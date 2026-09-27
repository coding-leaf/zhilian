# Research: AUTH 切片只读 bug 审计（认证 / 登录 / 会话）

- **Query**: 只读审计 AUTH 垂直切片前后端 bug，按 design.md §8 ledger schema 输出
- **Scope**: mixed（backend + frontend + cross-layer）
- **Date**: 2026-09-27
- **审查范围**:
  - backend: `services/auth.py`、`api/v1/auth.py`、`api/v1/users.py`、`api/deps/auth.py`、`api/deps/user.py`、`api/deps/db.py`、`core/security.py`、`core/config.py`、`core/errors.py`、`main.py`、`schemas/auth.py`、`schemas/user.py`、`repositories/user.py`、`models/user.py`、`models/base.py`、`container.py`、`api/v1/__init__.py`
  - frontend: `api/auth.ts`、`api/user.ts`、`stores/userStore.ts`、`utils/request.ts`、`utils/storage.ts`、`utils/error.ts`、`config/env.ts`、`pages/auth/login.vue`、`pages/login/index.vue`、`pages/profile/index.vue`、`App.vue`、`types/auth.ts`、`types/storage.ts`、`types/common.ts`、`pages.json`
  - 现有测试: `tests/unit/core/test_security.py`、`tests/unit/services/test_auth_service.py`、`tests/unit/api/test_auth_router.py`、`tests/unit/api/test_auth_deps.py`、`miniprogram/tests/unit/utils/request.spec.ts`、`miniprogram/tests/unit/api/auth.spec.ts`
- **证据强度图例**: 实测（命令可复跑）> 测试（现有用例可复现）> 推理（可跳转 `file:line` 的静态推理链）

---

## 功能性问题（P0 / P1 / P2）

### BUG-AUTH-001

- **级别**: P0
- **切片**: AUTH
- **层**: backend
- **位置**: `backend/app/core/security.py:33-41`（`get_secret_key`）、`backend/app/core/config.py:398-401`（`secret_key` 字段）、`backend/app/core/config.py:421-426`（`env_prefix="ZHILIAN_"`）
- **现象**: JWT 签名/验签密钥只读取裸环境变量 `SECRET_KEY`，从不读取项目强类型配置 `settings.secret_key`（其环境变量名应为 `ZHILIAN_SECRET_KEY`）。生产环境按配置约定注入 `ZHILIAN_SECRET_KEY` 时被完全忽略，令牌将回退使用源码中硬编码的公开默认密钥 `DEFAULT_SECRET_KEY`。
- **证据/复现**: **实测**。只读命令（`backend/` 下，`PYTHONDONTWRITEBYTECODE=1`、`python -B` 防写字节码）:
  ```
  uv run python -B -c "import os; os.environ.pop('SECRET_KEY', None); \
    os.environ['ZHILIAN_SECRET_KEY']='prod-super-secret-key-at-least-32-chars!'; \
    from app.core.config import get_settings; get_settings.cache_clear(); \
    from app.core.security import get_secret_key; \
    print('settings.secret_key =', get_settings().secret_key.get_secret_value()); \
    print('security.get_secret_key() =', get_secret_key()); \
    print('MATCH =', get_secret_key() == get_settings().secret_key.get_secret_value())"
  ```
  输出:
  ```
  settings.secret_key = prod-super-secret-key-at-least-32-chars!
  security.get_secret_key() = zhilian-insecure-development-secret-key-change-in-production-2026
  MATCH = False
  ```
  旁证: `tests/unit/core/test_security.py:199-203` 仅用裸 `SECRET_KEY` 断言覆盖；`tests/unit/core/test_config.py:127` 使用 `ZHILIAN_SECRET_KEY` 断言的是 `settings.secret_key`，两者互不交叉，故测试无法发现该断链。
- **影响**: 安全。生产若仅按规范注入 `ZHILIAN_SECRET_KEY`，篡改者可利用公开默认密钥伪造任意用户 `sub`/`token_version` 的合法 JWT，绕过全部鉴权。属越权/安全类 P0。
- **修复方向**: 让 `core/security.py` 统一从 `get_settings().secret_key.get_secret_value()` 取密钥（保留显式 `secret_key` 入参用于测试）；生产环境对仍为默认密钥的情况做启动期 fail-fast 校验。

