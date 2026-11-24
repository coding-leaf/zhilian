# Technical Design: 错题异步再生、初次生题极简提醒流、连接稳定性加固与高危 Bug 修复

> **对应 PRD**：`prd.md`
> **调研证据**：`research/01-async-mistake-generation.md` ~ `04-architecture-and-bugs-audit.md`

---

## 1. 架构与边界约束

1. **严格维持既有分层防线**（`backend/pyproject.toml` 6 条 `import-linter` 契约全绿）：
   - `app.api -> app.services -> app.repositories -> app.models`，禁止跨层反向依赖；
   - 所有新增数据访问逻辑落在 `repositories/` 并强制携带 `user_id` 多租户过滤；
   - 外部基础设施（Redis / HTTP / S3）全部封装在 `app/integrations/` 适配器内并遵循 `Protocol` + `Fake` 契约。
2. **前端工程红线**：
   - 所有 `.vue` SFC 单文件严格控制在 `<= 300` 行（目标 `<= 270` 行），零裸 Hex、零 Emoji、底栏适配 `env(safe-area-inset-bottom)`；
   - 不新增任何第三方 UI 库；复用现有 `useBackgroundTaskStore`、`BackgroundTaskBar.vue`、`src/api/adapters/` 归一化边界。

---

## 2. 跨层契约与数据模型设计

### 2.1 数据库迁移 `0012_async_job_practice_and_grading_unique.py`

1. **`question_generation_jobs` 表新增可空列**：
   - `result_practice_id: UUID | None`（可空外键指向 `practices.id`，`ondelete="SET NULL"`，索引）——记录自动建卷产出的 `Practice.id`；
   - `source_type: String(32) | None`（如 `"initial_compose"` / `"wrong_record"` / `"weakness"`）——持久化任务来源意图，小程序重启后仍可准确渲染提醒文案；
   - `source_practice_id: UUID | None`（可空，索引）——错题再生成溯源原练习 ID，配合活跃状态实现幂等去重；
   - `idempotency_key: String(128) | None`（可空，索引）——支持显式幂等键复用进行中或刚完成的同源任务。
2. **`grading_records` 部分唯一索引**：
   - 新增唯一索引 `uq_grading_records_item_final`：`UNIQUE (attempt_item_id) WHERE is_final = true`（PostgreSQL 使用 `postgresql_where=text("is_final IS TRUE")`，SQLite 使用 `sqlite_where=text("is_final = 1")`，确保本地测试与生产一致）。
   - 同步更新 `backend/app/models/question.py` 与 `backend/app/models/practice.py` 以通过迁移一致性测试门禁。

### 2.2 异步出题契约扩展（向后兼容）

- **请求 `QuestionGenerateRequest`**（`backend/app/schemas/question.py`）：
  - 保留既有必填/可选字段，新增可选字段（均带默认值）：
    - `auto_create_practice: bool = False`
    - `practice_title: str | None = None`
    - `source_type: Literal["initial_compose", "wrong_record", "weakness"] | None = None`
    - `source_practice_id: uuid.UUID | None = None`
  - 同步端点 `POST /questions/generate` 标记 `deprecated=True` 并维持 `count <= 20`；异步端点 `POST /questions/jobs` 允许 `count <= MAX_PRACTICE_QUESTIONS`（50），Worker 内部按 KP 3 并发分批生成，彻底消除前端多批串行中断问题。
- **响应 `QuestionGenerationJobResponse`**（`backend/app/schemas/question.py` + `miniprogram/src/types/question.ts` + `src/api/adapters/`）：
  - 新增返回字段：`result_practice_id: str | None`、`source_type: str | None`、`source_practice_id: str | None`、`practice_title: str | None`（从 `request_payload` 安全提取）。
- **活跃任务幂等去重（`QuestionService.create_generation_job`）**：
  - 支持读取请求头 `Idempotency-Key` 或基于 `(user_id, source_type, source_practice_id, material_id, folder_id, sorted(knowledge_point_ids))` 检查 `status in ("queued", "running")` 的活跃任务；命中时直接复用并返回现有 Job（`202`），防止用户双击触发双倍 LLM 消耗。
