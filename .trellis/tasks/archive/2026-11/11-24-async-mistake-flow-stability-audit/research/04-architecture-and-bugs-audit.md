# 全项目架构体检、Bug 与稳定性深度审计报告（Issue #4）

> **任务目录**：`.trellis/tasks/11-24-async-mistake-flow-stability-audit`
> **审计范围**：`backend/app/**`、`miniprogram/src/**`、`deploy/docker-compose.yml`、`backend/pyproject.toml`、`Taskfile.yml`、`.trellis/spec/**`
> **审计性质**：只读源码实证审计（所有缺陷均经源码逐行核验，附精确 `file:line` 锚点与触发路径，已排除文档注释说明的有意设计及信任边界误报）

---

## 0. 工作区状态与近期变更热点

- **工作区脏状态**（`git status --short`）：
  - 4 个 Trellis 流程文件有未提交修改：`.agent/plugins/trellis-agy/agents/trellis-{check,implement,research}.md`、`.trellis/workflow.md`。
  - 业务代码（`backend/`、`miniprogram/`、`deploy/`）工作树干净。
- **近期高频演进热点**（`git log -n 15 --oneline`）：
  - RAG / PDF VLM 脏页转录与 Rerank 升级（`fe04fbc`、`8561de6`、`b33de3c`）
  - LangGraph 助教图与题目级多轮记忆 / 防剧透（`fd347e7`、`07a1964`、`6eb87da`）
  - 这些近期新增的「多阶段同步/后台混合链路」与「跨进程状态同步」恰好也是本次审计发现隐患最集中的区域。

---

## 1. 现状架构盘点（Intended vs Reality）

### 1.1 已落地且运行良好的架构基线（**应当保留**）

| 维度 | 事实源 | 现状评估 |
|---|---|---|
| **后端六条分层契约** | `backend/pyproject.toml:72-139` | 实跑 `uv run lint-imports`：**208 files / 1115 deps，6 kept, 0 broken**。`api → services → repositories`、`core.algorithms` 纯算法核隔离、`api` 禁止直连 `integrations` 均被 CI 刚性守护。 |
| **后端多租户仓储隔离** | `backend/app/repositories/*.py`、`backend/app/models/base.py` | 全表 `TenantModelMixin(user_id)`，抽检 `practice`/`grading`/`diagnosis`/`material`/`question` 仓储方法均显式绑定 `user_id`；`api/v1/**` 所有受保护端点统一使用 `Depends(get_current_user)`（未使用跳过库校验的 `get_current_user_id`）。 |
| **后端同步路由并发规范** | `backend/app/api/v1/*.py`、`backend/app/api/deps/auth.py` | 全部路由端点均为普通 `def`（由 FastAPI 自动派发线程池），`async def get_current_user` 通过 `run_in_threadpool` 卸载查库（`auth.py:199`），未在路由层直接阻塞 asyncio 事件循环。 |
| **后端 Protocol + Fake 适配层** | `backend/app/integrations/*/{protocol,fake,factory}.py` | LLM/OCR/Embedding/Rerank/Search/Storage/Queue/Idempotency 9 类外设均抽象为 Protocol + Fake，配合 `mypy --strict`、`ruff`、Alembic 模型一致性单测与 80%+ 分支覆盖率，离线可测性极佳。 |
| **前端轻量分包 + Wire Adapter** | `miniprogram/src/{api/adapters,types,stores,subpackages}/` | 零重型 UI 框架，全仓 32 个 `.vue` 严格 `<= 270` 行，按域拆分的 `api/modules` + `api/adapters` 隔离了后端字段演进；`poller.ts`、`draftQueue.ts`、`loadingGuard.ts`、`requestError.ts` 具备清晰的工程抽象。 |

### 1.2 现实与文档/设计意图之间的结构性漂移（Architecture Drift）

1. **巨型 Service 门面膨胀**：虽然 `max-complexity = 15` 约束了单函数复杂度，但核心 Service 已演化为 1300–2000 行巨型类：
   - `backend/app/services/question.py`（1983 行，同时承担出题编排、异步任务管理、题库 CRUD、批次聚合、题目/范围两套 AI 助教）
   - `backend/app/services/material.py`（1612 行）、`practice.py`（1387 行）、`diagnosis.py`（1371 行）、`core/errors.py`（1252 行）。
2. **后台任务队列存在两套冲突的落库/入队语义，且缺乏统一 Job 抽象**：
   - `MaterialService.trigger_parse`（`material.py:1414-1416`）与 `QuestionService.create_generation_job`（`question.py:1035-1045`）是 **先 commit 再 enqueue**；
   - `PracticeService.submit_practice`（`practice.py:1048-1055, 1186`）与 `PracticeService.retry_grading`（`practice.py:1322-1331`）却是 **先 enqueue 再 commit**（导致 Worker 竞态读到旧状态）。
   - 三类任务（解析/判题/出题）各自发明一套状态机、轮询端点与终态回写，没有统一的任务表与退避/重试可见性模型。
