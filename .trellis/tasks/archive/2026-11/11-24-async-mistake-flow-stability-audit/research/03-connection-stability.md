# 调研报告 03：前后端全链路连接稳定性专项审计（「不稳定的连接」）

> **任务目录**：`.trellis/tasks/11-24-async-mistake-flow-stability-audit`
> **审计范围**：小程序前端网络/状态/轮询层（`miniprogram/src/**`）+ 后端 ASGI/DB/Redis/HTTP/LLM/Worker/部署配置层（`backend/app/**`、`deploy/docker-compose.yml`）+ 既有规范核对（`.trellis/spec/**`）
> **模式**：只读代码与配置静态审计（未修改任何业务代码、测试或配置）

---

## 1. 执行摘要（为什么用户感知到「连接不稳定」）

「不稳定的连接」并非单一偶发网络问题，而是 **后端资源占用/阻塞放大** 与 **前端无容错、无节流、无静默降级** 叠加形成的系统性故障链：

1. **后端慢接口与无超时 Redis 把快接口一起拖死**：
   - 所有认证请求在进入路由前已由 `get_current_user` 开启 DB 事务；同步调 LLM/RAG/S3/微信的路由全程占用请求级 DB `Session`（`IDLE IN TRANSACTION`）长达 10–180s+，且 `pgvector` 检索在内部再次从同一连接池借用第 2 条连接，高并发下存在**连接池自锁/耗尽**风险（**P0-1**）。
   - 全仓所有 Redis 客户端（RQ 队列、幂等锁、解析进度缓存、助教记忆）均忽略 `RedisSettings.timeout=5.0`，未设置 `socket_timeout` / `health_check_interval`，而前端高频轮询的 `GET /materials`、`GET /materials/{id}` 每次必查 Redis；一旦空闲 TCP 被 NAT/Docker 静默回收，请求直接无限挂起直至撞上前端 15s 超时（**P0-2**）。
   - `LLMOptions.timeout=30.0` 硬编码默认值覆盖了 `ZHILIAN_LLM__TIMEOUT`（导致配置失效），配合 4 次 HTTP 重试 × LangGraph 2 次自愈 × 出题 3 轮质检，单次同步请求极易超过前端 90s 超时；同时 LLM/Embedding/Rerank 每次调用都新建/销毁 `httpx.Client`，无连接池复用，放大偶发握手失败与超时（**P0-3**）。
2. **前端把一次瞬时抖动放大为全站「断连风暴」**：
   - `request.ts` 虽然预留了 `silentToast`，但**全仓 0 处传入 `silentToast: true`**；后台 2.5s 轮询或 `onShow` 静默刷新只要偶发一次失败，就会弹出全局错误 Toast 并调用 `dismissBlockingLoading()` 强行打断用户前台操作；同时 `App.vue` 切后台从不调用 `stopPolling()`，切回前台瞬间爆发失败弹窗；`poller.ts` 无 `try/catch`，单次轮询失败即永久杀死判题轮询（**P0-4**）。
   - 前端完全丢弃后端签发的 `refresh_token`，且 401 处理无单飞锁，每 2 小时必触发并发 401 风暴与多次 `reLaunch`（**P1-1**）。
   - 页面 `onMounted` + `onShow` 重复并发拉取（首页冷启并发 7 请求、其中 4 次重复 `GET /materials`）、草稿 `@input` 零防抖狂发 PUT、缺少并发队列控制，叠加后台轮询极易触碰微信小程序 **10 并发请求上限**，触发 `exceed max request count` 并向用户报错「网络连接失败」（**P1-2**）。

---

## 2. 严重级别总览

