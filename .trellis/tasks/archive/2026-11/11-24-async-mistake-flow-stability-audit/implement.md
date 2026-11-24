# Implementation Plan: 错题异步再生、初次生题极简提醒流、连接稳定性加固与高危 Bug 修复

> **推荐 Phase 2 执行编排**：**原生 `Swarm`（4 路并行开发 + 独立交叉校验）**，严格按用户指定模型分配：
> - 复杂后端/架构/网络核心（3 路）→ `gemini-4-neon-high`
> - 前端 UI/提醒流/测试收敛（1 路）→ `gemini-4-hydrogen-high`（或核心交互复杂处用 `gemini-4-neon-high`）
> - 每路工作在独立 `share` workspace，互不踩文件，全部单测与质量门禁通过后按序合并回主工作区。

---

## 1. 无冲突并行分片（File Ownership Map）

### Track B1 — 后端数据层、异步出题自动建卷与判题/诊断核心（Model: `gemini-4-neon-high`, `workspace: "share"`）
负责 R1.1、R1.3、R4.2、R4.3、R4.4、部分 R4.6：
- [ ] 新增 Alembic 迁移 `backend/migrations/versions/0012_async_job_practice_and_grading_unique.py`（`question_generation_jobs` 新增 `result_practice_id`/`source_type`/`source_practice_id`/`idempotency_key`；`grading_records` 部分唯一索引 `WHERE is_final = true`，含脏数据安全清理与 `downgrade`）。
- [ ] 更新 ORM 模型与 Schema：`backend/app/models/{question,practice}.py`、`backend/app/schemas/question.py`、`backend/app/repositories/{question,practice,diagnosis}.py`。
- [ ] 改造 `backend/app/api/v1/questions.py` 与 `backend/app/services/question.py`：
  - `POST /questions/jobs` 支持 `auto_create_practice`/`practice_title`/`source_type`/`source_practice_id`、活跃任务幂等去重、放宽异步单任务 `count <= 50`；
  - `POST /questions/generate` 标记 `deprecated=True`；
  - `run_generation_job` 短事务边界释放连接，完成后原子创建 `Practice` 并写入 `result_practice_id`，区分可重试与不可重试错误（可重试不提前标 `FAILED`）。
- [ ] 改造 `backend/app/services/{practice,grading,diagnosis,_diagnosis_report,_grading_llm}.py`：
  - `submit_practice` 与 `retry_grading` 改为 CAS + **先 `commit()` 再 `enqueue()`**（入队失败补偿回写 `partially_graded`）；修复 `_release_lock_quietly` 与 `user_ref` 脱敏日志；
  - 消除 `sync_practice_learning_state` + `ensure_diagnosis_report` 双写覆盖，恢复 `regressed_knowledge_points`；
  - `DiagnosisService.refresh_diagnosis_report` 在自评/重判改分后原地更新 `DiagnosisReport`；
  - 修复 `_diagnosis_report.py` 主客观题型枚举漂移与 `list_by_ids` N+1；
  - 透传 `regrade` 的 `reason` 给 LLM 与 `grading_metadata`；
  - `grade_practice` / `regrade_attempt` 外部 LLM 调用前释放 DB 事务。
- [ ] 补齐/更新后端单元测试（含迁移一致性测试、Commit-First、退步知识点、自评刷新诊断、异步自动建卷幂等）。

### Track B2 — 后端连接稳定性、安全止血与基础设施加固（Model: `gemini-4-neon-high`, `workspace: "share"`）
负责 R3.1、R3.2、R3.3、R3.6、R4.1、部分 R4.6：
- [ ] 修复 `backend/app/services/auth.py` 生产环境 `dev_code`/`dev_`/`mock_` 后门，并在 `backend/app/main.py` 增补生产微信凭据 fail-fast 校验、环境级 `cors_allow_origins`、全局脱敏 500 JSON 异常处理器。
- [ ] 更新 `backend/app/core/config.py` 与 `backend/.env.example`（`cors_allow_origins`、`postgresql+psycopg://`）。
- [ ] 新增 Redis 连接构造封装并改造 `backend/app/integrations/{queue/rq_adapter,queue/redis,idempotency/redis,idempotency/memory,storage/s3}.py`：
  - 透传 `socket_connect_timeout`/`socket_timeout`/`health_check_interval`/`max_connections` 并实现 `close()`；
  - `S3StorageAdapter` 配置连接/读超时并实现 `close()`；
  - `MemoryIdempotencyAdapter` 增加 LRU 上限与惰性清理。