3. **单 Worker 进程队头阻塞（Head-of-Line Blocking）**：
   - `deploy/docker-compose.yml:39-59` 仅起单个 `worker` 容器，消费 `[zhilian_high, zhilian]`（`worker.py:99`）。一旦 `parse_material_pipeline`（2–5 分钟长任务）占用 Worker，即使高优队列 `zhilian_high` 的 `grading_jobs` 也必须干等数分钟。
4. **同步 DB Session 与长耗时外部 I/O 强耦合**：
   - 请求级/任务级单一 `Session` 在调用前先 `SELECT` 打开事务，随后带着 `idle in transaction` 连接去同步等待 30–300 秒的 LLM/VLM/S3 请求（详见证据 §2.2）。
5. **LangGraph `MemorySaver` 空转开销**：
   - `backend/app/integrations/llm/coach_graph.py:675, 734` 每次 `run_coach_graph()` 都重新编译整张 `StateGraph` 并新建一个一次性 `MemorySaver()`，执行完即丢弃；真实多轮记忆由外层 `CoachSessionMemory` 维护，导致图编译与内存检查点纯属冗余开销。
6. **配置与文档漂移**：
   - `backend/pyproject.toml:12` 声明 `sqlalchemy[asyncio]`，但全后端均为同步 `Session`；`pypdf` 与 `pymupdf` 同时保留。
   - `AppSettings.idempotency.provider` 默认 `"memory"`（`config.py:194-197`），而 `queue.provider` 默认 `"redis"`（`config.py:168-171`），导致默认部署下幂等层既跨进程失效又持续内存泄漏。
   - `.trellis/spec/frontend/state-management.md`（2026-09-29）仍记载「5 个域 store」及已删除的死状态 `practiceStore.latestDiagnosis`，遗漏了现今最大 store `backgroundTask.ts`（509 行）。
   - `miniprogram/src/utils/request.ts:33` 定义了 `silentToast?: boolean` 选项，但全前端 **0 处调用方传 `silentToast: true`**，导致后台静默轮询与草稿队列失败时直接弹窗并打断用户当前页面 loading。

---

## 2. 实证 Bug 与稳定性隐患清单

> 严重度定义：**P0（安全/数据损坏/流程死锁）**、**P1（高频功能缺陷/竞态/资源泄漏）**、**P2（稳定性短板/体验割裂/可维护性隐患）**。

### P0 — 严重安全、数据一致性与死锁级缺陷

#### [P0-1] 生产环境微信登录鉴权后门（任意伪造账号登录）
- **位置**：`backend/app/services/auth.py:108-149`
- **事实依据**：
  - `_resolve_wechat_openid(code)` 在第 109–112 行 **无条件优先拦截** `code == "dev_code"` 与 `code.startswith(("dev_", "mock_"))`，**完全未校验 `settings.env != "production"`**，且执行顺序在真实微信 `jscode2session`（第 115 行）之前！
  - 第 145–148 行兜底回退在未配置 `wechat_app_id`/`wechat_app_secret` 时直接将任意 `code` 映射为 `wx_{code}`，而 `main.py:41` 启动期仅校验 `validate_secret_key`，**未对生产环境微信凭据缺失做 fail-fast**。
- **触发路径**：生产环境公网攻击者向 `POST /api/v1/auth/login` 发送 `{"code": "dev_code"}` 或 `{"code": "dev_anything"}`，即可绕过微信鉴权直接换取有效 JWT；若 `wx_dev_deterministic_user` 存在测试数据，直接越权登录该账号。
- **修复建议**：将 `dev_code`/`dev_`/`mock_` 分支严格限定在 `settings.env != "production"`；生产环境启动校验强制要求 `wechat_app_id` 与 `wechat_app_secret` 非空，且禁止落入第 3 段兜底映射。

#### [P0-2] 交卷与重试判题「先入队、后提交事务」竞态，导致 Worker 误判非法状态失败
- **位置**：
  - `backend/app/services/practice.py:1041-1055` + `1186-1194`（`submit_practice`）
  - `backend/app/services/practice.py:1311-1331`（`retry_grading`）
  - 对比消费端：`backend/app/services/grading.py:206-214`
- **事实依据**：
  - `submit_practice` 在第 1041 行将 `practice.status` 改为 `SUBMITTED`（尚未 `commit`），随即在第 1048 行 → 第 1186 行调用 `self.queue.enqueue("grading_jobs", ...)`，**直到第 1055 行才 `self.session.commit()`**。
  - `retry_grading` 在第 1311 行 CAS 更新为 `SUBMITTED`（未 `commit`），第 1322 行立即入队高优队列 `zhilian_high`，**第 1331 行才 `self.session.commit()`**。
