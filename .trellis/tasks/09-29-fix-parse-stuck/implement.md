# 资料解析流水线卡死与不可恢复：执行计划

## 审查门禁

- **G1（进 Phase 2 前）**：`trellis-before-dev` 已读取 backend 与 frontend 两套 spec
  （`error-handling.md` 管异常分类、`logging-guidelines.md` 管 R3 的日志、`database-guidelines.md` 管状态迁移、`quality-guidelines.md` 管纯函数下移）。
- **G2（提交前）**：`task verify` 退出码 0；重点盯 `backend/tests/unit/services/test_material_service.py` 零回归。
- **G3（AC-9 前）**：执行真实 provider 端到端前**必须取得用户确认**（消耗 openai/baidu 配额）。

## 执行清单

### S1 — R1 惰性回收（后端）

- [ ] S1.1 先读 `backend/tests/unit/services/test_material_service.py` 中既有的状态迁移与
      `try_transition_version_status` 用例，确认回收要复用哪个口径，避免造第二套。
- [ ] S1.2 **先写失败测试**：造一个 `parse_status='queued'` 且时间早于阈值的版本，
      断言 `get_material` 之后它变成 `FAILED` + `failed_stage='worker_unavailable'`。
- [ ] S1.3 实现阈值常量（`10 分钟`，注释写明「queued 持续 N 分钟 ⟺ 无消费者」的等价性依据）。
- [ ] S1.4 在 `get_material` / `list_materials` 读路径接入判定，写回走**
      已有的 `try_transition_version_status`** 原子迁移，保证幂等。
- [ ] S1.5 补边界测试：恰好等于阈值 / 略小于阈值 / 已 `started`（不得回收）/ 已达终态（不得回收）。
- [ ] S1.6 确认写回动作在**只读语义的调用**下也不会意外提交事务导致调用方数据被回滚——
      实现时核对 session / commit 边界（`app/services` 是唯一允许开事务的层）。

### S2 — R2 放宽重派通道（后端）

- [ ] S2.1 **先写失败测试**：陈旧活跃版本调用 `trigger_parse` 能入队（队列长度 +1）。
- [ ] S2.2 **同时写防回归测试**：非陈旧活跃版本调用 `trigger_parse` 仍早退、队列长度不变；
      并发两次调用只 +1（守住 `:1451-1453` 的并发保证）。
- [ ] S2.3 在 `:1440-1449` 的早退分支加例外，迁移仍走 `try_transition_version_status`。
- [ ] S2.4 确认 `retry_material_pipeline`（只认 `FAILED`）**不改**——R1 的回收结果会让它自然可用。

### S3 — R3 启动期与 doctor 健康检查（后端）

- [ ] S3.1 在 lifespan 中加检查：`queue.provider == 'redis'` 时查询 RQ worker 注册表，
      零消费者 → `WARNING`（含 8 要素结构化字段与处置建议）。**不阻断启动**。
- [ ] S3.2 在 `app/cli/commands/doctor.py` 加同一检查项（同一判定逻辑，不复制实现）。
- [ ] S3.3 单测：有消费者 / 无消费者两条分支；非 redis provider 时跳过检查。

### S4 — R4 前端可见反馈与出口

- [ ] S4.1 先核对 `src/types/index.ts` 的 `MaterialItem` 是否透出 `failed_stage`；
      未透出则在 `api/adapters/material.ts` 补归一化（**适配层职责，不在页面里做字段兼容**）。
- [ ] S4.2 `materialState.ts` 新增 `isMaterialStaleQueued(material, now?)` 纯函数 +
      `PARSE_STALE_THRESHOLD_MS` 常量（注释指向后端同名常量）。
- [ ] S4.3 单测：阈值边界、`now` 注入、非 queued 状态一律 false。
- [ ] S4.4 工作台讲义卡片：陈旧 `queued` 渲染可行动文案 + 重试入口（复用既有 `handleManualParse`）。
      **不放宽 `canStartMaterialParse` 的语义**——它保持「只允许未开始的资料启动解析」。
- [ ] S4.5 `pages/course/index.vue` 的 `syncParseProgress`：取消静默 `catch {}`，
      轮询超时后给可见提示（保留最后一次状态，但说明「未拿到最新进度」）。
- [ ] S4.6 按 `design.md` 决策 5 的文案表实现 `failed_stage → 文案` 映射。

### S5 — 验证

- [ ] S5.1 **AC-1（停 worker）**：不启动 worker，上传一份测试资料并触发解析，
      等阈值后断言接口返回 `failed` + `worker_unavailable`。**建议用 `fake` provider 隔离变量**。
- [ ] S5.2 **AC-2（防误伤，最关键）**：worker 在跑的前提下走一次正常解析，
      确认不被回收、最终 `ready`。若真实 provider 太慢，先断言「`queued` 阶段未被回收」。
- [ ] S5.3 AC-3 / AC-4：重派与并发不重复入队（S2.2 的测试即为证据）。
- [ ] S5.4 AC-5：分别在无 worker / 有 worker 两种情况下启动 API，比对启动日志。
- [ ] S5.5 AC-6 / AC-7：前端组件单测 + 纯函数单测。
- [ ] S5.6 `task verify`。
- [ ] S5.7 **AC-9（需用户确认后执行）**：`task worker` 起 worker，观察那 3 个 job 被领取、
      三份实测资料的终态。**EICAR 那一份若表现不同，单独登记为新发现，不塞进本任务**。

### S6 — 收尾

- [ ] S6.1 回填 PRD 的 AC 勾选与证据。
- [ ] S6.2 若 S5.7 发现 worker 起来后仍有卡死（例如 pgvector 维度不匹配之类），
      按 Trellis 的「Phases can roll back」回到 Plan 补需求，**不在 Execute 里临时扩 scope**。
- [ ] S6.3 把「worker 必须与 API 一起启动」写进运维文档（`Taskfile.yml` 已正确，
      缺的是**知道要跑它**这件事——落到 README 或 `AGENTS.md` 的运行说明）。

## 回滚点

| 步骤 | 回滚方式 |
| --- | --- |
| S1 惰性回收 | 后端单文件改动；回滚代码即可，已写库的 `FAILED` 无需回滚（见 design.md 兼容性一节） |
| S2 重派放宽 | 同上；并发保证的防回归测试保留，回滚时它仍应通过 |
| S3 健康检查 | 独立提交，可单独回滚 |
| S4 前端 | 纯前端改动，独立提交 |

## 验证命令

```bash
# 后端门禁
cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports \
  && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80

# 单独跑受影响的用例（改一处跑一次，别等最后）
cd backend && uv run pytest tests/unit/services/test_material_service.py -x -q

# 偷看队列积压（诊断用，勿在验收脚本里依赖）
cd backend && uv run python -c "
import redis; r = redis.from_url('redis://127.0.0.1:6379/0')
print('queued jobs:', r.llen('rq:queue:zhilian'))"

# 起 worker（会真实调用 openai/baidu）
task worker

# doctor 检查项
cd backend && uv run python -m app.cli doctor
```