- **Worker 原子收尾（`QuestionService.run_generation_job`）**：
  - 题目生成并落库后，若 `request_payload.get("auto_create_practice")` 为真：
    - 筛选本批 `status == "available"` 的 `question_ids`（按 `MAX_PRACTICE_QUESTIONS` 截断）；
    - 当 `len(available_ids) > 0` 时，在短事务内调用 `PracticeService.create_practice(...)`（不传冲突的 `question_count`，严格遵循 `.trellis/spec/frontend/api-payload-contracts.md` 语义），将 `practice.id` 写入 `job.result_practice_id`，一并置 `job.status = COMPLETED` 并 `commit()`；
    - 当 `len(available_ids) == 0` 时，`result_practice_id = None`，`job.status = COMPLETED` 并在摘要/error_message 标注无可用题（前端引导调整配置重试）。
  - **Commit-First 与重试语义对齐**：
    - `create_generation_job` 先 `commit()` 再 `enqueue()`；
    - `run_generation_job` 与 `parse_material_pipeline` 区分**不可重试业务错误**（直接标 `FAILED`）与**可重试基础设施错误**（网络/超时/5xx/429：回滚后 `raise` 交由 RQ 重试，最终耗尽由 `worker.py::handle_job_terminal_failure` 在 `not job.should_retry` 时统一落盘 `FAILED`）。

---

## 3. 后端稳定性与 P0 Bug 修复设计

### 3.1 判题、提交与诊断单次流水线（修复 R1.3、R4.2、R4.3、R4.4）

1. **Commit-First + CAS（`services/practice.py`）**：
   - `submit_practice` 将状态转换 `in_progress -> submitted` 改为仓储层 CAS 更新（`try_transition_status`），防止并发不同 `Idempotency-Key` 双重提交；
   - `submit_practice`（含主观题路径）与 `retry_grading` 全部改为：**先 `self.session.commit()` 持久化 `SUBMITTED` 状态，再调用 `self.queue.enqueue("grading_jobs", ...)`**；若入队抛出基础设施异常，开启补偿短事务将状态回写为 `PARTIALLY_GRADED`（可由前端「重试判题」恢复）并抛出错误。
   - `submit_practice` 异常回滚块将 `self.idempotency.release_lock` 统一改为 `self._release_lock_quietly`。
   - `practice.py:1097` 审计日志改用 `generate_user_ref(user_id)`。
2. **消除双写覆盖 `previous_score` + 支持原地刷新诊断（`services/diagnosis.py` & `services/grading.py`）**：
   - 练习首次达成 `COMPLETED` 时（纯客观题 `submit_practice` 与 Worker `grade_practice` 收尾）：**不再先调 `sync_practice_learning_state` 覆盖 `MasteryRecord` 再调 `ensure_diagnosis_report`**；统一只调一次 `generate_diagnosis_report`（内部按严格顺序：① 读取练习前 `previous_records` 基线 → ② 计算并写入最新 `MasteryRecord` 与 `WrongRecord` → ③ 计算 `score_delta` 准确识别 `regressed_knowledge_points` → ④ 写入 `DiagnosisReport`）。
   - 仅当练习未完全判完（`submitted`/`partially_graded`）时调用 `sync_practice_learning_state(partial_ok=True)`。
   - 新增 `DiagnosisService.refresh_diagnosis_report(user_id, practice_id)`（或在 `generate_diagnosis_report` 支持 `force_refresh=True`）：当 `self_evaluate_attempt` 或 `regrade_attempt` 修改了最终得分后，原地更新既有 `DiagnosisReport` 的 `total_score`/`score_rate`/`wrong_count`/`weak_knowledge_points`/`summary` 等字段，彻底消除结果页指标自相矛盾。
   - 修复 `_diagnosis_report.py:25`：从 `app.core.question_types.QuestionType` 统一派生主观题集合，不再硬编码缺失 `fill_in_blank`/`term_explanation`/`case_analysis`；批量 `list_by_ids` 替换 `_diagnosis_report.py:156` 的 N+1 查询。
   - 修复 `grading.py:665`：将 `RegradeAttemptDTO.reason` 经防注入包裹块传入 `_grading_llm.py` 重判提示词，并记入 `grading_metadata["regrade_reason"]`。