### BUG-AUTH-002

- **级别**: P1
- **切片**: AUTH
- **层**: cross-layer
- **位置**: `miniprogram/src/pages/auth/login.vue:62-65`（固定传 `nickname: '学员用户'`）；`backend/app/services/auth.py:185-190`（老用户 `nickname is not None` 时执行 `update_profile`）
- **现象**: 前端每次登录固定以 `nickname: '学员用户'` 提交；后端对已存在用户只要 `nickname is not None` 就用其覆盖数据库昵称。因此真实微信昵称/用户自定义昵称在每次登录时被改写为字面量“学员用户”。
- **证据/复现**: **测试 + 推理**。
  - 后端既有用例 `tests/unit/services/test_auth_service.py:53-71` 明确断言二次登录会用入参覆盖昵称（`UpdatedName`），证明覆盖行为是后端既定语义。
  - 前端 `login.vue:62-65` 硬编码 `nickname: '学员用户'`，未回传微信真实昵称。
  - `backend/app/services/auth.py:185-190` 的 `if nickname is not None or avatar_url is not None` 分支确认覆盖触发条件。
  推理链: 任意老用户再次登录 → 前端必传非空 `nickname` → 服务层必走 `update_profile` → 昵称落库被覆盖。
- **影响**: 数据错误。用户资料昵称被持续覆盖为占位值，属持久化数据污染（当前个人中心页为占位页，用户可感知性偏低，故定级 P1 而非 P0）。
- **修复方向**: 登录时不要硬编码 `nickname`（传 `None` 表示不更新），微信真实用户信息应经 `getUserProfile`/授权流程获取后再提交，或后端仅在字段确有变化时更新。

### BUG-AUTH-003

- **级别**: P1
- **切片**: AUTH
- **层**: cross-layer
- **位置**: `miniprogram/src/utils/request.ts:262-266`（`is401` → `handle401Error`）、`miniprogram/src/utils/request.ts:140-146`（无 refresh_token 时 `redirectToLogin` + 抛 20001）；触发端 `miniprogram/src/api/auth.ts:18-27`（`loginByWechat`，`skipAuth: true`）
- **现象**: 登录接口失败会返回 HTTP 401 / 业务码 20001（见证据）。前端 `request()` 对所有非 refresh URL 的 401 一律走静默刷新分支：登录时通常无本地 `auth_tokens`，于是删除存储、`uni.reLaunch('/pages/auth/login')` 并抛出“登录状态已过期”。结果是登录页收到错误前已被重载，用户既拿不到真实失败原因（如“用户账号已被停用/注销”、微信 code 无效），又被强制跳回登录页。
- **证据/复现**: **测试 + 推理**。
  - 后端用例 `tests/unit/api/test_auth_router.py:177-210` 证明 login 在“已注销/已停用”时返回 `401` + `code=20001`；`services/auth.py:130-138` 证明微信鉴权失败同样抛 `AuthenticationError(401/20001)`。
  - `request.ts:264` `const is401 = statusCode === 401 || resData.code === 20001;`，`request.ts:200` `isRefreshUrl = options.url.includes('/auth/refresh')`；login 的 url `/api/v1/auth/login` 使 `isRefreshUrl=false`，必然进入 `handle401Error`。
  - `login.vue:92-97` 的 catch 展示 toast，但此时页面已被 `reLaunch`（`request.ts:144/188`）重载。
- **影响**: 功能性错误。登录失败路径被错误归类为“会话过期”，吞掉真实错误码/文案并触发异常重定向；不当的重定向还可能掩盖服务端限流/封禁等诊断信息。
- **修复方向**: 对 `skipAuth` 请求（或登录/刷新等匿名端点）跳过 401 静默刷新与登录重定向，直接抛出并展示后端错误码/文案。

---

### BUG-AUTH-004