- **触发路径**：在 PostgreSQL（READ COMMITTED）+ 独立 Redis/RQ Worker 下，Worker 往往在 1–5ms 内弹出 `grading_jobs` 并新开会话查询 `Practice`，此时 API 事务尚未提交，Worker 读到旧状态 `in_progress`（`submit_practice`）或 `partially_graded`（`retry_grading`），在 `grading.py:206-214` 直接抛 `GradingNotAllowedError`（或 `submit` 随后 `commit()` 失败时 Worker 消费幽灵任务）。
- **修复建议**：统一向 `MaterialService.trigger_parse` / `QuestionService.create_generation_job` 对齐：**先 `commit()` 落库状态，再 `enqueue()`；入队异常时以补偿短事务回写可恢复状态（如 `partially_graded`）**（或引入本地事务表/Outbox）。

#### [P0-3] 「退步知识点识别」在全部真实交卷/判题链路中恒为空（双写覆盖基线）
- **位置**：
  - `backend/app/services/practice.py:1167-1172` + `1055-1062`（纯客观题路径）
  - `backend/app/services/grading.py:325-346`（混卷/主观题/自评/重判路径）
  - `backend/app/services/diagnosis.py:593-605`（`generate_diagnosis_report`）
- **事实依据**：
  - 在两种判题完成后，系统先调用 `DiagnosisService.sync_practice_learning_state(...)`，该方法内部先执行 `calculate_and_update_mastery(...)` 将**本次练习后的最新掌握度**写入并提交至 `mastery_records`。
  - 紧接着（同毫秒内）调用 `ensure_diagnosis_report(...)` → `generate_diagnosis_report(...)`。后者在第 593 行读取 `previous_records = list_mastery_records_by_knowledge_point_ids(...)` 作为「练习前基线」，再于第 599 行重算 `calculate_and_update_mastery(...)` 得到 `current_record_map`。
  - 因为第 593 行读到的已是刚刚提交的「练习后分数」，`previous_score` 永远等于 `current_score`，`score_delta` 恒为 `0.0`，导致 `synthesize_diagnosis_report` 永远无法识别任何退步知识点（`regressed_knowledge_points == []`），且白白重复计算一遍掌握度与错题同步。
- **触发路径**：任意真实用户完成练习并进入诊断报告页（单测因直接调用 `generate_diagnosis_report` 绕过了 `sync_practice_learning_state`，未能暴露该缺陷）。
- **修复建议**：若练习已进入 `COMPLETED`，合并「掌握度计算 + 错题同步 + 诊断报告生成」为单次流水线（先读旧 `previous_records`，再更新掌握度并生成报告），不再先 `sync_practice_learning_state` 覆盖旧分数再调用 `ensure_diagnosis_report`。

#### [P0-4] 自评覆盖 / AI 重判后 `DiagnosisReport` 永久陈旧，结果页总分与诊断指标自相矛盾
- **位置**：
  - 后端：`backend/app/services/grading.py:615, 763` → `grading.py:343` → `backend/app/services/diagnosis.py:456-461, 555-569`
  - 前端：`miniprogram/src/subpackages/report/composables/useReportDetail.ts:39, 47-50, 126-134`
- **事实依据**：
  - 用户在结果页提交自评（`POST /grading/self-evaluate`）或 AI 重判（`POST /grading/regrade`）后，`GradingService` 更新了 `AttemptItem.score`、`Practice.total_score` 和 `MasteryRecord`，随后调用 `ensure_diagnosis_report()`；前端紧接着调用 `loadReportIfGraded()` → `POST /practices/{id}/diagnosis`。
  - 但 `ensure_diagnosis_report()`（`diagnosis.py:456-461`）与 `generate_diagnosis_report()`（`diagnosis.py:555-569`）见到已有 `DiagnosisReport` 即直接幂等返回旧行，**永不重算**。
- **触发路径**：主观题原判 0 分（错题 1、得分率 50%），用户自评改为满分后，页面顶部 `totalScore`（读自 `session.total_score`）和题卡变为满分，但 `wrongCount`（`useReportDetail.ts:48` 优先读 `report.wrong_count`）、`score_rate`、`weak_knowledge_points` 仍永久显示旧的错误结果。
- **修复建议**：在 `DiagnosisService` 新增 `refresh_diagnosis_report(user_id, practice_id)`（或支持 `force_refresh=True`），在 `self_evaluate_attempt` 与 `regrade_attempt` 改动最终得分后原地更新已有 `DiagnosisReport` 行。

#### [P0-5] 前端 `draftQueue.reset()` 缺少代际隔离，切题/切换练习时在途草稿失败会永久死锁新练习交卷
- **位置**：
  - `miniprogram/src/utils/draftQueue.ts:49-72, 108-114`
  - `miniprogram/src/stores/practice.ts:76-86, 89-95`
- **事实依据**：
  - `draftQueue.reset()` 仅清空 `latest`/`lastAnswer`/`failures`/`workers` 四个 Map，**未递增代际号（epoch/generation）去作废仍在飞行的 `run()` 协程**。
  - 同时 `practice.ts:77-81` 的 saver 回调在执行时动态读取 `currentSession.value?.id`。