| 编号 | 级别 | 所属层 | 核心问题 | 用户可见表现 |
| --- | --- | --- | --- | --- |
| **P0-1** | P0 Critical | 后端 DB / 并发 | 同步 LLM/RAG/S3/WeChat 调用全程占 DB Session（`IDLE IN TRANSACTION`）+ `pgvector` 嵌套借连接死锁 + 缺 `pool_recycle` | 慢请求期间全站普通接口 15s 超时、偶发 500 断连 |
| **P0-2** | P0 Critical | 后端 Redis / Worker | 全仓 Redis 客户端无 `socket_timeout` / `health_check_interval`（忽略配置）+ 高频轮询路径强依赖 Redis + Worker 连接池泄漏 | `GET /materials` / 轮询无规律 15s 卡死超时 |
| **P0-3** | P0 Critical | 后端 LLM / HTTP | `LLMOptions.timeout=30.0` 覆盖 `ZHILIAN_LLM__TIMEOUT` + 多层重试超时放大（>90s）+ 每次请求重建 `httpx.Client` 无连接池复用 | 出题/助教/重判频繁 90s 超时或上游握手断连 |
| **P0-4** | P0 Critical | 前端网络 / 轮询 | 全仓 0 处传 `silentToast: true` + 切后台不 `stopPolling()` + `poller.ts` 单次失败即永久中止 | 后台抖动狂弹「网络连接失败」、误杀前台 Loading、结果页卡死「判题中」 |
| **P1-1** | P1 High | 前端认证 | 丢弃 `refresh_token` + `handleUnauthorized()` 无单飞去重 | 每 2 小时并发 401 风暴、连环弹窗与多次 `reLaunch` |
| **P1-2** | P1 High | 前端并发 / 草稿 | 无全局并发限流、无幂等 GET 重试、草稿 `@input` 零防抖、冷启/切页重复并发 | 触发微信 10 并发上限（`exceed max request count`），误报「网络连接失败」 |
| **P1-3** | P1 High | 后端 SQLite | 默认 SQLite 未开 WAL、无 `busy_timeout`（默认仅 5s） | 本地/单机并发读写与后台任务碰撞报 `database is locked` |
| **P1-4** | P1 High | 后端 ASGI / 错误 | 全量同步 `def` 路由共抢 40 线程池（含 `/health`）+ 缺失兜底 500 JSON 异常处理器 | 高负载下 `/health` 饿死；DB/池异常回纯文本 500 绕过前端契约 |
| **P1-5** | P1 High | 前后端耦合 | 错题再生题仍走前端串行同步 `POST /questions/generate`（未走异步 jobs） | 错题巩固长等 90s+，超时失败率极高（与 Issue #1 耦合） |
| **P2-1** | P2 Medium | 前端配置 / 平台 | 默认 `localhost` 受 TUN/IPv6 影响、`manifest.json` 缺 `networkTimeout`、`uploadFile` 超时文案误报 15 秒 | 开发者工具 60s 假死、上传大文件超时提示不准 |
| **P2-2** | P2 Medium | 后端外设 / 配置 | S3/OCR 缺超时与 `close()`、内存队列裸线程无兜底、`.env.example` 写错 `asyncpg`、`/health` 未探 Redis、CORS 通配与凭据冲突 | 隐性资源泄漏、故障难诊断、配置踩坑 |

---

## 3. 分级详细发现与因果链

### P0-1 [Backend DB & Pool] 长耗时外部调用全程占用 DB Session + 嵌套借连接死锁风险

- **代码锚点**：
  - 请求级 Session 生命周期：`backend/app/api/deps/db.py:20-29`、`backend/app/container.py:146-170`
  - 认证前置开事务：`backend/app/api/deps/auth.py:161-199`（`get_current_user` 经请求级 `Session` 查询 `users` 表，自动 `BEGIN`）
  - 同步 HTTP 路由持 Session 等待慢外部调用：
    - `backend/app/api/v1/questions.py:125-202` -> `backend/app/services/question.py:492-600`（`generate_questions*` 全程持 `self.session` 等待 `execute_concurrent_kp_generation` 多考点并发 LLM/Embedding）
    - `backend/app/api/v1/questions.py:341-391` -> `backend/app/services/question.py:1738-1965`（`ask_coach`、`ask_scoped_coach` 持 `self.session` 等待 Embedding + Rerank + LangGraph LLM）
    - `backend/app/api/v1/grading.py:107` -> `backend/app/services/grading.py:715-762`（`regrade_attempt` 持 `self.session` 等待 LLM 重判）
    - `backend/app/api/v1/auth.py:30` -> `backend/app/services/auth.py:127`（`login_with_wechat` 持 `self.session` 调微信 `jscode2session` 最高 10s）
    - `backend/app/api/v1/materials.py:198` -> `import_material_file`（持 `self.session` 同步上传大文件到 S3/MinIO）
  - **嵌套 Session 借用**：`backend/app/integrations/search/pgvector.py:145, 374`（`with self._session_factory() as session:` 在外层请求已持有 1 条 DB 连接的前提下，再次向同一个 `QueuePool` 申请第 2 条连接）
  - **Worker 侧长事务/长 Session**：`backend/app/worker.py:44-71`、`backend/app/services/grading.py:225-285`（整卷判题逐题调 LLM 期间全程持同一 Session，最后统一 `commit()`）、`backend/app/services/material.py:460-560`（跨 S3 下载 + OCR/VLM + Embedding + LLM 全程持同一 Session）
  - **连接池配置缺失**：`backend/app/container.py:108-115`、`backend/app/core/config.py:42-57`（有 `pool_size=10, max_overflow=20, pool_timeout=30.0, pool_pre_ping=True`，但**缺失 `pool_recycle`**、**缺失 `connect_args`** 的 `connect_timeout` / TCP keepalive / `statement_timeout`）