### 3.2 生产登录安全与全局异常（修复 R4.1、R3.6）

1. `backend/app/services/auth.py`：
   - `_resolve_wechat_openid` 仅当 `settings.env != "production"` 时允许 `dev_code`/`dev_`/`mock_` 与无凭据回退；生产环境下缺少 `wechat_app_id`/`wechat_app_secret` 时直接报错，并在 `main.py` 启动 lifespan 增加生产微信凭据 fail-fast 校验。
2. `backend/app/main.py` & `core/config.py`：
   - `AppSettings` 新增 `cors_allow_origins: list[str]`（开发默认 `["*"]` 且仅在非通配符时开 `allow_credentials=True`，生产显式配置白名单）；
   - 注册全局 `@app.exception_handler(Exception)`，记录结构化脱敏异常日志并返回统一 JSON 500（`{"code": 50000, "message": "服务暂时繁忙，请稍后重试", "details": {}}`）；
   - `container.py::check_health()` 在启用 Redis 队列/幂等时增加短超时 `redis.ping()` 探活。
3. 修复 `backend/.env.example` 数据库示例驱动为 `postgresql+psycopg://`。

### 3.3 后端连接稳定性（修复 R3.1、R3.2、R3.3、R4.6）

1. **Redis 与 S3 超时/释放 + Worker 容器复用**：
   - 新增统一辅助函数（如 `integrations/redis_client.py`）依据 `RedisSettings` 构建连接池：`socket_connect_timeout=settings.timeout`、`socket_timeout=settings.timeout`、`health_check_interval=30`、`max_connections=settings.max_connections`、`retry_on_timeout=True`；
   - `RQQueueAdapter`、`RedisIdempotencyAdapter`、`RedisQueueAdapter` 与 `worker.py` 全部复用该构造器并实现 `close()`（关闭 `connection_pool.disconnect()`）；
   - `S3StorageAdapter` 配置 `Config(signature_version="s3v4", connect_timeout=10, read_timeout=30, max_pool_connections=20)` 并实现 `close()`；
   - `worker.py` 改为进程级懒初始化单例 `AppContainer`（注册 `atexit`/信号钩子统一 `shutdown()`），消除每任务重建引擎与泄漏连接池问题；
   - `MemoryIdempotencyAdapter` 引入有界 LRU 容量上限（默认 `max_entries=10000`）与写入期惰性淘汰过期键。
2. **LLM/Embedding/Rerank 超时修复与 `httpx.Client` 复用**：
   - `LLMOptions.timeout: float | None = None`（`integrations/llm/protocol.py`）；`openai.py`、`agent_graph.py` 仅当 `options.timeout is not None` 时才覆盖客户端默认 `settings.llm.timeout`；`_grading_llm.py` 移除硬编码 `20.0` 改为遵循配置（上限可设为合理值如 `min(settings.llm.timeout, 60.0)` 或使用配置）；
   - `OpenAILLMAdapter`（及同目录 Embedding/Rerank 适配器）在实例级持有一个持久化 `httpx.Client`（配置 `httpx.Limits(max_connections=30, max_keepalive_connections=15)` 与显式 `Timeout`）并实现 `close()`，由 `AppContainer.shutdown()` 统一关闭；
   - 重试退避加入 `random.uniform(0.5, 1.5)` jitter，防止并发请求惊群重试。
3. **DB 短事务边界 + `pgvector` 修复 + SQLite WAL / PG `pool_recycle`**：
   - `container.py`：
     - SQLite：注册 `event.listen(engine, "connect", ...)` 设置 `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=15000; PRAGMA foreign_keys=ON;`，`connect_args={"check_same_thread": False, "timeout": 15.0}`；
     - PostgreSQL：增补 `pool_recycle=1800`、`pool_pre_ping=True` 及 `connect_args` TCP keepalives（兼容 psycopg）。
   - 短事务解耦：在 `grade_practice`、`regrade_attempt`、`parse_material_pipeline`（LLM 与 S3 上传段）、`run_generation_job`（并发 LLM 段）、`ask_coach`/`ask_scoped_coach` 中，将只读数据提取为纯内存 DTO/快照后立即 `session.rollback()`/`close()` 释放连接，执行完外部 I/O 后再开启短事务写回与 `commit()`；
   - `PgvectorHybridSearchAdapter`：允许复用调用方已释放连接或在独立无嵌套事务上下文执行检索，避免在请求事务已占连接时从同一池二次 checkout 引发连接池死锁。