- [ ] 改造 `backend/app/integrations/llm/{protocol,openai}.py`、`backend/app/integrations/embedding/`、`backend/app/integrations/rerank/`、`backend/app/workflows/agent_graph.py`：
  - `LLMOptions.timeout` 默认 `None`，消除 30s 静默覆盖；
  - 适配器实例级复用持久化 `httpx.Client` 并实现 `close()`；重试退避加入 jitter。
- [ ] 改造 `backend/app/container.py`、`backend/app/worker.py`、`backend/app/integrations/search/pgvector.py`、`backend/app/services/material.py`（S3/LLM 短事务与可重试异常不提前标 `FAILED`）：
  - SQLite `connect` 事件开启 `WAL` + `busy_timeout=15000` + `synchronous=NORMAL` + `foreign_keys=ON`；
  - PG engine 增补 `pool_recycle=1800` 与 keepalives；
  - `check_health()` 增加 Redis 短超时探活；
  - `worker.py` 改为进程级单例 `AppContainer` 复用；
  - 消除 `pgvector` 嵌套借连接死锁风险。
- [ ] 补齐/更新后端单元测试（auth 生产拒绝 dev_code、Redis/LLM 超时与关闭、SQLite WAL、MemoryIdempotency LRU、全局 500 JSON、health Redis 探活）。

### Track F1 — 前端网络层、Auth 续期、轮询与草稿队列韧性（Model: `gemini-4-neon-high`, `workspace: "share"`）
负责 R3.4、R3.5、R4.5、R4.6：
- [ ] 改造 `miniprogram/src/utils/request.ts` & `miniprogram/src/manifest.json`：
  - 默认地址 `127.0.0.1`、`manifest.json` `networkTimeout`、`uploadFile` 真实超时分类；
  - `silentToast: true` 禁止弹 Toast 且禁止 `dismissBlockingLoading()`；
  - 并发调度队列（`maxConcurrent=6`）+ in-flight GET 去重 + 幂等 GET 有限次退避重试（含 jitter）；
  - 401 单飞静默刷新 `refresh_token` + 防重锁单次 `handleUnauthorized()`。
- [ ] 改造 `miniprogram/src/stores/auth.ts` & `miniprogram/src/App.vue`：
  - 持久化 `refresh_token`；`clearAuth()` 重置所有域 store 并停止 `backgroundTaskStore` 轮询；
  - `App.vue` `onHide` 停轮询、`onShow` 按需恢复。
- [ ] 改造 `miniprogram/src/utils/poller.ts` & `miniprogram/src/utils/draftQueue.ts` & `miniprogram/src/stores/practice.ts` & `miniprogram/src/subpackages/practice/pages/session/index.vue`：
  - `poller.ts` 容忍连续瞬时失败（默认 3 次）不中断；
  - `draftQueue.ts` 增加 `epoch` 代际隔离、静态绑定 `practiceId`、并发限制 `<= 2`、`silentToast: true`；
  - `session/index.vue` 文本输入 500ms 防抖并在切题/交卷前即时 flush。
- [ ] 改造 `miniprogram/src/composables/useCoachChat.ts`（`userId` 隔离 + 30 会话 LRU）与 `miniprogram/src/pages/index/index.vue`（消除首次 `onMounted`+`onShow` 双重并发拉取）。
- [ ] 补齐前端单元测试（`request.spec.ts` / `draftQueue.spec.ts` / `poller.spec.ts` / `auth` 清理与 401 单飞）。