- **触发路径**：用户在练习 A 作答（`apiSavePracticeDraft` 在途）→ 立即切换到练习 B（`initPractice` 调 `draftQueue.reset()`）：
  1. 若练习 A 的在途请求在 200ms 后网络失败，`draftQueue.ts:58` 会把 `questionId_A` 写入**练习 B 的 `failures` Map**；
  2. 练习 B 交卷时 `draftQueue.flush()` 因 `failures.size > 0` 恒返回 `false` 阻断交卷；
  3. 用户点击顶部「重试全部」调 `retryAllDrafts()`，但 `lastAnswer` 在 `reset()` 时已被清空，`if (lastAnswer.has(questionId_A))` 为 `false`，该失败项永远无法清除，**练习 B 彻底无法交卷**。
- **修复建议**：在 `createDraftQueue` 引入自增 `epoch` 计数器（`reset()` 时 `epoch += 1`），`run()` 与 `finally` 中一旦 `myEpoch !== epoch` 立即静默退出，不触碰任何 Map 也不触发 `notify()`；且 `enqueue` 应把 `practiceId` 与 `questionId` 绑定进任务载荷，避免动态读 `currentSession.value?.id`。

---

### P1 — 高频稳定性、并发、资源泄漏与契约缺陷

#### [P1-1] 长耗时 LLM / VLM / S3 I/O 期间长期占用数据库事务与连接池（`idle in transaction`）
- **位置**：
  - `backend/app/services/grading.py:199-285`（`grade_practice`：先 `SELECT` 拿连接，再串行跑全部主观题 LLM 判分并持有行锁，最后第 285 行才 `commit`）
  - `backend/app/services/grading.py:677-762`（`regrade_attempt`：先 `SELECT` 开事务，第 715 行同步等 30–90s LLM，第 762 行才 `commit`）
  - `backend/app/services/knowledge.py:257-310` + `backend/app/services/material.py:549-592`（`_validate_and_load_snippets` 先 `SELECT` 开事务，随后跑多批 × 最多 3 轮 LLM 抽取，且 `material.py:573` 在未提交的 `DELETE/INSERT` 写锁事务内同步执行 `storage.put_object` 上传 S3）
  - `backend/app/services/question.py:1152-1173`（`run_generation_job`：`_prepare_kp_work_specs` 先 `SELECT` 开事务，再并发跑 LLM/Embedding）以及同步端点 `ask_coach` / `ask_scoped_coach` / `generate_questions`（FastAPI 请求级 `Session` 全程绑定到整个 90s 同步 LLM 请求）。
- **风险影响**：默认连接池 `pool_size=10, max_overflow=20`（`config.py:42-49`）。高并发或慢 LLM 抖动时，仅 30 个在途助教/重判/出题请求就会耗尽全部数据库连接，导致 `/auth/login`、`/health` 等短平快接口全线排队 30s 后 500 超时；PostgreSQL 上长时间 `idle in transaction` 还会阻塞 `VACUUM` 并触发 `idle_in_transaction_session_timeout` 断连。
- **修复建议**：严格落地「短事务读取 → 释放 Session/连接执行纯外部 I/O → 短事务写回」三段式边界（或至少在进入 LLM/S3 前调用 `session.rollback()`/`commit()` 归还连接，长任务中用 `session_factory` 开启独立短事务）。

#### [P1-2] Worker 重试语义冲突：业务代码在 RQ 重试前已提前写死 `status = failed`
- **位置**：
  - `backend/app/services/question.py:1192-1203`（`run_generation_job` 捕获异常立即写 `job.status = FAILED` 并 commit，然后再 `raise` 给 RQ）
  - `backend/app/services/material.py:605-616`（`parse_material_pipeline` 调 `mark_pipeline_failed` 立即写 `MaterialStatus.FAILED` / `ParseStatus.FAILED` 并 commit，再 `raise` 给 RQ）
  - 对比：`backend/app/integrations/queue/rq_adapter.py:61-68`（配置 `Retry(max=3, interval=[10, 30, 90])`）与 `backend/app/worker.py:220-269`（明确注释仅在 `not job.should_retry` 时回写终态失败）。
- **触发路径**：LLM/VLM 出现一次偶发 502/超时 → 任务第 1 次执行即把 DB 改成 `failed` → 前端轮询立即看到 `failed` 并停止轮询、向用户报错 → 10 秒后 RQ 自动重试成功并静默覆盖 DB 为 `completed`/`ready`，前后端状态彻底割裂。
- **修复建议**：区分「不可重试业务错（4xx/格式错误）」与「可重试基础设施错（网络/超时/5xx/429）」；对可重试错误仅回滚并 `raise` 交由 RQ 重试（可把进度文案标为重试中），终态 `FAILED` 统一交由 `handle_job_terminal_failure` 在 `not job.should_retry` 时落盘。