---

## 4. 前端 UX 状态机与网络韧性设计

### 4.1 统一「只提醒、不强制跳转」的生题体验（R1.1、R1.2、R2.1–R2.3）

1. **后端自动建卷 + 前端统一提醒模型**：
   - `useBackgroundTaskStore` 的 `BackgroundTaskItem` 新增 `resultPracticeId?: string | null`、`sourceType?: 'initial_compose' | 'wrong_record' | 'weakness' | null`、`practiceTitle?: string | null`。
   - **初次生题（`questions/index.vue` + `useQuestionCompose.ts`）**：
     - 提交生题调用 `backgroundTaskStore.startQuestionJob({ ..., auto_create_practice: true, source_type: 'initial_compose' })`；
     - 页面采用显式状态机：`mode = 'config' | 'generating' | 'ready'`：
       - `config`：展示 `<QuestionConfigPanel>`；
       - `generating`：隐藏配置表单，仅展示单一干净的页内进度卡（文案「正在后台出题（X/Y 考点）· 可随时离开继续浏览，完成后顶部提醒」），并向 `<BackgroundTaskBar :exclude-job-id="activeJobId" />` 传参，彻底消除双进度条；
       - `ready`：生题完成后**绝不强制跳转**，也不渲染杂乱的 `QuestionPreviewPanel` 题库清单，改为展示极简「试卷已就绪」卡片（例如：`已为你生成 N 道题 · 覆盖 M 个考点`，若有部分待审仅一行柔和次要提示，**不锁死作答**；主按钮「立即开始作答」直达 `/subpackages/practice/pages/session/index?practice_id=...`，次按钮「去我的题库查看」跳学情页题库 Tab / 「重新组卷」切回 `config`）；
       - 若 `availableCount === 0`（全部未过质检），展示柔和空态提示并引导调整配置重试。
     - 修复 `view=generated` 闪屏：`onLoad` 同步判定 query 参数设置初始 `mode`，不先渲染 `config`；`attachActiveJobForScope()` 同时衔接本范围刚刚完成的任务；讲义页「查看/核对题目」统一引导至学情题库或明确限定可用批次。
   - **错题异步再生（4 个入口）**：
     - `useReportDetail.ts::startAdaptivePractice` 与 `useReviewCenter.ts::runRegenerate` 移除 `withBlockingLoading('生成中...')` 与 `utils/questionGeneration.ts` 同步批量调用，改调 `backgroundTaskStore.startQuestionJob({ ..., auto_create_practice: true, source_type: 'wrong_record', practice_title: '错题巩固练习', source_practice_id })`；
     - `report/pages/detail/index.vue` 挂载 `<BackgroundTaskBar auto-refresh />`；
     - 发起后仅轻 Toast「已在后台生成错题巩固卷，完成后顶部提醒」，按钮显示「后台生题中」防连点；完成后**不强制跳转**，仅通过 `<BackgroundTaskBar />` 提醒「错题巩固卷已就绪 · 立即作答」，用户点击直达 `session/index?practice_id=...`。

### 4.2 前端网络层、轮询与草稿队列韧性（R3.4、R3.5、R4.5、R4.6）