- **级别**: P2
- **切片**: AUTH
- **层**: cross-layer
- **位置**: `miniprogram/src/api/user.ts:34-42`（`updateUserProfile` → `PUT /api/v1/users/me`）；`backend/app/api/v1/users.py:24-66`（仅注册 `GET /me` 与 `DELETE /me`）
- **现象**: 前端存在 `PUT /api/v1/users/me` 的画像更新调用，但后端 users 路由没有任何 PUT 处理器。该调用若被启用将收到 405 Method Not Allowed。
- **证据/复现**: **推理（全仓检索）**。`backend/app/api/v1/users.py` 全文仅 `@router.get("/me")` 与 `@router.delete("/me")`；`backend/app/api/v1/__init__.py:16` 聚合 `users_router`；全仓 PUT 路由仅出现在 `api/v1/questions.py:233`、`api/v1/practices.py:195`。当前该函数无调用方（`grep updateUserProfile` 仅命中定义），属契约悬空。
- **影响**: 前后端契约不一致。画像更新能力实际不可用（若被接入即 405）；当前为潜在缺陷。
- **修复方向**: 二选一——后端补齐 `PUT /users/me`（含 `UpdateUserProfilePayload` schema 与 service 方法），或移除前端悬空调用与类型。

### BUG-AUTH-005

- **级别**: P2
- **切片**: AUTH
- **层**: frontend
- **位置**: `miniprogram/src/utils/request.ts:160-175`（静默刷新后仅 `storage.setItem('auth_tokens', newTokens)`，随后 `request(item.options)` 重放）；`miniprogram/src/stores/userStore.ts:16-34`（令牌状态唯一来源为 store 的 `tokens` ref）
- **现象**: 401 静默刷新成功后只更新了本地存储的令牌，未同步 Pinia `userStore.tokens`。请求层（`request.ts:220-223`）从 storage 读新令牌，故请求本身正确；但 store 内 `tokens`/`isAuthenticated`（`userStore.ts:20`）仍指向旧令牌对，造成“存储态与内存态不一致”。
- **证据/复现**: **测试 + 推理**。`miniprogram/tests/unit/utils/request.spec.ts:142-195` 断言刷新后 storage 中为新 token，但全用例未断言 `useUserStore().tokens` 被更新；`request.ts` 未导入 `userStore`（避免循环依赖），无任何回写通道。`request.spec.ts:197-251` 的并发重放同样只校验 storage。
- **影响**: 状态不一致。当前消费方 `index.vue`/`App.vue` 仅用 `isAuthenticated` 布尔与 profile，旧 token 恒为 truthy，故暂不致功能中断；但任何直接读取 store `tokens.access_token`/`refresh_token` 的后续代码会拿到过期旧值。
- **修复方向**: 刷新成功后通过可注入的回调/事件同步更新 store 令牌，或让 store 作为令牌唯一真源（request 从 store 读取）。

### BUG-AUTH-006

- **级别**: P2
- **切片**: AUTH
- **层**: frontend
- **位置**: `miniprogram/src/utils/request.ts:160-175`
- **现象**: 静默刷新成功后 `await request<T>(options)` 重放原请求，但无“已重试/最大重试次数”标记。若重放请求再次返回 401/20001，且刷新端点持续返回可用新令牌，则每次都会再次进入 `handle401Error` → 刷新 → 重放，形成无界循环，Promise 永不 settle（挂起）。
- **证据/复现**: **推理**。`request.ts:264-265` 对每次 401 无条件调用 `handle401Error`；`handle401Error` 内部重放（`166`）与队列重放（`172`）均再次走 `request()`，无 attempt 计数或 `skipAuth` 短路。触发前提是服务端“能发新令牌但拒绝该 access token”，属异常/半故障态。
- **影响**: 未处理异常/Promise 挂起风险。半故障态下请求层可能无限往返刷新端点，阻塞调用方并放大服务端压力。
- **修复方向**: 为重放请求加 `isRetry` 标记或最大重试阈值，超过阈值直接抛认证错误并清理会话。

### BUG-AUTH-007