- **因果机制**：
  1. 任意认证请求进入慢接口时，先执行 `SELECT users` 把数据库连接置为 `IDLE IN TRANSACTION`，随后等待外部 LLM/S3/OCR 数十秒到数分钟。
  2. 一旦并发慢请求 + 轮询请求占满 30 条连接池上限，若这些请求内部再调用 `PgvectorHybridSearchAdapter._recall_snippets` 申请第 2 条连接，**全部请求陷入连接池自锁**，直到 30s 后抛 `sqlalchemy.exc.TimeoutError`。
  3. 即便未死锁，其他轻量接口（列表、详情、保存草稿、登录）排队等待连接超过 15s 即触发前端 `DEFAULT_REQUEST_TIMEOUT_MS` 超时；而在 PostgreSQL/NAT 侧，`IDLE IN TRANSACTION` 超时或空闲断连会在 LLM 完成后 `commit()` 瞬间炸出 `OperationalError`，白白浪费 LLM 耗时并返回 500。
- **加固方向**：
  - 严格实行 **「短事务-释放连接-外部 I/O-短事务回写」** 模式：对同步 LLM/S3/WeChat 路径先读出纯 DTO 后 `session.rollback()/close()` 或改用按需短会话，外部调用期间**零数据库连接占用**。
  - `PgvectorHybridSearchAdapter` 支持复用外部传入的只读短会话或确保外层调用 `search` 前已释放连接，消除嵌套借连接死锁。
  - PostgreSQL 引擎补充 `pool_recycle=1800` 及 psycopg `connect_args`（`connect_timeout=5`、`keepalives=1`、`keepalives_idle=30`、`keepalives_interval=10`、`keepalives_count=3`）。

---

### P0-2 [Backend Redis & Worker] Redis 客户端全量缺失超时/保活配置 + 高频轮询路径挂死 + Worker 连接泄漏

- **代码锚点**：
  - 闲置配置：`backend/app/core/config.py:60-80`（定义了 `RedisSettings.timeout = 5.0` 和 `max_connections = 10`，全仓未传给任何 Redis 构造器）
  - 无超时/无保活的 Redis 构造点：
    - `backend/app/integrations/queue/rq_adapter.py:36`：`Redis.from_url(redis_url or "redis://localhost:6379/0")`
    - `backend/app/integrations/idempotency/redis.py:66`：`redis.from_url(target_url, decode_responses=True)`
    - `backend/app/integrations/queue/redis.py:81`：`redis.from_url(target_url, decode_responses=True)`
    - `backend/app/worker.py:98`：`Redis.from_url(settings.redis.redis_url)`
  - 高频读取路径强依赖上述无超时客户端：
    - `backend/app/services/material.py:175, 981, 1070, 1160` -> `backend/app/services/_material_pipeline.py:62-72, 113-163`（每次 `GET /materials` 与 `GET /materials/{id}` 都会调用 `redis_client.get` / `mget` 查解析进度）
    - `backend/app/container.py:74-76` -> `backend/app/integrations/llm/coach_memory.py:69-72, 95-102`（助教答疑读写 Redis 会话记忆）
    - `backend/app/services/practice.py:947, 977`（交卷幂等检查/加锁）
  - **Worker 连接池泄漏**：
    - `backend/app/worker.py:86-90`：每个后台任务都执行 `container = AppContainer.create()` 并在 `finally` 调 `asyncio.run(container.shutdown())`。
    - `backend/app/integrations/container.py:461-497`：`ProviderRegistry.shutdown()` 仅查找 `shutdown`/`aclose`/`close` 方法，但 `RQQueueAdapter`（`rq_adapter.py`）、`RedisIdempotencyAdapter`（`idempotency/redis.py`）、`RedisQueueAdapter`（`queue/redis.py`）均**未实现**任何关闭方法！
- **因果机制**：
  - `redis-py` 默认 `socket_timeout=None`、`socket_connect_timeout=None`、`health_check_interval=0`。在 Docker Desktop（Windows 宿主 ↔ 容器网桥）或云 Redis 环境下，空闲 TCP 连接被中间防火墙静默丢弃后，下一次 `GET /materials` 或 `GET /materials/{id}` 调 `redis_client.get/mget` 不会快速报错降级（即使 `_material_pipeline.py` 写了 `try/except` 降级，也根本等不到异常！），而是**阻塞等待 OS TCP 重传超时（数分钟）**，直接把前端 2.5s 轮询与首页加载全部拖成 15s 超时。
  - 在 Windows 上 `worker.py:106` 使用进程内 `SimpleWorker`，每个任务新建 `AppContainer` 却从未关闭 Redis 连接池，长期运行后累积耗尽 Redis `maxclients` 与文件描述符。