1. **`miniprogram/src/utils/request.ts`**：
   - 默认 `API_BASE_URL` 改为 `http://127.0.0.1:8000/api/v1`；`uploadFile` 错误分类传入真实上传超时值（120000ms）；`manifest.json` `mp-weixin` 配置 `networkTimeout: { request: 90000, uploadFile: 120000 }`。
   - **`silentToast` 修复**：当 `options.silentToast === true` 时，失败时**既不弹 Toast，也不调用 `dismissBlockingLoading()`**。
   - **并发调度器 + GET 去重 + 幂等 GET 重试**：
     - 维护最大并发数 `MAX_CONCURRENT_REQUESTS = 6` 的 FIFO 调度队列（高优/写请求不饿死，留余量给上传与登录）；
     - 相同 `GET` URL+query 在途时复用同一个 Promise（`inFlightGetMap`），避免首页 `onMounted`/`onShow` 瞬间发出 4 个相同 `GET /materials`；
     - 对 `GET` 遇到 `network` / `timeout` / HTTP `502,503,504` 进行最多 2 次指数退避重试（含 jitter）。
   - **401 单飞刷新 `refresh_token` + 防重 `handleUnauthorized`**：
     - `stores/auth.ts` 持久化 `refresh_token`；
     - `request.ts` 收到 401 时若存在 `refresh_token` 且非刷新端点本身，进入单飞 `refreshPromise` 调 `POST /auth/refresh`，并发 401 请求挂起等待新 token 后自动重放一次；
     - 仅当刷新失败或无 `refresh_token` 时执行带防重锁（`isRedirectingToLogin`）的单次 `authStore.clearAuth()` + `uni.reLaunch('/pages/auth/login')`。
2. **生命周期与 Store 清理**：
   - `authStore.clearAuth()` 统一调用 `backgroundTaskStore.reset()` 以及清理 `material`/`folder`/`practice`/`diagnosis` 状态，终结登出后 401 死循环与跨账号串数据；
   - `App.vue` `onHide` 调用 `backgroundTaskStore.stopPolling()`，`onShow` 在已登录且存在活跃任务时恢复轮询；
   - `pages/index/index.vue` 消除首次进入 `onMounted` + `onShow` 双重拉取。
3. **轮询器容错与 `backgroundTaskStore` 修复**：
   - `miniprogram/src/utils/poller.ts`：为每次 tick 增加 `try/catch` 与连续错误容忍阈值（默认 `maxConsecutiveErrors = 3`），单次瞬时断网记录日志并继续按退避间隔重试，避免判题轮询永久卡死；
   - `backgroundTaskStore.ts`：所有轮询请求传 `silentToast: true`；单批轮询限制并发 `<= 2`；遇到 HTTP 404/403 立即移除对应追踪任务；超时处理同步覆盖 `materialTasks` 与 `questionJobs`（提供「刷新进度」续查）。
4. **草稿队列代际隔离与输入防抖（R4.5、R3.5）**：
   - `miniprogram/src/utils/draftQueue.ts`：引入自增 `epoch`（`reset()` 时 `epoch += 1`），`run()` 与 `finally` 每次恢复前校验 `myEpoch === epoch`，不匹配直接静默返回；载荷静态绑定 `{ practiceId, questionId, answer }`；增加全局并发上限 `maxConcurrent = 2` 且 `retryAll()` 串行/限流执行；写草稿请求透传 `silentToast: true`。
   - `miniprogram/src/subpackages/practice/pages/session/index.vue`：主观题/填空题输入立即更新内存草稿，对 storage 写入与 `draftQueue.enqueue` 做 `500ms` 防抖（切题或点交卷前立刻 flush 防抖定时器）。
5. **助教聊天本地存储隔离（R4.6）**：
   - `miniprogram/src/composables/useCoachChat.ts`：存储 key 加入 `userId` 前缀并维护最多 30 个会话的 LRU 索引，防止切账号串消息与撑爆微信 10MB 存储上限。

---

## 5. 风险与回滚考量

- **Alembic 迁移 0012**：全部新增列均为 `nullable=True`，零破坏旧数据；`grading_records` 部分唯一索引在迁移前先检查/清理历史同 `attempt_item_id` 多条 `is_final=true` 脏数据（保留最新一条），确保线上迁移可安全升级与降级。
- **前端 `request.ts` 401 单飞刷新与并发队列**：需用完备单元测试覆盖「多并发 401 仅刷新 1 次并全量重放」「刷新失败仅 `reLaunch` 1 次」「`silentToast` 不误杀 loading」「超过 6 并发排队不丢请求」。
- **前端测试断言更新**：`miniprogram/tests/studyAndComposeFlow.spec.ts` 中对旧版 `QuestionPreviewPanel` 自动切换及同步 `apiGenerateQuestions` 的旧断言需同步更新为极简就绪卡与异步任务流断言。