- **级别**: P2
- **切片**: AUTH
- **层**: frontend
- **位置**: `miniprogram/src/utils/storage.ts:11`（`MAX_STORAGE_BYTES = 20 * 1024`）、`miniprogram/src/utils/storage.ts:73-75`（`serialized.length > MAX_STORAGE_BYTES`）
- **现象**: 常量语义为“字节阈值（20KB）”，但校验使用的是字符串 `serialized.length`（UTF-16 code unit 计数）。含中文/多字节字符时，字符数 ≤ 字节数，实际写入字节可显著超过 20KB 而通过校验。
- **证据/复现**: **推理**。`storage.ts:11` 命名与注释为 bytes；`storage.ts:73` 直接比较 `.length`。例如 20000 个中文字符（`.length=20000`）在 UTF-8 下约 60KB，仍 `< 20480` 通过。`miniprogram/tests/unit/utils/storage.spec.ts` 未覆盖多字节边界。
- **影响**: 边界值错误。本地存储“20KB 保护”对多字节内容失效，可能触发小程序存储配额；同时纯 ASCII 场景下保护正常。
- **修复方向**: 按实际编码计算字节数（如 `new TextEncoder().encode(serialized).length` 或 `wx` 存储 API 的字节口径）再比较阈值。

### BUG-AUTH-008

- **级别**: P2
- **切片**: AUTH
- **层**: frontend
- **位置**: `miniprogram/src/pages/auth/login.vue:73-80`
- **现象**: 登录成功后先写入一个硬编码占位画像（`id: 'usr_current'`，非真实 UUID，`created_at` 为客户端当前时间），随后 `void userStore.hydrateProfile()` 以“发射后不管”方式异步水合。若水合失败（网络异常、非 401 错误），catch 分支（`userStore.ts:74-90`）不清理占位数据，占位画像会长期驻留 store 与 UI。
- **证据/复现**: **推理**。`login.vue:73` 硬编码对象含非法 UUID 字符串 `usr_current`；`login.vue:80` 未 `await`；`userStore.ts:60-91` 失败时仅在 `isAuthError` 时 `clearTokens/clearProfile`，非认证错误直接 `return null`，占位 profile 保留。消费方 `pages/index/index.vue:79` 直接读取 `userStore.profile?.nickname`。
- **影响**: 状态未重置/占位数据残留。后端已返回真实用户，但前端以伪造占位画像覆盖并可能在失败后保留；`id` 非 UUID 也对后续任何按 id 的调用构成隐患（当前 `userId` 未被请求消费，故影响有限）。
- **修复方向**: 登录响应或立即 `await` 的 `GET /users/me` 作为画像唯一真源，失败时置空并提示；删除硬编码占位对象。

### BUG-AUTH-009

- **级别**: P2
- **切片**: AUTH
- **层**: backend
- **位置**: `backend/app/api/v1/auth.py:92-93`（`revoke` 忽略 `revoke_tokens` 返回值）、`backend/app/api/v1/users.py:65-66`（`delete_current_user_account` 忽略 `delete_account` 返回值）
- **现象**: 两个端点丢弃 service 布尔返回值，恒返回 `success=True` 与成功文案。当 service 内部实际未命中（如用户不存在/软删除 `rowcount=0`）时，客户端仍收到成功。
- **证据/复现**: **推理**。`services/auth.py:296` `return bool(new_version > 0)`、`services/auth.py:369` `return success`；端点 `auth.py:92` 与 `users.py:65` 均未接收返回值。触发条件为已认证用户记录缺失（并发注销/硬删等边界），正常自身路径下通常为 True。
- **影响**: 接口契约不符。失败被报告为成功，误导客户端状态机（如注销后仍认为凭据已吊销）。
- **修复方向**: 依据 service 返回值决定 `success` 字段与提示，或在失败时抛出对应业务异常。

### BUG-AUTH-010