- **加固方向**：
  - 统一由配置工厂构造 Redis 客户端，强制透传 `socket_connect_timeout=min(3.0, settings.redis.timeout)`、`socket_timeout=settings.redis.timeout`（RQ Worker 阻塞消费专用连接除外，仅对 API 读写连接设短 `socket_timeout`）、`health_check_interval=30`、`retry_on_timeout=True`、`max_connections=settings.redis.max_connections`。
  - 进度缓存读取等非关键路径设更短超时（如 1–2s），确保异常时可迅速落回内存/DB 降级而不拖垮接口。
  - 为 `RQQueueAdapter`、`RedisIdempotencyAdapter`、`RedisQueueAdapter` 实现 `close()`（调用 `self._client.close()` / `connection_pool.disconnect()`），并避免 `worker.py` 每任务重复重建整个引擎与外部连接池。

---

### P0-3 [Backend LLM & HTTP] `LLMOptions.timeout=30.0` 覆盖环境配置 + 多层重试超时放大 + 零连接池复用

- **代码锚点**：
  - 配置失效缺陷：
    - `backend/app/integrations/llm/protocol.py:60`：`LLMOptions.timeout: float = 30.0`（硬编码非 `None` 默认值）
    - `backend/app/integrations/llm/openai.py:185`：`effective_timeout = options.timeout if options else self.timeout`
    - `backend/app/integrations/llm/agent_graph.py:91-104`：即使调用方传 `options=None`，`call_model_node` 也会新建 `LLMOptions(tools=..., tool_choice=...)`，把 `timeout` 重置为 `30.0`！
    - 受影响调用点：`services/_question_generation.py:356`、`services/_material_pipeline.py:373`、`services/question.py:1793`、`integrations/llm/coach_graph.py:498, 565, 609` 全部锁死 30s；`services/_grading_llm.py:85` 硬编码 20s；仅 `services/knowledge.py:225` 显式传 60s。
  - 零 HTTP 连接池复用（每次请求新建并销毁 `httpx.Client`）：
    - `backend/app/integrations/llm/openai.py:131-134`
    - `backend/app/integrations/embedding/openai.py:109-112`
    - `backend/app/integrations/rerank/siliconflow.py:80-83`
    - `backend/app/services/auth.py:127`（顶层 `httpx.get`）
    - `backend/app/integrations/_http_retry.py:20-29`（`managed_httpx_client` 生产路径 `external_client is None` 时每次 `with factory() as client:` 建完即关）
  - 重试与超时多层放大：
    - HTTP 层 `max_retries=3`（4 次尝试，`openai.py:163-168`，退避无 jitter `_http_retry.py:53, 64`）× LangGraph 自愈 2 轮（`agent_graph.py:180`）× 出题质检 `max_retries=2`（3 轮，`_question_generation.py:339`）× 多考点批处理（`question.py:592` 并发 3，但 10 考点需 4 波）。
- **因果机制**：
  - 面对思考型/长输出大模型（如 DeepSeek / Qwen-max），单次结构化出题或长文答疑 20–35s 返回属常态。因 `ZHILIAN_LLM__TIMEOUT` 被 `LLMOptions.timeout=30.0` 静默覆盖，第 30s 被 `httpx.ReadTimeout` 误杀并触发 3 次重试，总耗时瞬间膨胀至 **120s+**，直接击穿小程序 `LONG_REQUEST_TIMEOUT_MS=90000`（`miniprogram/src/utils/requestError.ts:29`）。
  - 每次请求新建 `httpx.Client` 导致无 TCP/TLS 会话复用、无 `httpx.Limits` 管控，并发出题/解析时频繁新建 TLS 连接，跨地域/代理链路下极易出现 `ConnectTimeout` / `RemoteProtocolError` / `ReadError`。
- **加固方向**：
  - 将 `LLMOptions.timeout` 改为 `float | None = None`，在 `OpenAICompatibleLLMAdapter.generate` 中改为 `options.timeout if (options and options.timeout is not None) else self.timeout`，并在 `agent_graph.py` 中透传 `None`。
  - 在 `OpenAICompatibleLLMAdapter`、`OpenAICompatibleEmbeddingAdapter`、`SiliconFlowRerankAdapter` 实例级别复用长生命周期 `httpx.Client(limits=httpx.Limits(...), timeout=httpx.Timeout(connect=10.0, read=..., write=15.0, pool=10.0))`，并实现 `close()` 纳入 `ProviderRegistry.shutdown()`。
  - 在 `_http_retry.py` 中增加 Full/Equal Jitter 退避，并为单次同步 HTTP 请求设置端到端 **总时间预算（deadline）**（例如同步接口 <= 75s，避免客户端 90s 断连后后端仍继续重试浪费配额）。

---

### P0-4 [Frontend Network & Polling] `silentToast` 零使用 + 切后台不停止轮询 + `poller.ts` 单次失败即永久中止

