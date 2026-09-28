# 资料解析流水线卡死与不可恢复：技术设计

## 核心设计决策

### 决策 1｜回收判定只认 `queued`，不认「跑得慢」

**选择**：`parse_status == 'queued'` 且 `enqueued_at`/`updated_at` 早于 10 分钟 → 回收。

**为什么不按「活跃阶段总时长」判定**：那会把**真实跑得慢**的解析误杀。实测环境用的是真实
provider（openai LLM + openai embedding + baidu OCR），一份大 PDF 的知识抽取单阶段就可能跑几分钟，
整条流水线上十分钟完全正常。用总时长判定必然误伤，而误伤一个正在正常推进的任务比不回收更糟。

**为什么 `queued` 是干净判据**：RQ worker 以轮询方式取队列，只要消费者活着，
`queued → started` 在**秒级**完成。因此 `queued` 持续 10 分钟 ⟺ 没有消费者。这是**等价**关系，不是启发式。

**已覆盖的相邻场景**：

| 状态 | 由谁兜底 |
| --- | --- |
| 任务已被领取但卡死 | RQ 自身 `timeout=1800`（见 job hash 的 `timeout` 字段）+ `app.worker.handle_job_terminal_failure` |
| 任务执行失败并重试 | 既有 `retry_intervals=[10,30,90]` + `retries_left=3` |
| **入队但无人领取** | **本任务 R1（当前唯一缺口）** |

### 决策 2｜回收放在 API 读路径，不放 worker 侧定时清扫

**选择**：`MaterialService.get_material` / `list_materials` 内做惰性判定。

**理由**：要检测的正是「worker 不存在」。一个跑在 worker 里的清扫器，在需要它的场景下**必然不在运行**——
这是自相矛盾的设计。放在读路径则永远可用：用户一打开工作台就会触发判定。

**代价与取舍**：读路径变重（多一次陈旧判定）。收益是判定**必然发生**在用户看得到的时刻。

**不做「定时任务兜底」**：无 worker 时它不跑；有 worker 时 RQ 自己的超时已覆盖。加了是重复。

### 决策 3｜回收为 `FAILED`，而不是新增 `stale` 状态

**选择**：复用终态 `FAILED`，用 `failed_stage='worker_unavailable'` 承载精确原因。

**理由**：`FAILED` 这条路径**上下游都已存在且验证过**——
后端 `retry_material_pipeline`（`services/material.py:779`）只接受 `FAILED`；
前端工作台对 `status === 'failed'` 已经渲染「重试解析」按钮（`pages/index/index.vue:117-122`）。
引入新状态需要同时改：状态机、`materialState.ts` 三个函数、模板分支、后端重试门禁、以及所有相关单测——
而收益只是语义更贴切。

**代价**：`FAILED` 的字面含义把责任指向了资料本身，而实际是运维问题。
**缓解**：`failed_stage` 是机器可读的区分位，前端按它给不同文案（见决策 5）。
这是「用已有词汇 + 一个精确字段」换「不动状态机」，权衡后取前者。

### 决策 4｜重派放宽也要过原子迁移

**选择**：`trigger_parse` 的早退分支增加「陈旧即可重派」例外，但仍必须走
`try_transition_version_status(expected_from=陈旧活跃态, to=QUEUED)`。

**理由**：`:1451-1453` 的注释明确记录了这个原子迁移是为了防止「两个并发请求各入队一次」，
导致同一版本被两个 worker 同时解析（重复 OCR/LLM 开销 + 重复切片）。放宽重派**不能**把这个保证弄丢。
条件更新失败即说明别的请求已经推进了它，本次直接返回——非陈旧的活跃态**保持原早退行为**。

### 决策 5｜文案区分「排队中」与「后台服务未运行」

用户看到「排队中」会等，看到「后台解析服务未运行」会去启 worker 或找运维。这是完全不同的人的不同动作，
必须区分。前端按 `failed_stage` 取值：

| `failed_stage` | 用户可见文案 | 可行动作 |
| --- | --- | --- |
| `worker_unavailable` | 后台解析服务未运行，任务未被处理 | 「重试解析」 |
| `queue_dispatch` | 解析任务提交失败，请重试 | 「重试解析」 |
| 其他 / `NULL` | 解析失败 | 「重试解析」 |

### 决策 6｜健康检查只警告不阻断

`queue.provider == 'redis'` 且 RQ worker 注册表为空 → **WARNING 日志**，不抛异常。

**理由**：只想跑 API 不跑 worker 是合法的开发姿势（例如只调前端接口）。硬失败会拦住正常开发。
但「忘了起 worker」必须能被看见，所以用**结构化 WARNING**（复用既有 8 要素日志口径）而不是静默。

同一检查项加入 `app/cli/commands/doctor.py`，让 `doctor` 给出可操作结论——
运维路径要有**一个**明确的检查入口。

## 前端契约

新增纯函数（放 `src/utils/materialState.ts`，与既有三个函数同址）：

```ts
/** 入队后长期未被领取：等价于后台解析服务未运行。阈值与后端保持一致。 */
export const PARSE_STALE_THRESHOLD_MS = 10 * 60 * 1000

export function isMaterialStaleQueued(material: MaterialState, now?: number): boolean
```

- `material` 形参沿用既有 `MaterialState`（`Pick<MaterialItem, 'status' | 'parse_status'>`），
  需**扩展**为也 pick 时间字段（`MaterialItem` 现有时间字段名以 `types/index.ts` 为准，实现时核对）。
- `now` 可注入 → 纯函数可单测，不依赖真实时钟（符合 `quality-guidelines.md`「逻辑下移到纯函数再测」）。
- **阈值前后端各写一份是可接受的**：后端是权威判定（写库），前端只做展示态判断。
  为避免漂移，两处常量都要带指向对方的注释。

## 兼容性与回滚

- R1/R2/R3/R4 相互独立，可分开提交；R4 依赖 R1 写回的数据形态（`failed_stage`），
  但**不依赖 R1 的代码**——它读的是数据库里已有的 `failed_stage` 字段（`MaterialItem` 是否已透出该字段需核对，
  未透出则由 R4 补一条 `Wire → MaterialItem` 的适配）。
- **回滚影响**：R1 一旦写库，被回收的版本就是 `FAILED`。回滚代码不会自动把它们变回 `queued`，
  但这**不是损失**——它们本来就已经卡死；回收后反而获得了「重试解析」这一条可用路径。