- **级别**: P2
- **切片**: AUTH
- **层**: backend
- **位置**: `backend/app/services/auth.py:123`（`httpx.get(url, params=params, timeout=10.0)`）；调用方为 async 路由 `backend/app/api/v1/auth.py:30-48`
- **现象**: 微信 `jscode2session` 置换使用同步 `httpx.get`，却被 `async def login` 在事件循环线程内直接调用（未走线程池/异步客户端）。真实微信鉴权期间（最长 10s 超时）将阻塞整个事件循环。
- **证据/复现**: **推理**。`api/v1/auth.py:30` 为 `async def login`，直接同步调用 `auth_service.login_with_wechat`；`services/auth.py:123` 为同步阻塞 `httpx.get`。配置了 `wechat_app_id`/`wechat_app_secret` 时该分支才会执行（生产场景）。
- **影响**: 并发/性能错误。单个登录请求可阻塞其他所有请求的调度，出现全局卡顿/超时放大；不改变单请求正确性，故定 P2。
- **修复方向**: 改用 `httpx.AsyncClient` 异步调用，或将同步调用显式 offload 到线程池（`run_in_threadpool`）。

### BUG-AUTH-011

- **级别**: P2
- **切片**: AUTH
- **层**: backend
- **位置**: `backend/app/api/deps/auth.py:190-196`（`container.create_auth_service(session=container.session_factory())`）、`backend/app/api/deps/user.py:40-46`、`backend/app/api/deps/auth.py:143-145`
- **现象**: fallback 分支直接用 `container.session_factory()` 新建 Session，既不 `close()` 也不交由 FastAPI 生成器依赖托管，属连接泄漏；`get_current_user` 的该分支还会与请求级 Session 并存产生双会话。
- **证据/复现**: **推理（含可达性评估）**。`deps/auth.py:193` 无 try/finally 关闭逻辑；而正常生产路径 `auth_service` 由 `Depends(get_auth_service)` 提供且为 `AuthService` 实例（`deps/auth.py:185` 的 `isinstance` 分支先命中），故该泄漏分支仅在 `dependency_overrides` 注入非 `AuthService` 时可达；`deps/user.py:43-45` 同理仅在注入的 `session` 非 `Session` 时可达。当前生产不可达，故定 P2 而非 P0/P1。
- **影响**: 资源泄漏（潜在）。一旦该 fallback 被真实触发（测试覆盖/未来重构），每次请求泄漏一个未关闭会话，长跑将耗尽连接池。
- **修复方向**: fallback 生成器也使用 `with container.get_session()` 托管生命周期，或复用注入的请求级 Session。

---

## 跨层契约核对（AUTH）

| 契约点 | 后端（file:line） | 前端（file:line） | 结论 |
|---|---|---|---|
| POST `/api/v1/auth/login` | `api/v1/auth.py:24-48` | `api/auth.ts:18-27` | 一致（路径/方法/请求体字段 `code,nickname,avatar_url`） |
| POST `/api/v1/auth/refresh` | `api/v1/auth.py:51-70` | `api/auth.ts:35-42` | 一致（`refresh_token` 字段、`skipAuth`） |
| POST `/api/v1/auth/revoke` | `api/v1/auth.py:73-93` | `api/auth.ts:49-53` | 路径/方法一致；**响应 `success` 不反映 service 结果**（BUG-AUTH-009） |
| GET `/api/v1/users/me` | `api/v1/users.py:24-43` | `api/user.ts:21-26` | 一致（`UserProfileResponse` 字段 `id,nickname,avatar_url,created_at`） |
| PUT `/api/v1/users/me` | 无处理器 | `api/user.ts:34-42` | **不一致 → 405**（BUG-AUTH-004） |
| DELETE `/api/v1/users/me` | `api/v1/users.py:46-66` | `api/user.ts:49-53` | 路径/方法一致；响应成功态同 BUG-AUTH-009 |
| 令牌响应字段 | `schemas/auth.py:29-37`（`access_token,refresh_token,token_type,expires_in`） | `types/auth.ts:12-18` | 一致（snake_case 对齐，`expires_at?` 前端可选、后端不返回，非缺陷） |
| 登录请求字段 | `schemas/auth.py:11-18`（`extra="forbid"`） | `types/auth.ts:6-10` | 一致 |
| 错误码 20001 / HTTP 401 | `core/errors.py:70-94`、`main.py:89-99` | `request.ts:263,279-285`、`utils/error.ts:9` | 一致（前端按 20001/401 识别认证失效） |
| 错误码 10001 / HTTP 422 | `main.py:102-112` | `utils/error.ts:8` | 一致 |
| 存储键 `auth_tokens` | — | `types/storage.ts:9`、`stores/userStore.ts:30`、`utils/request.ts:141,162,220` | 一致（白名单内，键名统一） |
| 路由注册 | — | `pages.json:10-26`（含 `pages/auth/login`） | 一致；`pages/profile/index.vue` 存在但**未在 `pages.json` 注册且无引用**（属非功能性死页面，另计 SMELL，不在此列） |