#### [P1-3] Worker 每任务新建 `AppContainer` + 适配器未实现 `close()` 导致连接池泄漏
- **位置**：
  - `backend/app/worker.py:86-90, 160-168, 178-187, 199-210`
  - `backend/app/integrations/container.py:461-497`
  - `backend/app/integrations/queue/rq_adapter.py:36`、`idempotency/redis.py:66`、`storage/s3.py`
- **事实依据**：
  - `worker.py` 每次执行任务都调用 `AppContainer.create()`，最后调用 `asyncio.run(container.shutdown())`。
  - 扫描全 `backend/app/integrations/`，**仅 `BaiduOCRAdapter` 实现了 `close()`**；`RQQueueAdapter`（持有 `Redis.from_url`）、`RedisIdempotencyAdapter`（持有 `redis.from_url`）、`S3StorageAdapter`（持有 boto3 client）均无 `close()`/`shutdown()`。
  - 在 Windows 本地 `SimpleWorker`（单进程常驻执行所有任务，`worker.py:106`）下，每跑一个任务就永久泄漏一组 Redis `ConnectionPool` 与 boto3 连接池；且 `RQQueueAdapter:36` 与 `RedisIdempotencyAdapter:66` 创建 Redis 客户端时均**未透传 `settings.redis.timeout` / `max_connections`**（无 socket 超时保护）。
- **修复建议**：为 Redis/S3 适配器补齐 `close()` 方法并接入 `settings.redis.timeout`；在 `SimpleWorker` / Worker 进程级复用单例 `AppContainer`（而不是每任务重建引擎与连接池）。

#### [P1-4] `MemoryIdempotencyAdapter` 无界内存泄漏 + 默认值与 Redis 队列不匹配
- **位置**：`backend/app/integrations/idempotency/memory.py:31, 108-133`、`backend/app/core/config.py:194-197`
- **事实依据**：
  - `MemoryIdempotencyAdapter._records` 是无上限普通 `dict`，仅在**同一 key 再次访问**时才懒删除过期项。由于客户端每次提交都生成新 UUID 幂等键，已过期的响应快照永远残留在内存中，直到 OOM。
  - `IdempotencySettings.provider` 默认 `"memory"`，与 `QueueSettings.provider = "redis"` 不一致，多进程部署下分布式幂等完全失效。
- **修复建议**：为 `MemoryIdempotencyAdapter` 加入容量上限（LRU）或定时/写入期惰性清理；在 Docker/生产配置显式开启 `ZHILIAN_IDEMPOTENCY__PROVIDER=redis`。

#### [P1-5] 判题并发无锁且 `grading_records` 缺少「单作答项唯一终态」约束
- **位置**：
  - `backend/app/models/practice.py:658-661`（仅普通 `Index("ix_grading_records_item_final", "attempt_item_id", "is_final")`，非唯一）
  - `backend/app/services/grading.py:199-285`（`grade_practice` 无行锁/CAS）
  - `backend/app/services/practice.py:982-1047`（`submit_practice` 遇不同 `Idempotency-Key` 并发提交时无 CAS 状态保护，会双次更新并双次入队 `grading_jobs`）
- **触发路径**：两台设备/不同幂等键同时交卷，或用户在 Worker 判题期间并发点自评/重判，两事务同时读取 `existing_records` 并各自写入 `is_final=True` 的 `GradingRecord`，破坏「每题有且仅有一条最终判题记录」的不变量，导致后续 `list_final_records_by_practice` 字典覆盖结果不可预测。
- **修复建议**：`submit_practice` 状态切换改为 `try_transition_status` CAS；为 `grading_records` 增加 PostgreSQL 部分唯一索引 `UNIQUE (attempt_item_id) WHERE is_final = true`（迁移同步适配 SQLite）；`grade_practice` / `regrade_attempt` / `self_evaluate_attempt` 写回前按 `attempt_item_id` 锁行或乐观校验。

#### [P1-6] 前端认证生命周期缺失 `refresh_token` 续期、401 并发 `reLaunch` 风暴与登出不清理后台轮询
- **位置**：
  - `miniprogram/src/stores/auth.ts:55-72`
  - `miniprogram/src/utils/request.ts:11-23, 72-79`
  - `miniprogram/src/pages/profile/index.vue:150`
- **事实依据**：
  1. 后端签发 2h `access_token` + 30d `refresh_token` 并提供 `POST /api/v1/auth/refresh`（`api/v1/auth.py:51-70`），但前端 `auth.ts:70` 丢弃 `refresh_token`，每 2 小时强行把正在答题/看讲义的用户踢回登录页。
  2. `request.ts:11-23` 的 `handleUnauthorized()` **无单飞/重入锁**：页面 `onShow` 并发 4–5 个请求同时 401 时，会连续触发 4–5 次 `uni.reLaunch('/pages/auth/login')` 与 Toast 轰炸。
  3. `authStore.clearAuth()` **不调用 `backgroundTaskStore.reset()` 也不清理其他域 store**（全仓 0 处调用 `backgroundTaskStore.reset()`/`stopPolling()`）：用户登出或 401 后，若有活跃解析/出题任务，后台轮询定时器继续每 2.5s 发无 Token 请求 → 持续触发 401 → 反复 `reLaunch` 循环；且切换账号时残留上一用户的 `materialList`/`folders`/`currentSession`。
