# PRD: 错题异步再生、初次生题极简提醒流、连接稳定性加固与高危 Bug 修复

> **任务目录**：`.trellis/tasks/11-24-async-mistake-flow-stability-audit`
> **优先级**：P1
> **范围模式**：核心闭环一次到位（问题 1 + 问题 2 + 问题 3 P0/P1 + 问题 4 全部 5 个 P0 硬 Bug；中长期巨型 Service 拆分、fast/heavy 双队列分离与 OpenAPI 自动代码生成留作二期）

---

## 1. 目标与用户价值

消除远程试用中暴露的 4 类核心痛点，使「资料 → 生题 → 答题 → 交卷/判题 → 诊断 → 错题再练」全链路无长耗时阻塞、无杂乱题库强制跳转、无高频网络断连与弹窗污染，并根治已实证的安全、竞态与数据一致性 P0 缺陷。

---

## 2. 关键决策（已与用户确认）

- **D1 范围边界**：本轮覆盖问题 1（错题异步化 + 去除交卷双倍同步计算）、问题 2（初次生题去杂乱题库 + 去双进度条/闪屏/历史混杂）、问题 3（前后端 P0/P1 连接稳定性加固）、问题 4 中 5 个 P0 硬 Bug 及紧密耦合的 P1 稳定性项（如 `MemoryIdempotencyAdapter` 上限、RQ 重试前误标 `FAILED`、Worker 容器连接池泄漏、`clearAuth` 清理轮询与域 store、`regrade` 申诉理由透传等）。
- **D2 生题完成交互（初次生题 & 错题再生统一规则）**：**只提醒，绝不强制跳转**。
  - 无论初次生题还是错题异步再生，后台任务完成后**均不强制 `redirectTo` / `navigateTo`** 抢夺用户当前页面焦点；
  - 若用户在出题页原地等待完成，仅展示极简「试卷已就绪」提醒卡（题数 + 考点覆盖 + 一键「立即开始作答」直达练习页 + 次要「前往题库查看」入口），**绝不铺开带答案/解析/讲义切片的杂乱题库列表**；
  - 若用户在其他页面（工作台、讲义、报告页、学情页），由 `<BackgroundTaskBar />` 展示非打断式就绪提醒，点击「立即作答」直达 `/subpackages/practice/pages/session/index?practice_id=...`。
- **D3 兼容策略**：旧同步接口 `POST /questions/generate` 标记 Deprecated 保留向后兼容，前端清零对其调用。

---

## 3. 详细需求与已实证缺陷映射

### R1：答题后错题再生题全异步化 + 消除交卷/判题双倍同步计算

| ID | 级别 | 现状与精确代码锚点 | 目标行为 |
|---|---|---|---|
| **R1.1** | P0 | 4 个错题再生入口（`AdaptivePracticeCard.vue:7-13`、`report/pages/detail/index.vue:51-58` → `useReportDetail.ts:142-165`、`WrongBookSection.vue:56`、`review/index.vue:86` → `useReviewCenter.ts:304-335,396`）全部锁屏 `withBlockingLoading('生成中...')` 并经 `utils/questionGeneration.ts:31-101` 串行调同步 `POST /questions/generate`（90s 阻塞）。 | 全部迁至异步 `POST /questions/jobs`（`202 Accepted` 立即返回），携带 `auto_create_practice=true`、`practice_title`、`source_type`、`source_practice_id`；后端 `QuestionGenerationJob` 新增 `result_practice_id` 与活跃任务幂等去重；Worker 出题完成后原子创建 `Practice` 并写入 `result_practice_id`。前端移除全屏阻塞遮罩，仅轻提示并在 `<BackgroundTaskBar />` 持续追踪。 |
| **R1.2** | P0 | `report/pages/detail/index.vue` 未挂载 `<BackgroundTaskBar />`；`BackgroundTaskBar.vue:56-72` 点击已完成 `question_job` 硬编码跳 `questions/index?view=generated`。 | `report/pages/detail/index.vue` 挂载 `<BackgroundTaskBar auto-refresh />`；`BackgroundTaskBar` 识别 `result_practice_id`，完成态展示「试卷已就绪 · 立即作答」（错题任务显示「错题巩固卷已就绪」），点击直达 `/subpackages/practice/pages/session/index?practice_id=...`，**绝不自动强跳，也不绕道题库页**。 |
| **R1.3** | P1 | 纯客观题交卷 `services/practice.py:1159-1173` + `:1056-1062` 及 Worker 判题收尾 `services/grading.py:325-346` 连续调用 `sync_practice_learning_state` 和 `ensure_diagnosis_report`，造成掌握度与错题同步被完整计算 **2 遍**，且直接引发 P0-3（退步知识点恒为空）。 | 练习达成 `COMPLETED` 时，合并为单次流水线（先读练习前 `previous_records` 基线 → 更新掌握度与错题 → 生成诊断报告），消除双倍计算；仅未全判完（`submitted`/`partially_graded`）时调用 `sync_practice_learning_state(partial_ok=True)`。 |