- **代码锚点**：
  - `miniprogram/src/utils/request.ts:33, 37-42, 87, 97`：定义了 `silentToast?: boolean`，但全仓无任何 API 或调用方传入 `true`；且 `reportFailure` 默认调用 `dismissBlockingLoading()` + `uni.showToast(...)`。
  - `miniprogram/src/stores/backgroundTask.ts:187-221`：`pollOnce` 每 2.5s 轮询活跃资料与出题任务，调用 `apiGetMaterialDetail` / `apiGetQuestionJob` 时未抑制全局错误 Toast 与 `dismissBlockingLoading()`。
  - `miniprogram/src/App.vue:8-14`：`onHide` / `onShow` 仅打印日志；`backgroundTaskStore.stopPolling()`（`backgroundTask.ts:347`）**全仓 0 处调用**。
  - `miniprogram/src/utils/poller.ts:82-95`：`const value = await fetcher()` 无异常捕获与容忍计数。
  - `miniprogram/src/subpackages/report/composables/useReportDetail.ts:78-96`（`pollGrading`）与 `miniprogram/src/subpackages/report/pages/detail/index.vue:115`：调用 `detail.pollGrading()` 未接 `.catch()`，且底层 `poller.run()` 遇到任意 1 次瞬时网络抖动/超时即 reject 退出，轮询永久终止；`stores/diagnosis.ts:28`、`stores/material.ts:57` 存在相同脆弱性。
- **因果机制**：
  1. 当存在后台解析/出题任务时，只要网络出现一次短瞬抖动或切到微信后台导致 socket 被系统挂起，每 2.5s 的后台轮询就会不断触发全局 `uni.showToast('网络连接失败...' / '请求超时（15秒）...')`，并**顺手调用 `dismissBlockingLoading()` 把用户当前正在执行的前台操作 Loading 强行关掉**，给用户造成「系统处处断连」的强烈错觉。
  2. 交卷后进入结果页轮询判题时，只要 20 次轮询中有 1 次抖动，`gradingPoller` 直接死亡，页面永久停留在「判题中」直到用户手动下拉刷新。
- **加固方向**：
  - 为所有后台轮询、静默刷新（`backgroundTask`、`pollGrading`、`fetchProfile`、`onShow` 后台同步、`apiSavePracticeDraft`）开放并传递 `silentToast: true`；在 `request.ts` 中区分「静默请求失败绝不调用 `dismissBlockingLoading()`」。
  - 在 `App.vue` 的 `onHide` 调用 `useBackgroundTaskStore().stopPolling()`，在 `onShow` 若 `hasActiveTasks` 则恢复轮询（同时监听 `uni.onNetworkStatusChange` 断网暂停、联网恢复）。
  - 在 `poller.ts` 中支持 `maxConsecutiveErrors`（如连续失败 3–5 次才中止/退避，单次失败按退避继续轮询而非直接死亡），并允许页面在 `onHide`/`onShow` 暂停与续传。

---

### P1-1 [Frontend Auth] 丢弃 `refresh_token` + 401 无单飞去重 -> 2 小时并发 401 风暴

- **代码锚点**：
  - 后端双令牌：`backend/app/core/security.py:24, 27`（`ACCESS_TOKEN_EXPIRE_MINUTES = 120`，`REFRESH_TOKEN_EXPIRE_DAYS = 30`）；刷新端点 `backend/app/api/v1/auth.py:51-70`（`POST /api/v1/auth/refresh`）。
  - 前端丢弃刷新令牌：`miniprogram/src/stores/auth.ts:69-70`（只保存 `resData.access_token`，忽略 `refresh_token`）；`miniprogram/src/api/modules/auth.ts` 无 refresh 封装。
  - 401 无去重：`miniprogram/src/utils/request.ts:11-23, 72-79, 143-149`（`handleUnauthorized()` 每次收到 401 都直接清存储、弹 Toast、调用 `uni.reLaunch({ url: '/pages/auth/login' })`）。
- **因果机制**：
  - 用户停留或隔 2 小时切回小程序，任意页面 `onShow` 瞬间发出 4–7 个并发请求，全部命中 401 -> 并发触发 4–7 次 `handleUnauthorized()`，导致连环 `reLaunch` 与弹窗闪烁，且中断正在填写的练习作答（未静默换新 token）。
- **加固方向**：
  - 持久化 `refresh_token`，在 `request.ts` 实现**单飞（single-flight）静默刷新队列**：首个 401 发起唯一一次 `POST /auth/refresh`（或微信小程序静默重登），其余并发 401 请求挂起等待新 token 后自动重放；仅当刷新本身失败时才执行**带防重锁（cooldown/guard）的单次** `handleUnauthorized()`。

---