- **修复建议**：持久化 `refresh_token` 并在 `request.ts` 实现单飞 401 自动续期（失败才走加锁的单次 `handleUnauthorized`）；`clearAuth()` 统一重置 `backgroundTask`/`material`/`folder`/`practice`/`diagnosis` 五个域 store 并停止全部轮询器。

#### [P1-7] `backgroundTaskStore` 轮询缺陷：弹窗污染、404 死轮询、出题任务超时失联
- **位置**：
  - `miniprogram/src/stores/backgroundTask.ts:187-221, 280-282`
  - `miniprogram/src/api/modules/materials.ts:28-33`、`questions.ts:95-100`
  - `miniprogram/src/utils/request.ts:37-42`
- **事实依据**：
  1. `pollOnce()` 调用 `apiGetMaterialDetail` / `apiGetQuestionJob` 时未传 `silentToast: true`（整个前端 0 处使用该参数）。一旦弱网抖动，后台每 2.5s 弹出「网络连接失败」Toast 并调用 `dismissBlockingLoading()`，直接误杀用户当前页面的 loading 框。
  2. 轮询 205 次超时后，`backgroundTask.ts:281` 仅调用 `markActiveMaterialTasksTimedOut()`，**完全遗漏 `questionJobs`**，导致超时后的生题任务永久卡在「生题中...」且无手动刷新按钮。
  3. 当被轮询的 `materialId` 或 `jobId` 返回 HTTP 404（已被删除）时，`catch` 仅 `console.error` 而不从活跃集合移除，继续白白请求 205 次。
- **修复建议**：给后台轮询 API 和草稿队列写入 API 透传 `silentToast: true`；对 404/403 响应立即移除对应追踪项；为 `questionJobs` 补齐超时标记与手动刷新入口。

#### [P1-8] AI 重判用户申诉理由 `reason` 被后端静默丢弃
- **位置**：
  - `backend/app/api/v1/grading.py:128-135`
  - `backend/app/services/grading.py:665-728`
  - `backend/app/services/_grading_llm.py:168-198`
- **事实依据**：前端 `GradingActionModal` 引导用户输入重判申诉原因并通过 `POST /grading/regrade` 传入 `reason`，路由也装进了 `RegradeAttemptDTO(attempt_item_id=..., reason=request.reason)`，但 `resolve_regrade_args()` 只解包 `(user_id, attempt_item_id)`，**`reason` 从未被传给 LLM 阅卷提示词，也未记入 `grading_metadata`**。
- **修复建议**：将 `dto.reason` 作为可选参考信息（附带防 prompt injection 边界提示）传入重判提示词，并记录到 `grading_metadata["regrade_reason"]`。

---

### P2 — 中等缺陷、配置安全与性能短板