### R2：初次生题极简提醒流（消除杂乱题库与双进度条/闪屏）

| ID | 级别 | 现状与精确代码锚点 | 目标行为 |
|---|---|---|---|
| **R2.1** | P0 | `questions/index.vue:115-131, 233-239` 在生题完成后切到 `QuestionPreviewPanel`（3 层 Banner 叠放 + 每题卡片暴露参考答案/解析/讲义切片/剔除/重生成），且 `useQuestionCompose.ts:109-111` 在存在任意缺口时锁死「开始作答」。 | 初次生题调用 `POST /questions/jobs` 同样传 `auto_create_practice=true`；完成后**不强制跳转**，也不展示杂乱逐题预览列表，改为展示极简「试卷已就绪」提醒卡（题数、覆盖考点数、可选非阻塞缺口提示行、主按钮「立即开始作答」直达 `session/index?practice_id=...`、次按钮「去题库查看」跳学情题库/「重新组卷」）。只要 `available.length > 0` 即允许开练（不再因部分考点待审锁死）。 |
| **R2.2** | P1 | `questions/index.vue:3` `<BackgroundTaskBar />` 与 `:14-31` `.job-progress-banner` 双进度条叠放，且 `:33` `<QuestionConfigPanel>` 在出题中仍占满屏。 | `questions/index.vue` 生题进行中收起配置表单，只展示单一清晰的页内进度卡片（同时对当前页面正在展示的 `activeJobId` 隐藏全局 `<BackgroundTaskBar />` 重复项，避免双进度条）；用户可随时返回继续看讲义，切走后由顶栏 `<BackgroundTaskBar />` 接管进度与就绪提醒。 |
| **R2.3** | P1 | `questions/index.vue:111,133-152` 处理 `view=generated` 先以 `isConfigMode=true` 闪现配置页；`course/index.vue:182-188`「继续核对已生成题目」未传 `batch_id` 且不过滤 `pending_review`，混入全量历史题；离开页期间任务完成后回访 `questions/index.vue:154-156` 无法衔接。 | 修复 `onLoad` 初始态防闪屏；`attachActiveJobForScope()` 同时识别近期已完成的本范围任务（展示就绪提醒卡）；讲义页「查看历史题目/核对」统一引导至「学情 - 我的题库」或显式限定可用题/批次，消除两套杂乱题库视图割裂。 |

### R3：前后端连接稳定性全量加固（P0 + P1）

