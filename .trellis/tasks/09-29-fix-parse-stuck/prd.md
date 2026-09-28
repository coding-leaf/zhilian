# 资料解析流水线卡死与不可恢复

## Goal

让解析链路上任何一种「卡住」都**可诊断、可恢复、有出口**。
核心约束：不允许存在「用户什么都做不了、系统什么都不说」的静止状态。

## 现象（2026-09-29 用户实测）

「我有一个一小时前上传的文件，一直在解析，没有返回资料」——UI 上永久显示「正在抽取考点拓扑...」，无按钮、无提示、无失败。

## 根因：**已复现并定案**（非假设）

### 第一层（真正的根因）：**worker 在 Windows 上根本跑不起来**

**2026-09-29 本次侦察实测**：按项目自带的方式启动 worker（`task worker`，即
`ZHILIAN_QUEUE__PROVIDER=redis uv run python -m app.worker`），进程**启动后在第一个 job 上崩溃退出**：

```
Worker b1f3c6bdd65f498398aef65224e3323b: zhilian: ...parse_material_pipeline... (7c2861f1-...)
Worker ...: found an unhandled exception, quitting...
Traceback (most recent call last):
  File "rq/worker/worker_classes.py", line 52, in wait_for_horse
    pid, stat, rusage = os.wait4(self.horse_pid, 0)
AttributeError: module 'os' has no attribute 'wait4'
```

**成因**：`os.wait4` 与 `os.fork` 都是 POSIX-only。`app/worker.py:67` 已经写了
`SpawnWorker if os.name == "nt" else Worker`——但**这个分支救不了**：
`SpawnWorker(Worker)` 只重写了 `fork_work_horse`（`worker_classes.py:165`），
**它继承的是同一个 `Worker.wait_for_horse`（`:46`）**，照样调 `os.wait4`。
在本机 Python 上实测确认：`hasattr(os, 'wait4') == False`。

**结论**：这不是「用户忘了起 worker」，而是**项目文档指定的启动方式在 Windows 上必然失败**。
所以在此之前，任何资料都不可能被异步解析——包括当天早上那 4 份（它们必然走了同步路径：
`trigger_parse(sync=True)` 或 CLI，见 `services/material.py:1433`）。

**修复**（已实施，见 `app/worker.py`）：Windows 分支改用 `rq.SimpleWorker`。
它是唯一从 `BaseWorker` 派生的实现（MRO 实测为 `SimpleWorker → BaseWorker → object`），
**同进程执行任务，不触碰 fork/wait4**。
**已知代价**：同进程执行无法强杀超时任务——一个卡死的任务会阻塞整个 worker
（POSIX 下 `Worker` 会 fork 出 work horse 并在 `timeout + 60s` 后 `kill_horse`）。
解析流水线各外设调用自带超时，故接受此代价并在此留档。

### 第二层：worker 缺席时任务静默永久排队（**修复第一层后仍存在的代码缺陷**）

本次侦察在实测环境取得的证据：

| 证据 | 观测值 |
| --- | --- |
| Redis | 6379 在监听 |
| API 进程 | `uvicorn app.main:app --port 8000` 在运行（4 个进程） |
| **worker 进程** | **不存在**（无 `python -m app.worker`） |
| `rq:queue:zhilian` | **len = 3**，三个 job `status=queued`、`started_at=''`、`worker_name=''` |

数据库侧对应三份资料（`materials` ⨝ `material_versions`）：

| 资料 | title | status | parse_status | 卡住起点 (UTC) |
| --- | --- | --- | --- | --- |
| `32a72b49-ca9c-4af0-af13-29683b46a763` | EICAR 测试文件.txt | `parsing` | `queued` | 2026-09-28 18:17:21 |
| `a64949ed-0414-420e-bc5d-c3158f69dbc0` | VRChat_2026-08-04_2… | `parsing` | `queued` | 2026-09-28 18:16:52 |
| `62efb3b5-3dfe-4941-be1c-3751abe993d5` | Maven依赖管理.PDF | `parsing` | `queued` | 2026-09-28 16:59:44 |

三份均 `failed_stage = NULL`、`error_message = NULL`——**没有留下任何失败痕迹**。

**反证流水线本身完好**：同一环境当天 08:40–09:25 的 4 份资料均为 `ready`
（说明当时 worker 在跑，或走了同步解析），流水线具备把资料推到 `ready` 的能力。
**worker 在 16:59 之前停止**，之后所有上传全部静默排队。

### 代码缺陷：三层「不可恢复」放大了这个运维状态

运维状态（worker 没起）本身不是代码缺陷，但下面三处让用户**无路可走**，
且**一个字都不说**——这才是本任务要修的东西。