| 编号 | 位置 | 现象与影响 | 修复建议 |
|---|---|---|---|
| **P2-1** | `backend/app/services/_diagnosis_report.py:25, 176-185` | 硬编码 `_SUBJECTIVE_TYPES = {"short_answer", "essay", "subjective"}`，与 7 题型权威枚举 `app/core/question_types.py` 漂移：遗漏 `fill_in_blank`/`term_explanation`/`case_analysis`，导致这三类错题全被误归为 `has_objective_mistake`（影响诊断归因准确度）。 | 复用 `app.core.question_types.QuestionType` 统一派生主客观题集合，消除局部硬编码。 |
| **P2-2** | `backend/app/main.py:83-89` + `92-116` | ① `CORSMiddleware` 无条件配置 `allow_origins=["*"]` + `allow_credentials=True`（违反 CORS 安全基线，应由 `AppSettings` 按环境注入白名单）；② 缺少全局 `Exception` 处理器，未捕获 500 返回纯文本且绕过 `CORSMiddleware` 丢 CORS 头。 | 在 `AppSettings` 增加 `cors_allow_origins` 配置；补充统一 500 JSON 异常处理器（脱敏不泄露堆栈）。 |
| **P2-3** | `backend/app/services/auth.py:176-182`、`folder.py:98-105, 178-186` | `login_with_wechat`（首次注册）与 `FolderService.create_folder`/`rename_folder` 均为 `SELECT → INSERT` TOCTOU，未捕获唯一索引 `IntegrityError`，并发双击时返回 500 而非幂等返回/409 冲突。 | 捕获 `IntegrityError` 后 `rollback()`：登录回查既有用户，课程建/改名转译 `FolderNameConflictError(409)`。 |
| **P2-4** | `backend/app/services/auth.py:209,267,298,466`、`practice.py:1096-1097` | 违反项目日志脱敏红线：同时打印 `user_ref`（脱敏哈希）与 `"target_id": str(user.id)`（明文 `user_id`），且 `practice.py:1096` 直接把明文 `user_id` 格式化进 `user_ref=%s`。 | `practice.py:1097` 改为 `generate_user_ref(user_id)`；用户自身审计日志的 `target_id` 改用脱敏标识。 |
| **P2-5** | `backend/app/services/practice.py:1119` | `submit_practice` 异常回滚块直接调用 `self.idempotency.release_lock(...)` 而非已封装的 `_release_lock_quietly(...)`，若 Redis 瞬断会掩盖真实业务异常。 | 改为 `self._release_lock_quietly(clean_key, user_id)`。 |
| **P2-6** | `backend/app/services/_diagnosis_report.py:156-158` | 循环内逐条 `knowledge_repo.get_by_id(point_id, user_id)` 产生 N+1 查询，而 `knowledge_repo.list_by_ids()` 已就绪。 | 改为一次 `list_by_ids(sorted_point_ids, user_id)` 批量预加载。 |
| **P2-7** | `backend/app/integrations/llm/openai.py:131-134` | `self._client is None`（生产默认）时，每次 LLM 请求新建并销毁 `httpx.Client`，无法复用 TCP/TLS Keep-Alive 连接（Embedding/Rerank 适配器同理）。 | 在适配器实例级维护带限流参数的持久化 `httpx.Client` 并在 `close()` 中释放。 |
| **P2-8** | `miniprogram/src/composables/useCoachChat.ts:27-32, 78-94` | 助教聊天历史持久化键 `zhilian:coach:history:${sessionKey}` **缺少 `userId` 隔离**（切换账号串消息），且**无总 key 数/容量 LRU 淘汰**，长期使用会撞穿微信小程序 10MB `wx.setStorage` 上限并连带写失败练习草稿与 token。 | key 前缀纳入 `userId`，并维护有界索引（如最多保留最近 30 个会话，超限按 LRU 淘汰）。 |
| **P2-9** | `miniprogram/src/subpackages/report/composables/useReportDetail.ts:60-63, 82-92, 134` | ① `loadReportIfGraded` 复用了 `gradingPoller`，若判题轮询进行中用户对某题点自评，`gradingPoller.run()` 会 `stop()` 掉外层判题轮询；② `diagnosisStore.loadReport` 会重复请求一次 `GET /practices/{id}`。 | 分离报告加载与判题轮询器；`loadReport` 支持复用已确认 `completed` 的会话直接调 `apiTriggerDiagnosis`。 |
| **P2-10** | `miniprogram/src/stores/practice.ts:46-52, 101, 118, 141` | 若首屏 `fetchProfile()` 尚未完成或失败，`resolveUserId()` 退化为 `'anonymous'`，之后 `user.id` 就绪时交卷清错 key，导致本地草稿孤儿残留或恢复错位。 | 草稿清理时兜底清理 `anonymous` 键，或在登录成功后将 `user_id` 同步落盘（如从 JWT payload 解析 `sub` 兜底）。 |

---

## 3. 结合 `zhilian` 现状的务实软件架构演进方案

项目现有底子**非常扎实**（import-linter 6 契约、Protocol+Fake 适配层、纯算法核、前端 Wire Adapter 与组件行数门禁），**切忌推倒重写**（例如盲目切异步 SQLAlchemy 或拆微服务，只会引入巨大返工风险）。推荐按 **「保基线 + 三阶段务实演进」** 推进：

### Phase 0（立即修复，1–2 天，无架构破坏）
目标：止血 P0 安全/数据正确性与高频稳定性缺陷。
1. **安全止血**：修复 `auth.py` 生产环境 `dev_code`/`mock_` 绕过，启动校验微信凭据 + CORS 环境白名单 + 全局 500 JSON 异常处理器。
2. **数据正确性止血**：
   - 修复 `submit_practice` / `retry_grading` 先 `commit` 再 `enqueue`；
   - 修复 `DiagnosisService` 双写覆盖 `previous_score`（恢复退步知识点识别）及自评/重判后原地刷新 `DiagnosisReport`；
   - 统一 `_diagnosis_report.py` 题型常量；透传重判 `reason`。
3. **前端状态止血**：
   - `draftQueue` 增加 `epoch` 代际隔离与静态 `practiceId` 绑定；
   - `request.ts` 增加 401 单飞锁 + `refresh_token` 自动续期；
   - `authStore.clearAuth()` 联动清理全量域 store 并停止 `backgroundTaskStore` 轮询；
   - 后台轮询与草稿保存启用 `silentToast: true`，补齐 `questionJobs` 超时态与 404 移除。