| ID | 级别 | 现状与精确代码锚点 | 目标行为 |
|---|---|---|---|
| **R3.1** | P0 | **Redis 零超时与连接池泄漏**：`rq_adapter.py:36`、`idempotency/redis.py:66`、`queue/redis.py:81`、`worker.py:98` 调用 `Redis.from_url()` 忽略 `RedisSettings.timeout`/`max_connections` 且缺 `close()`；`worker.py:86-90` 每任务重建 `AppContainer`。 | 全量 Redis 适配器透传 `socket_connect_timeout`、`socket_timeout`、`health_check_interval=30`、`max_connections` 并实现 `close()`；`S3StorageAdapter` 显式设超时并实现 `close()`；Worker 进程级复用单例 `AppContainer`（退出时统一 `shutdown`）。 |
| **R3.2** | P0 | **LLM 超时静默覆盖与连接零复用**：`LLMOptions.timeout=30.0` (`protocol.py:60`) + `openai.py:185` + `agent_graph.py:101` 覆盖 `ZHILIAN_LLM__TIMEOUT`（`_grading_llm.py:85` 硬编码 20s）；重试无 jitter；LLM/Embedding/Rerank 每次调用新建销毁 `httpx.Client`。 | `LLMOptions.timeout` 默认改为 `None`（未显式指定时走 `settings.llm.timeout`），消除硬编码 20s/30s 覆盖；适配器实例级复用持久化 `httpx.Client`（带连接池上限与 `close()`）；重试退避增加随机 jitter。 |
| **R3.3** | P0 | **后端 DB 长事务/嵌套借连接/SQLite 锁库**：请求级事务跨越同步 LLM/S3/WeChat 调用；`PgvectorHybridSearchAdapter` (`pgvector.py:145,374`) 嵌套借第 2 个连接；PG 缺 `pool_recycle`/keepalives；默认 SQLite 缺 WAL 与 `busy_timeout`。 | 长耗时 LLM/S3 外部 I/O 之前释放/提交短事务归还连接，写回时重开短事务；`pgvector` 消除嵌套连接池死锁风险（复用/串行归还）；PG engine 配 `pool_recycle=1800` 与 TCP keepalives；SQLite `connect` 事件开启 `WAL` + `busy_timeout=15000` + `synchronous=NORMAL` + `foreign_keys=ON`。 |
| **R3.4** | P0 | **前端静默轮询、生命周期与 `poller` 容错**：`silentToast` 全仓 0 调用导致轮询抖动弹窗并误杀前台 loading；`App.vue` `onHide` 未停轮询；`poller.ts:84` 单次失败即永久中止；`backgroundTask.ts:281` 遗漏 `questionJobs` 超时且 404 死轮询。 | 后台轮询与草稿同步全面传 `silentToast: true`；`request.ts` 在 `silentToast: true` 时**禁止调用 `dismissBlockingLoading()`**；`App.vue` `onHide` 暂停轮询、`onShow` 按需恢复；`poller.ts` 支持连续失败容忍阈值（如连续 3 次瞬时失败才中止）；`backgroundTaskStore` 补齐 `questionJobs` 超时态、404/403 立即移除。 |
| **R3.5** | P1 | **前端 401 单飞刷新 + 并发限流 + 防抖去重**：丢弃 `refresh_token` 且 `handleUnauthorized` 无锁；首页冷启 7 并发（4 个重复 `GET /materials`）；答题页 `PUT /answers` 零防抖易撞微信 10 并发上限；`localhost` 默认地址与 `manifest.json` 缺 `networkTimeout`、`uploadFile` 错报 15s。 | 持久化 `refresh_token` 并在 `request.ts` 实现单飞 401 静默续期与防重 `handleUnauthorized` 锁；`authStore.clearAuth()` 重置所有域 store 并停止轮询；`request.ts` 内置并发调度器（`maxConcurrent=6`）+ in-flight GET 去重 + 幂等 GET 有限次退避重试（含 jitter）；修复首页 `onMounted`/`onShow` 重复加载；答题输入加 500ms 防抖与 `draftQueue` 并发限制；默认开发基址改 `127.0.0.1`、`manifest.json` 配 `networkTimeout`、修复 `uploadFile` 超时分类。 |
| **R3.6** | P1 | **后端兜底 500 JSON 处理器、健康检查与配置卫生**：`main.py` 缺全局 `Exception` 处理器（返回纯文本且丢 CORS 头）；`CORS` 无条件 `*` + credentials；`/health` 未探测 Redis；`.env.example` 写错 `asyncpg`。 | `main.py` 增补全局脱敏 500 JSON 处理器；`AppSettings` 增加环境级 `cors_allow_origins`；`check_health()` 在启用 Redis 时执行短超时 ping；修复 `.env.example` 为 `postgresql+psycopg://`。 |

### R4：全项目 5 个已实证 P0 硬 Bug 与紧耦合 P1 修复

| ID | 级别 | 位置 | 根因与修复要求 |
|---|---|---|---|
| **R4.1** | P0 | `backend/app/services/auth.py:108-149`、`main.py:41` | **生产登录鉴权后门**：`dev_code`/`dev_`/`mock_` 及兜底 `wx_{code}` 仅允许 `settings.env != "production"`；生产启动 fail-fast 校验 `wechat_app_id`/`wechat_app_secret` 非空。 |
| **R4.2** | P0 | `backend/app/services/practice.py:1041-1055,1186-1194,1311-1331` | **先入队后 Commit 竞态**：`submit_practice` 与 `retry_grading` 改为先 `session.commit()` 再 `queue.enqueue("grading_jobs")`，入队失败以补偿短事务回写 `partially_graded`；`submit_practice` 使用 CAS 状态流转防双提交；为 `grading_records` 增加 `UNIQUE (attempt_item_id) WHERE is_final = true` 部分唯一索引（Alembic 迁移 0012）。 |
| **R4.3** | P0 | `backend/app/services/practice.py:1167`、`grading.py:337`、`diagnosis.py:593-605` | **退步知识点恒为空**：随 R1.3 合并单次流水线，确保 `generate_diagnosis_report` 在写入新 `MasteryRecord` 前读取真实的练习前 `previous_records` 基线。 |
| **R4.4** | P0 | `backend/app/services/grading.py:615,763` → `diagnosis.py:456-461,555-569` | **自评/重判后诊断永久陈旧**：`DiagnosisService` 新增 `refresh_diagnosis_report`（`force_refresh=True`），在 `self_evaluate_attempt` 与 `regrade_attempt` 改动最终得分后原地更新已有 `DiagnosisReport` 行，使结果页总分与错题/薄弱点保持一致；同时透传 `POST /grading/regrade` 的申诉理由 `reason`（`grading.py:665`）并修复 `_diagnosis_report.py:25` 主客观题型枚举漂移。 |
| **R4.5** | P0 | `miniprogram/src/utils/draftQueue.ts:49-72,108-114`、`stores/practice.ts:76-95` | **`draftQueue.reset()` 切题死锁交卷**：引入自增 `epoch` 代际号与静态绑定 `practiceId`，`reset()` 后旧在途任务静默丢弃不污染新练习 `failures`。 |
| **R4.6** | P1 | `question.py:1192-1203`、`material.py:605-616`、`idempotency/memory.py:31`、`useCoachChat.ts:27` | **紧耦合稳定性清理**：RQ 可重试基础设施异常不提前写死 `FAILED`（终态由 `handle_job_terminal_failure` 落盘）；`MemoryIdempotencyAdapter` 补 LRU 上限防 OOM；`useCoachChat` 存储键加 `userId` 隔离与有界淘汰；`practice.py:1097` 修正日志 `user_ref` 脱敏。 |