| # | 缺陷 | 锚点 | 后果 |
| --- | --- | --- | --- |
| D1 | 入队成功后无租约/超时回收 | `services/material.py:1440-1471` | 版本永久停在 `queued`，没人翻成终态 |
| D2 | 后端无重派通道 | `services/material.py:1440-1449`、`:809-810` | `trigger_parse` 对活跃状态**直接早退**（不报错）；`retry_material_pipeline` **只接受 `FAILED`**。卡在 `queued` 的版本在 API 层两个入口都进不去 |
| D3 | 前端无重派入口、无超时反馈 | `utils/materialState.ts:10-18`、`pages/index/index.vue:117-133`、`pages/course/index.vue:230-236` | `canStartMaterialParse` 只认 `pending`；`isMaterialParsing` 为真时模板**只渲染 ⌛**；轮询 20×1.5s 超时后 `catch {}` 保留旧状态，页面永远显示「正在抽取考点拓扑...」 |

**D2 是最要命的一处**：即使用户后来把 worker 起起来，**已卡住的资料在 UI 和 API 两层都无法重新派发**，
只能删除重传。用户当天连传三份全部撞上这堵墙。

## Change Boundary

### In scope

- **R1 惰性回收（stale reaper）**：读取资料时判定「已入队但长期未被领取」，翻成终态 `FAILED`。
- **R2 放宽重派通道**：让 `trigger_parse` 能对「活跃但陈旧」的版本重派，复用已有的原子状态迁移保护。
- **R3 启动期 worker 健康检查**：API 起在 redis 队列模式但没有消费者时，**大声记日志**。
- **R4 前端可见反馈与出口**：区分「排队中」与「排队过久」；给重试入口；轮询超时不静默。

### Out of scope（明确不做）

- **不改解析算法**（`parse_material_pipeline` 的分块/OCR/知识抽取/embedding 逻辑）——本次它是完好的，有 4 份 `ready` 为证。
- **不换队列实现**（不引入 Celery / 不改成进程内线程），`immediate_mode` 保持原样。
- **不做「自动把 worker 拉起来」**：进程编排属运维边界，代码只负责**发现并说清**，
  不负责偷偷起进程（那会带来僵尸进程与端口冲突这类更难查的问题）。
- **不改 `Taskfile.yml` 的 `worker` 目标**：它已经是对的（`ZHILIAN_QUEUE__PROVIDER=redis` + `uv run python -m app.worker`）。
  本次的问题是**没人知道要跑它**，由 R3 + 文档解决。

## Requirements

### R0 — 让 worker 在 Windows 上真的能跑（**已在侦察阶段实施**）

- Windows 分支改用 `rq.SimpleWorker`；POSIX 分支保持 `rq.Worker` 不变。
- 必须保留说明代价的注释（同进程执行、不能强杀超时任务），避免后人误以为这是等价替换。
- **不得**改成「Windows 上直接抛异常拒绝启动」——那等于把可用性判给平台。
- **验证**：`uv run python -m app.worker` 启动后能领取并完成积压 job，
  且 `hasattr(os, 'wait4') == False` 的环境下不再抛 `AttributeError`。

### R1 — 惰性回收：入队过久即判失败

- **判据必须无歧义**：只对 `parse_status == 'queued'`（**尚未被领取**）的版本生效。
  依据：只要 worker 活着，`queued` 会在**秒级**被领取（RQ 轮询队列），
  因此「`queued` 持续 N 分钟」等价于「没有消费者」。这条判据**不会**把「LLM 跑得慢」误判为卡住——
  跑得慢的任务处于 `started` 状态，由 RQ 自己的 `timeout=1800` 与
  `app.worker.handle_job_terminal_failure` 兜底。
- **阈值**：`N = 10` 分钟，写成常量并注明依据。
- **落点**：在 `MaterialService` 读取路径（`get_material` / `list_materials`）上做惰性判定——
  **不能依赖 worker 侧的定时清扫**，因为「worker 不在」正是要检测的场景，清扫器本身也不会运行。
- **终态写回**：`parse_status = FAILED`、`failed_stage = 'worker_unavailable'`、
  `error_message = '后台解析服务未运行，任务未被处理'`；资料主表 `status = FAILED`。
- **幂等**：同一版本只回收一次（借助已有的 `try_transition_version_status` 原子迁移）。

### R2 — 放宽重派通道

- `trigger_parse` 的早退分支（`:1440-1449`）增加一个例外：版本处于**活跃状态**且**已陈旧**时，
  允许原子迁移 `活跃 → QUEUED` 并重新入队。
- **必须复用** `try_transition_version_status`，保持「两个并发请求不会重复入队」的既有保证
  （该保证的注释见 `:1451-1453`，不得回退）。
- 非陈旧的活跃状态**保持现有早退行为**——并发重复入队是真实风险，不能为了好用来掉它。
- 依据 R1 的回收结果，`retry_material_pipeline`（只认 `FAILED`）会自动变得可用，**不需要放宽**。

### R3 — 启动期与可观测的 worker 健康检查

- API 启动（lifespan）时：若 `queue.provider == 'redis'`，查询 RQ 的 worker 注册表；
  **零消费者**时输出一条 `WARNING` 级别结构化日志（含 `error_code` 与处置建议）。