---

## Caveats / Not Found

- **未列为编号 bug 的客观事实**:
  - `services/auth.py:208-212` 与 `266-270` 将 `expires_in=7200` 硬编码，与 `core/security.py:24` 的 `ACCESS_TOKEN_EXPIRE_MINUTES=120` 为两处独立来源；当前值等价（120min=7200s），无现时可观察缺陷，属常量重复（SMELL 范畴）。
  - `services/auth.py:36-63` 与 `api/deps/auth.py:91-118` 各定义一份 `validate_user_status`；`AuthService` 同时保留 `revoke_user_tokens`/`delete_user_account` 等别名；`container.py` 具 `create_*` 与 `get_*` 双套方法。均为重复实现/薄 shim，非功能性，按任务要求不在本文件计数。
  - 前端 `api/auth.ts` 的 `refreshToken`/`revokeTokens`、`api/user.ts` 的 `updateUserProfile`/`deleteAccount` 无调用方（`grep` 仅命中定义）——死代码，按任务要求另计 SMELL（其中 `updateUserProfile` 因对应后端缺失已按契约问题计入 BUG-AUTH-004）。
  - `pages/profile/index.vue` 未被 `pages.json` 注册、无导航引用——死页面，按任务要求另计 SMELL。
- **疑似(SR)**: 本切片未发现确凿的真机/开发者工具专属渲染或交互问题。（登录失败时 `uni.reLaunch` 与 `uni.showToast` 的时序表现可能与平台相关，但根因是 BUG-AUTH-003 的代码逻辑，已按 P1 计入，不重复计 SR。）
- **环境受限(ENV)**: 本切片未触发工具链失败；仅执行了一条只读 Python 演示命令且成功，无 ENV 项。
- **证据强度说明**: BUG-AUTH-001 为实测；BUG-AUTH-002、003 为“现有测试 + 静态推理”；其余为静态推理（均可跳转 `file:line`）。BUG-AUTH-006/011 的触发依赖特定运行态，已在各自条目注明可达性。
- **未覆盖**: 无真实微信客户端/真机联调，微信 `jscode2session` 真实响应分支未运行验证。

---

## 本切片计数小结

| 级别 | 数量 | 编号 |
|---|---|---|
| P0 | 1 | BUG-AUTH-001 |
| P1 | 2 | BUG-AUTH-002、BUG-AUTH-003 |
| P2 | 8 | BUG-AUTH-004、005、006、007、008、009、010、011 |
| 疑似(SR) | 0 | — |
| 环境受限(ENV) | 0 | — |
| **合计** | **11** | — |

**最严重 3 条**:
1. `BUG-AUTH-001`（P0）: JWT 签名密钥读裸 `SECRET_KEY` 而非 `ZHILIAN_SECRET_KEY`，生产按规范注入的密钥被忽略、回退硬编码默认密钥，可致令牌伪造。
2. `BUG-AUTH-002`（P1）: 登录固定提交 `nickname='学员用户'`，后端每次登录用其覆盖用户真实昵称，造成资料数据被改写。
3. `BUG-AUTH-003`（P1）: 登录接口 401 被误当作会话过期，触发静默刷新/重定向并吞掉真实登录失败原因。