### P1-2 [Frontend Concurrency & Drafts] 无并发限流 / 无幂等重试 / 草稿零防抖 / 冷启重复请求 -> 触发微信 10 并发上限

- **代码锚点**：
  - 首页冷启重复爆发：`miniprogram/src/pages/index/index.vue:206-224`（`onMounted` 调 `refreshAll()` 含 `loadFolders` + `loadMaterialList` + `refreshActiveTasks`[内含 `apiGetMaterialList` + `apiListQuestionJobs`] = 4 请求；紧接着 `onShow` 再发 `refreshActiveTasks` + `loadMaterialList` = 3 重复请求 -> **瞬时 7 并发，其中 `GET /materials` 并发 4 次**）。
  - 学情页爆发：`miniprogram/src/pages/review/composables/useReviewCenter.ts:158-167`（`Promise.all` 并发 6–7 请求）。
  - 后台轮询无并发上限：`miniprogram/src/stores/backgroundTask.ts:191-218`（`Promise.all` 同时请求全部活跃资料与出题任务）。
  - 草稿输入零防抖与并发重放：`miniprogram/src/subpackages/practice/pages/session/index.vue:168-171`（`@input` 每次击键直调 `practiceStore.recordAnswer`）-> `miniprogram/src/stores/practice.ts:115-121`（同步 `uni.setStorageSync` + `draftQueue.enqueue`）-> `miniprogram/src/utils/draftQueue.ts:49-106`（每道题独立并发 worker 无全局并发上限，`retryAll()` 并行发射所有失败题）。
  - 请求层无重试/无并发队列：`miniprogram/src/utils/request.ts:44-102`（无最大并发调度器、无同 URL in-flight GET 去重、对瞬时 `network`/`timeout`/502/503/504 幂等 GET 无退避重试）。
- **因果机制**：
  - 微信小程序强制限制同时最多 **10 个并发 `wx.request`**。当用户有 2–3 个后台解析/出题任务正在轮询，同时切换 Tab（学情/工作台）或在练习页快速输入主观题/触发 `retryAllDrafts` 时，总并发瞬间突破 10，微信底层直接以 `request:fail exceed max request count` 拒绝请求；`requestError.ts:117` 将其统统映射为 `kind='network'` -> Toast 报「网络连接失败，请检查网络后重试」。
- **加固方向**：
  - 在 `request.ts` 内置 **并发请求调度器（maxConcurrent = 6~8，留余量给上传/登录）** + **GET in-flight 请求合并（dedup）** + **幂等 GET 有限次退避重试（1–2 次，仅限 `network`/502/503/504，含抖动）**。
  - 修复 `pages/index/index.vue` 首屏 `onMounted` 与 `onShow` 双重加载（加首次跳过或 in-flight 合并），`backgroundTask.ts` 复用/合并列表查询或限流（并发 <= 2）。
  - `session/index.vue` 对文本输入加 **500–800ms debounce**（本地内存即时更新，落 storage 与 `draftQueue` 防抖），`draftQueue.ts` 限制全局并发（<= 2）并在 `retryAll()` 中串行/限流执行。

---

### P1-3 [Backend SQLite] 本地默认 SQLite 未开启 WAL 与 `busy_timeout`

- **代码锚点**：
  - `backend/app/container.py:101-106`：`create_engine(settings.db.db_url, echo=settings.db.echo, connect_args={"check_same_thread": False})`
  - `backend/app/core/config.py:34-37`：默认 `db_url = "sqlite:///./zhilian_dev.db"`
  - `backend/app/services/question.py:1053-1071`：内存队列模式下，异步出题在后台线程打开独立 SQLite Session 并发写入。
- **因果机制**：
  - SQLite 默认回滚日志模式（`DELETE`）在写入期间阻塞全部并发读/写，且 Python `sqlite3` 默认 `timeout=5.0`s。当后台出题/解析线程写库同时前台轮询/保存草稿，极易超过 5s 抛出 `sqlite3.OperationalError: database is locked`（HTTP 500）。
- **加固方向**：
  - 在 SQLite 引擎注册 SQLAlchemy `connect` 事件监听器，连接建立即执行 `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=15000; PRAGMA foreign_keys=ON;`，并设置 `connect_args={"check_same_thread": False, "timeout": 15.0}`。

---

### P1-4 [Backend ASGI Threadpool & Global Error Handler] 同步 `def` 线程池饱和风险 + 缺失兜底 500 JSON 处理器