- **不阻断启动**：本地开发完全可能只想跑 API 不跑 worker，硬失败会拦住正常开发流程。
- 在现有 `app/cli/commands/doctor.py` 中增加同名检查项，让 `doctor` 能给出可操作的结论。

### R4 — 前端可见反馈与出口

- `materialStatusText` 之外新增一个「陈旧判定」纯函数（可单测，不依赖 `uni.*`）。
- 工作台讲义卡片：`queued` 且陈旧 → 文案从「排队中」改为可行动的提示，
  **并渲染重试入口**（复用既有的 `handleManualParse`，不再只给 ⌛）。
- `pages/course/index.vue` 的 `syncParseProgress`：轮询超时不静默吞掉，
  在页面上给一条可见提示（当前是 `catch {}` 后保留旧状态）。
- 文案必须区分「排队中」与「后台服务未运行」——这是用户判断该找谁的关键信息。

## Acceptance Criteria

- [ ] AC-1 在**停掉 worker** 的前提下上传一份资料并触发解析，等待阈值后：
      `GET /materials/{id}` 返回该资料 `status='failed'`、`parse_status='failed'`、
      `failed_stage='worker_unavailable'`。证据：接口响应 + 数据库查询。
- [ ] AC-2 **不停 worker** 的正常解析（含真实 LLM 慢调用）**不被误回收**：
      造一个运行时间超过阈值的解析，确认其 `queued` 阶段短于阈值、`started` 阶段不受 R1 影响，
      最终正常到 `ready`。**这是 R1 最关键的防误伤验收。**
- [ ] AC-3 陈旧版本经 `POST /materials/{id}/parse` 可以重新入队，且并发两次调用只产生一个 job
      （断言队列长度 +1 而非 +2，复用既有原子迁移的单测口径）。
- [ ] AC-4 非陈旧的活跃版本调用 `/parse` 仍早退、不入队（不回归 `:1451-1453` 的并发保证）。
- [ ] AC-5 API 在 redis 队列模式且无消费者时启动，日志出现 WARNING 级检查项；有消费者时不出现。
- [ ] AC-6 前端：工作台对陈旧资料渲染重试入口，且「排队中超过 N 分钟」与「后台解析服务未运行」
      在文案上可区分。证据：组件单测 + 编译产物。
- [ ] AC-7 全新纯函数有单测覆盖（含边界：恰好等于阈值、已 `started` 的版本、已达终态的版本）。
- [ ] AC-8 `task verify` 全绿；`backend/tests/unit/services/test_material_service.py` 既有用例零回归。
- [ ] AC-0（R0）worker 在 Windows 上能启动并完成积压 job。**侦察阶段已取得初步证据**：
      改用 `SimpleWorker` 后启动，`rq:queue:zhilian` 由 3 降为 0，首个 job 报
      `Successfully completed ... in 0:00:01.811451s`。待 `task verify-backend` 覆盖。
- [ ] AC-9 端到端：启动 worker 后，卡住的 3 份实测资料（见上表）各自拿到**明确的终态**。
      **侦察阶段已观测到两条**，实现阶段需复核并留档：
      | 资料 | 观测终态 | 判定 |
      | --- | --- | --- |
      | `a64949ed` VRChat | `retake_required` / `failed_stage=ocr_quality_gate` | **流水线正确**：OCR 质量门禁判定页面内容不足，业务上要求重拍。不是缺陷 |
      | `32a72b49` EICAR | 观测到 `parse_status=extracting_knowledge`（进行中） | 待最终确认 |
      | `62efb3b5` Maven | 修复前被崩溃的 worker 弹出后遗留在 `rq:wip:zhilian` | **RQ 自身的崩溃恢复**：需等死掉 worker 的 TTL（默认 420s）过期才会被回收重排。**这不是本任务的缺陷**，但要在验收时确认它最终确实被重排，而不是永久滞留

## Notes

- **本次不做「删除重传」**：那 3 份资料本身完好，卡住的是调度。修好 R1/R2 后它们应当可恢复。
- **实测环境用的是真实 provider**（`ZHILIAN_LLM__PROVIDER=openai`、`ZHILIAN_EMBEDDING__PROVIDER=openai`、
  `ZHILIAN_OCR__PROVIDER=baidu`、`ZHILIAN_SEARCH__PROVIDER=pgvector`）。因此 AC-9 会**真实消耗外部 API 配额与时间**，
  执行前须获得用户确认；AC-1/AC-2 应尽量在 `fake` provider 下完成以隔离变量。
- **`EICAR 测试文件.txt` 是杀毒测试样本**（标准 EICAR 字符串）。worker 一旦跑起来，
  该 job 会真正执行；若链路中任何一层对上传内容做安全扫描，其表现会与其他两份不同。
  AC-9 若出现这一份与另两份**不同**的失败形态，按「新发现」单独登记，不要顺手塞进本任务的修复范围。
- **D3 的 `canStartMaterialParse` 门禁本身是对的**（只允许未开始的资料启动解析），
  它缺的是「陈旧活跃态」这一分支。修 R4 时不要把它放宽成「任何非终态都能点」。