### Track F2 — 前端错题异步化、初次生题极简提醒流与后台任务条统一（Model: `gemini-4-hydrogen-high`, `workspace: "share"`）
负责 R1.1、R1.2、R2.1、R2.2、R2.3、部分 R3.4：
- [ ] 扩展前端类型与 API 适配器：`miniprogram/src/types/question.ts`、`miniprogram/src/api/modules/questions.ts`、`miniprogram/src/api/adapters/`（对接 `auto_create_practice`/`result_practice_id`/`source_type`/`source_practice_id` 与 `silentToast` 透传）。
- [ ] 改造 `miniprogram/src/stores/backgroundTask.ts` 与 `miniprogram/src/components/BackgroundTaskBar.vue`：
  - 所有轮询请求透传 `silentToast: true`，并发限制 `<= 2`，404/403 立即移除，补齐 `questionJobs` 超时态与刷新；
  - 支持 `excludeJobId` prop 消除 `questions/index.vue` 双进度条；
  - 识别 `resultPracticeId` 与 `sourceType`，完成态仅展示非打断式提醒（「试卷已就绪 · 立即作答」/「错题巩固卷已就绪 · 立即作答」），点击直达 `/subpackages/practice/pages/session/index?practice_id=...`。
- [ ] 改造 4 个错题再生入口并废弃同步调用：`miniprogram/src/subpackages/report/pages/detail/index.vue`（挂载 `<BackgroundTaskBar auto-refresh />`）、`useReportDetail.ts`、`pages/review/composables/useReviewCenter.ts`、`utils/questionGeneration.ts`（清零 `apiGenerateQuestions` 调用，移除 `withBlockingLoading('生成中...')`）。
- [ ] 重构初次生题页 `miniprogram/src/subpackages/material/pages/questions/index.vue`、`useQuestionCompose.ts`、`subpackages/material/components/`、`subpackages/material/pages/course/index.vue`：
  - 显式三态：`config` → `generating`（单一进度卡，隐藏表单与重复顶栏）→ `ready`（极简「试卷已就绪」提醒卡：主按钮「立即开始作答」直达练习，次按钮「去我的题库查看」/「重新组卷」，**绝不自动强跳、绝不铺开带答案/切片的杂乱题库、不因部分待审锁死**）；
  - 修复 `view=generated` 闪屏、`attachActiveJobForScope()` 衔接近期已完成任务、清理讲义页无 `batch_id` 历史混杂入口；
  - 确保所有触碰的 `.vue` 文件继续满足 `<= 300` 行、零裸 Hex、零 Emoji 门禁。
- [ ] 更新并补齐前端测试（`studyAndComposeFlow.spec.ts`、`backgroundTask.spec.ts`、错题异步流与无强跳提醒测试）。

> **合并协调点**：
> - 后端合并顺序：`B1` → `B2`（仅 `backend/app/services/practice.py` 与 `backend/app/services/question.py` 若有交叉由 B1 主导，B2 聚焦 `auth`/`main`/`container`/`worker`/`integrations`/`material` 避免冲突）。
> - 前端合并顺序：`F1` → `F2`（`F1` 聚焦 `utils/`/`stores/auth`/`stores/practice`/`App.vue`/`session/index`/`pages/index`；`F2` 聚焦 `stores/backgroundTask`/`BackgroundTaskBar`/`questions/index`/`useQuestionCompose`/`report/detail`/`useReviewCenter`/`course/index`；`stores/auth.ts` 调用 `backgroundTaskStore.reset()` 接口名已既有，零冲突！）。

---

## 2. 合并后验证与质量门禁

在宿主 Windows PowerShell 直接运行（严禁走 WSL）：
```powershell
task verify-backend
task verify-frontend
```
> 若全量 `pytest` 中 `tests/unit/core/algorithms/` 墙钟阈值偶发抖动，按 `AGENTS.md` 规范单独复跑该目录确认 100% 通过。

合并且门禁全绿后，派发独立只读评审员（或 `trellis-check`）针对完整 `git diff` 复核跨层契约、多租户安全、短事务边界与 300 行组件红线，并通过 `trellis-update-spec` 将新确立的架构契约沉淀回 `.trellis/spec/`。