- **代码锚点**：
  - 全量同步路由：`backend/app/api/v1/{auth,diagnosis,folders,grading,knowledge,materials,practices,questions,users}.py` 与 `backend/app/main.py:123`（`def health_check`）全部为同步 `def`，共享 AnyIO 默认 40 线程池。
  - 线程池退出阻塞：`backend/app/services/_question_generation.py:524-547`（某考点抛错后，`with ThreadPoolExecutor(...)` 退出阶段仍默认 `wait=True` 阻塞等待其余正在执行 LLM 的子线程结束）。
  - 缺失全局兜底异常处理器：`backend/app/main.py:92-116`（仅注册 `AppError` 与 `RequestValidationError`，未注册 `Exception` / `SQLAlchemyError` 处理器）。
- **因果机制**：
  - 慢同步 LLM 路由与挂死 Redis 读操作会占用 AnyIO 40 线程池配额；极端情况下连同步 `def health_check` 也被饿死导致网关/探针误判实例下线。
  - 当 DB 池超时、`OperationalError` 或未预期异常发生时，Starlette `ServerErrorMiddleware` 返回纯文本 `Internal Server Error`（非 JSON 且在异常路径可能缺少 CORS 头），前端 `request.ts:81-86` 无法提取 `detail/message`，只能报无信息量的 `请求失败 (500)` 或被浏览器/工具链判为网络中断。
- **加固方向**：
  - 配合 P0-1/P0-2/P0-3 消除慢/阻塞同步路径（同步重型接口异步化），并按需调优 Uvicorn workers / AnyIO threadpool tokens；将 `/health` 的 Redis/DB 探活控制在明确短超时内。
  - 在 `main.py` 增补全局 `@app.exception_handler(Exception)`（脱敏记录堆栈，返回统一 JSON `{"code": 50000, "message": "服务暂时繁忙，请稍后重试", "details": {}}` 并确保附带 CORS 头）。

---

### P1-5 [Cross-Layer] 错题再生题仍走前端串行同步 `POST /questions/generate`

- **代码锚点**：
  - `miniprogram/src/utils/questionGeneration.ts:31-58, 71-101`（`regenerateWrongPractice` -> `generateQuestionsInBatches` 串行循环调用 `apiGenerateQuestions` 即同步 `POST /questions/generate`）
  - 调用方：`miniprogram/src/subpackages/report/composables/useReportDetail.ts:151`、`miniprogram/src/pages/review/composables/useReviewCenter.ts:308`
- **因果机制**：
  - 尽管系统已建设异步出题任务（`POST /questions/jobs`），错题再生题仍走长连接同步接口且按批次串行等待。多考点场景下极易超过 90s（或反向代理 60s 网关超时），导致用户看到「请求超时（90秒）」，而后端实则仍在出题（与 Issue #1 调研高度交集，建议在 Issue #1 改造中一并迁至异步任务流）。

---

### P2-1 [Frontend Platform & Config] `localhost` 默认地址、`manifest.json` 缺 `networkTimeout`、`uploadFile` 超时提示失真

- **代码锚点**：
  - `miniprogram/src/utils/request.ts:9`：`API_BASE_URL = ... || 'http://localhost:8000/api/v1'`（`.trellis/spec/frontend/network-contract.md:241-243` 已记录 `localhost` 在 TUN 代理 / IPv6 `::1` 场景引发 60s 无响应）
  - `miniprogram/src/manifest.json:11-20`：`mp-weixin` 块未配置 `networkTimeout`（`uploadFile` 依赖平台默认 60s，弱网传大 PDF 容易被平台强断）
  - `miniprogram/src/utils/request.ts:167`：`uploadFile` 的 `fail` 回调调用 `classifyTransportFailure((err as any)?.errMsg)` 未传 `timeoutMs`，导致 60s 上传超时被错误提示为「请求超时（15秒）」
- **加固方向**：
  - 默认开发地址改用 `http://127.0.0.1:8000/api/v1`；在 `manifest.json` 的 `mp-weixin` 中显式配置 `networkTimeout`（如 `request: 90000, uploadFile: 120000`）；`uploadFile` 失败分类传入实际上传超时值（如 `60000` 或 `120000`）。

---

### P2-2 [Backend External Clients & Config Hygiene] S3/OCR 缺超时与释放、内存队列裸线程、配置与健康检查缺口