---

## 4. 验收标准（可观测、可测试）

1. **R1（异步错题再生）**：
   - 从报告页与学情错题本点击错题再生题时，HTTP 响应 `< 500ms` 返回 `202`（走 `POST /questions/jobs`，前端零调用 `apiGenerateQuestions`），无全屏阻塞遮罩，页面可自由滚动切换；
   - Worker 完成后自动生成练习并将 `result_practice_id` 写入 Job；报告页与其余页面顶部 `<BackgroundTaskBar />` 展示就绪提醒，**不自动强跳**，用户点击「立即作答」直达 `/subpackages/practice/pages/session/index?practice_id=...`；
   - 连续双击同一错题再生按钮不会重复入队两个活跃 LLM 任务；
   - 纯客观题交卷仅执行 1 次掌握度/错题更新，单测证实不发生双写。
2. **R2（初次生题极简提醒流）**：
   - 出题页提交生题后仅展示单一页内进度态（无双进度条、无占屏配置表单）；
   - 生题完成后**不强制跳转**且**不展示带答案/解析/讲义切片的杂乱题库列表**，仅展示极简「试卷已就绪」提醒卡（主按钮直达练习，次按钮可前往题库）；切走后由顶栏 `<BackgroundTaskBar />` 提醒，点击直达练习；
   - 存在部分考点待审但 `available.length > 0` 时不锁死开练；`view=generated` 入口无配置页闪屏。
3. **R3（连接稳定性）**：
   - 单测验证：全部 Redis 适配器配置了 `socket_timeout`/`health_check_interval` 且具备 `close()`；Worker 进程复用容器且 `shutdown` 释放资源；`LLMOptions.timeout=None` 不覆盖 `settings.llm.timeout` 且复用 `httpx.Client`；SQLite 启用 WAL + `busy_timeout`；PG 配置 `pool_recycle`；长耗时 LLM 路由/Worker 写回前不长时间持有未提交 DB 事务；`main.py` 未捕获异常返回统一 JSON 500；
   - 前端单测验证：后台轮询携带 `silentToast: true` 且失败时不弹 Toast、不调用 `dismissBlockingLoading()`；`App.vue` `onHide` 停轮询；`poller.ts` 容忍单次瞬时失败不中断；401 并发请求单飞刷新 `refresh_token` 仅触发一次；`request.ts` 限制并发数 `<= 6` 且合并同 URL in-flight GET；`clearAuth()` 清空域 store 并停止轮询。
4. **R4（5 个 P0 硬 Bug）**：
   - 单测覆盖：`env="production"` 下 `dev_code`/`dev_`/`mock_` 被拒绝；`submit_practice` 与 `retry_grading` 在 `commit()` 之后才 `enqueue()`；练习得分下降时 `regressed_knowledge_points` 非空；自评/重判改分后 `DiagnosisReport` 同步刷新且 `regrade_reason` 生效；`draftQueue.reset()` 后旧在途请求失败不污染新练习 `failures` 也不阻断交卷；`grading_records` 部分唯一索引迁移正反执行及模型一致性测试通过。
5. **质量门禁**：`task verify-backend`（ruff / mypy strict / lint-imports / pytest >= 80%）与 `task verify-frontend`（eslint / vue-tsc / vitest）全绿（遵循 `AGENTS.md` 关于 `tests/unit/core/algorithms/` 墙钟阈值单独复跑说明）。

---

## 5. 不在范围（留作二期独立任务）

- 拆分 4 个 1300–1983 行巨型 Service（`question.py`/`material.py`/`practice.py`/`grading.py`）
- `deploy/docker-compose.yml` 拆分 `worker-fast` / `worker-heavy` 双队列部署拓扑
- 基于 OpenAPI 自动生成前端 TypeScript Schema/枚举脚本
- 单题 AI 复查 `POST /grading/regrade` 改异步 202 端点与 Worker 整卷主观题 3 并发判分（本轮仅修其 DB 长事务、`reason` 透传与诊断刷新）