### Phase 1（核心稳定性与异步解耦，1–2 周 — 与 Issues #1/#2/#3 协同落地）
目标：彻底解决「长耗时阻塞、连接不稳定、后台任务割裂」三大结构性根因。
1. **统一异步任务基础设施（Unified Async Job Architecture）**：
   - 将解析、判题、生题（含 Issue #1 错题异步再生成）收敛到统一的 **「Commit-First + 终态回调」** 模式：
     - 业务代码仅在不可重试业务错误时写 `FAILED`；网络/LLM 瞬时错误交 RQ 退避重试，重试耗尽后由 `handle_job_terminal_failure` 统一落终态；
   - **拆分 Worker 队列隔离队头阻塞**（`deploy/docker-compose.yml`）：
     - `worker-fast`（消费 `zhilian_high`：`grading_jobs`、错题小批生题，秒级响应）；
     - `worker-heavy`（消费 `zhilian`：`parse_material_pipeline`、大批量生题）；
   - **Worker 进程级复用单例 `AppContainer`**，并为所有 Redis/HTTP/S3 适配器补齐 `close()` 与连接池复用（`httpx.Client` 长连接 + `settings.redis.timeout`）。
2. **数据库 Session 与外部 I/O 边界彻底解耦（Short-Transaction Pattern）**：
   - 确立硬约定：**禁止在持有未提交数据库事务期间发起任何 LLM / VLM / OCR / Embedding / S3 网络调用**。
   - 在 `grade_practice`、`regrade_attempt`、`parse_material_pipeline`、`run_generation_job`、`ask_coach` 中改为三段式：
     1. 短事务读取输入快照并 `session.rollback()`/`close()` 归还连接；
     2. 纯内存 + 外部 I/O（LLM/VLM/S3）计算结果；
     3. 新短事务 CAS / 行锁写回并 `commit()`。
   - 为 `grading_records` 增加部分唯一索引 `UNIQUE (attempt_item_id) WHERE is_final = true`，把数据不变量下沉到数据库层。
   - 生产/Docker 默认将 `IdempotencySettings.provider` 切到 `redis`（并对 `memory` 实现加 LRU 上限）。

### Phase 2（中长期架构收敛，按迭代逐步推进）
目标：降低认知负担与跨层漂移成本。
1. **拆解后端 4 个巨型 Service**：按「写命令 / 只读查询 / AI 助教」拆出聚焦子服务（如从 1983 行的 `QuestionService` 拆出 `CoachService` 与 `QuestionJobService`），保持 `app.services` 门面清晰。
2. **简化 LangGraph 装配**：`build_coach_graph` 改为无 `MemorySaver` 的可复用编译图（按 `ProviderRegistry` 单例缓存，彻底消除每次请求的图编译与无效检查点开销）。
3. **前后端契约单一真相源**：基于 FastAPI 自动生成的 `/openapi.json` 引入轻量 TypeScript schema 校验/生成脚本（至少覆盖枚举如 `QuestionType`、`PracticeStatus`、写入类请求体必填字段），把 `title?` / `_SUBJECTIVE_TYPES` 这类静默漂移在 CI 阶段拦住。
4. **前端后台任务与导航状态机收敛**（与 Issue #2 衔接）：将 `backgroundTaskStore` 的轮询生命周期与页面跳转/通知动作解耦，避免 `backgroundTask.ts`（509 行）继续膨胀成跨业务全局中枢；补齐 `.trellis/spec/frontend/state-management.md` 对 `backgroundTask` store 的文档对齐。

---

## 附录：本次审计发现的 `.trellis/spec/` 规范路径（供 `implement.jsonl` / `check.jsonl` 编排参考）

- 后端规范：
  - `.trellis/spec/backend/index.md`
  - `.trellis/spec/backend/directory-structure.md`
  - `.trellis/spec/backend/database-guidelines.md`
  - `.trellis/spec/backend/error-handling.md`
  - `.trellis/spec/backend/logging-guidelines.md`
  - `.trellis/spec/backend/quality-guidelines.md`
  - `.trellis/spec/backend/material-statistics.md`
- 前端规范：
  - `.trellis/spec/frontend/index.md`
  - `.trellis/spec/frontend/network-contract.md`
  - `.trellis/spec/frontend/state-management.md`（存在文档漂移，需后续刷新）
  - `.trellis/spec/frontend/api-payload-contracts.md`
  - `.trellis/spec/frontend/directory-structure.md`
  - `.trellis/spec/frontend/type-safety.md`
  - `.trellis/spec/frontend/component-guidelines.md`
  - `.trellis/spec/frontend/hook-guidelines.md`
  - `.trellis/spec/frontend/quality-guidelines.md`
- 通用思维指南：
  - `.trellis/spec/guides/index.md`
  - `.trellis/spec/guides/cross-layer-thinking-guide.md`
  - `.trellis/spec/guides/code-reuse-thinking-guide.md`
  - `.trellis/spec/guides/git-and-workspace-governance.md`