- **代码锚点**：
  - `backend/app/integrations/storage/s3.py:82-91`：boto3 `Config(signature_version="s3v4")` 未显式设置 `connect_timeout`、`read_timeout`（默认各 60s）、`max_pool_connections`（默认 10），且未实现 `close()`。
  - `backend/app/integrations/ocr/baidu.py:80` & `tencent.py:80-104`：`BaiduOCRAdapter` 创建了持久 `httpx.Client(timeout=timeout)` 但未设置连接池 `limits` / 分离 `connect` 超时且无 `close()`；`TencentOCRAdapter` 无 `close()`。
  - `backend/app/services/question.py:1053-1071` & `138-160`：`MemoryQueueAdapter` 模式下裸起 `threading.Thread(..., daemon=True)`，无并发上限，且后台异常仅打日志不保证回写 `QuestionGenerationJob` 终态失败（任务可能永久卡在 `queued`/`running`，前端无限轮询）。
  - `backend/.env.example:16`：示例 URI 为 `postgresql+asyncpg://...`，而 `backend/app/container.py:108` 使用同步 `create_engine`，直接复制 `.env.example` 启动即报错（`deploy/docker-compose.yml:49` 使用的是 `postgresql+psycopg://`）。
  - `backend/app/main.py:83-89`：`CORSMiddleware(allow_origins=["*"], allow_credentials=True)` 违背 Fetch CORS 规范（生产应按环境白名单配置）。
  - `backend/app/container.py:280-321`：`check_health()` 仅探测 DB `SELECT 1`，未探测 Redis 连通性（当 `queue`/`idempotency` 使用 Redis 且 Redis 失联时 `/health` 仍报 200 OK，掩盖 P0-2 故障）。
  - `miniprogram/src/subpackages/report/composables/useReportDetail.ts:78-96`：`pollGrading` 仅轮询 20 次 × 2.5s = 50s，主观题较多时容易在判完前提前停止。

---

## 4. 规范与代码现状交叉核对（Spec vs Reality）

| 规范文档 | 规范约定 | 代码真实状态与偏离 |
| --- | --- | --- |
| `.trellis/spec/frontend/network-contract.md` | 15s 默认超时 + 90s LLM 白名单超时；结构化 `RequestError`；`localhost` 列为已知偏离 | 1) 代码新增了 `silentToast` 选项但规范未更新且全仓 0 处调用；2) `uploadFile` 超时文案错用 15s 默认值；3) `api/index.ts` 已拆分为 `api/modules/*`；4) 缺 401 单飞刷新与并发限流契约；5) `localhost` 偏离至今未收敛 |
| `.trellis/spec/backend/database-guidelines.md` | 同步 `Session`，请求级注入 `get_db_session`，Service 层负责 commit/rollback | 1) 规范未禁止在持有 DB `Session` 时执行长耗时外部 I/O（LLM/S3/WeChat）；2) 未约束禁止在请求事务内二次 `session_factory()` 嵌套借连接（`pgvector.py` 违规）；3) 未约束 SQLite WAL / `busy_timeout` 与 PG `pool_recycle` |
| `.trellis/spec/backend/error-handling.md` | `AppError` / `RequestValidationError` 统一 JSON 响应，严禁裸吞错 | `main.py` 缺少兜底 `Exception` / `SQLAlchemyError` 处理器，连接池超时/DB 断连直接泄漏纯文本 500 |

---

## 5. 推荐落地修复顺序（按投入产出比排序）

1. **第一批（止血 — 立即消除 80% 体感「连接不稳定」）**：
   - **后端 Redis 补超时与关闭**（P0-2）：给 `RQQueueAdapter` / `RedisIdempotencyAdapter` / `RedisQueueAdapter` 透传 `socket_connect_timeout` / `socket_timeout` / `health_check_interval` / `max_connections` 并实现 `close()`。
   - **后端修复 `LLMOptions.timeout=None` 覆盖 Bug + 复用 `httpx.Client` 连接池 + 退避加 jitter**（P0-3）。
   - **前端轮询静默化与生命周期治理**（P0-4）：后台轮询与静默刷新传 `silentToast: true` 且不误杀 `dismissBlockingLoading()`；`App.vue` `onHide`/`onShow` 联动 `stopPolling()`/恢复；`poller.ts` 支持连续失败容忍计数。
2. **第二批（根治 — 消除高并发雪崩与 2 小时断连）**：
   - **后端 DB Session 与外部 I/O 解耦 + 消除 `pgvector` 嵌套借连接 + PG `pool_recycle` / SQLite WAL**（P0-1、P1-3）。
   - **前端 401 单飞刷新 `refresh_token` + 并发限流队列（max=6~8）+ GET 去重与有限重试 + 草稿防抖**（P1-1、P1-2）。
   - **后端兜底 500 JSON 处理器 + `/health` 增加 Redis 探活**（P1-4、P2-2）。
3. **第三批（架构协同 — 与 Issue #1 联动）**：
   - **错题再生题迁移至异步任务流**（P1-5），彻底消除同步多批 90s 超时；修复 `manifest.json` `networkTimeout`、`127.0.0.1` 默认地址与 `.env.example` 驱动名（P2-1、P2-2）。

---

## 6. 关联项目规范清单（供 `implement.jsonl` / `check.jsonl` 装配）

- `.trellis/spec/frontend/network-contract.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/spec/frontend/quality-guidelines.md`
- `.trellis/spec/frontend/api-payload-contracts.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/logging-guidelines.md`
- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`
