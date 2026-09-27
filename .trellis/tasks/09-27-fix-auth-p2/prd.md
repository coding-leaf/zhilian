# 需求规范：AUTH 切片 P2 修复（BUG-AUTH-004 ~ BUG-AUTH-011）

## Goal

修复与清零 AUTH 审计清单中 8 条 P2 缺陷：契约悬空画像更新端点、401 静默刷新内存 Store 未同步、401 重放无界循环防护、本地存储字节阈值口径校准、登录硬编码占位画像残留与回滚、后端注销与吊销服务返回值感知、微信登录异步 offload 保护事件循环、以及 fallback 依赖会话生命周期托管防泄漏。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-AUTH.md`（第 74-161 行）：

| ID | 级别 | 层 | 一句话描述 | 状态判定 |
|---|---|---|---|---|
| BUG-AUTH-004 | P2 | cross-layer | 前端存在 `PUT /api/v1/users/me` 更新画像契约，但后端 users 路由未注册 PUT 处理，触发即 405 | 有效（客观存在） |
| BUG-AUTH-005 | P2 | frontend | 401 静默刷新成功后仅更新本地 storage，未同步 Pinia `userStore.tokens` 内存态 | 有效（客观存在） |
| BUG-AUTH-006 | P2 | frontend | 401 静默刷新后重放原请求无 `isRetry`/最大重试次数限制，极端异常下有无界循环与挂起风险 | 有效（客观存在） |
| BUG-AUTH-007 | P2 | frontend | `MAX_STORAGE_BYTES` 语义为 20KB 字节限制，但校验使用 `serialized.length` 字符数，多字节字符超标穿透 | 有效（客观存在） |
| BUG-AUTH-008 | P2 | frontend | 登录成功后先写入硬编码假画像（`usr_current`），随后非阻塞水合；水合失败后脏数据永久残留 UI | 有效（客观存在） |
| BUG-AUTH-009 | P2 | backend | 吊销与注销端点丢弃 service 返回值，底层未命中软删除/未更新时仍恒定返回 `success=True` | 有效（客观存在） |
| BUG-AUTH-010 | P2 | backend | 微信 `jscode2session` 使用同步 `httpx.get`，被 `async def login` 在主事件循环中直接调用，最长阻塞 10s | 有效（客观存在） |
| BUG-AUTH-011 | P2 | backend | `deps/auth.py` 与 `deps/user.py` 的 fallback 分支直接调用 `container.session_factory()`，未托管关闭导致连接泄漏 | 有效（客观存在） |

---

## Requirements

### 功能要求

1. **AUTH-004 (画像更新端点契约补齐)**:
   - 后端 `backend/app/schemas/user.py` 新增 `UpdateUserProfileRequest`（继承 `BaseModel`，包含可选 `nickname: str | None = None` 与 `avatar_url: str | None = None`，`extra="forbid"`）。
   - 后端 `backend/app/services/auth.py` 补齐 `update_user_profile(user_id, nickname=..., avatar_url=...) -> UserProfileResponse`，并在用户不存在时抛出 `AuthenticationError`。
   - 后端 `backend/app/api/v1/users.py` 注册 `@router.put("/me", response_model=UserProfileResponse)` 路由，调用 service 完成画像更新并返回最新 profile。

2. **AUTH-005 (静默刷新内存与存储状态一致性)**:
   - 前端 `miniprogram/src/utils/request.ts` 提供轻量解耦的 Token 刷新回调订阅通道（如 `setTokenRefreshCallback`），避免 `request.ts` 与 `userStore.ts` 产生循环依赖。
   - 在 Pinia `userStore.ts` 初始化或挂载时注册该回调，静默刷新成功后同步执行 `tokens.value = newTokens`，保持内存态与 `storage` 严格一致。

3. **AUTH-006 (401 静默重试无界循环断路器)**:
   - 前端 `miniprogram/src/types/request.ts`（或 `RequestOptions`）新增附加可选字段 `_retryCount?: number`（内部计数，默认 0）。
   - 在 `miniprogram/src/utils/request.ts` 的 `handle401Error` 重放原请求及队列请求时，将 `_retryCount = (options._retryCount || 0) + 1` 注入选项。
   - 当请求再次进入 401 拦截时，若 `options._retryCount >= 1`（最大重试 1 次），直接短路拒绝进入静默刷新，抛出 `AppError(20001, '登录状态已过期，请重新登录', { status_code: 401 })`，清理凭证并重定向至登录页。

4. **AUTH-007 (存储阈值 UTF-8 真实字节数校验)**:
   - 前端 `miniprogram/src/utils/storage.ts` 改造大小校验逻辑：放弃纯字符串 `.length` 比较，改用 UTF-8 实际字节长度计算（优先使用标准 `new TextEncoder().encode(serialized).length`，在无 TextEncoder 环境兼容回退到编码字节算法）。
   - 确保包含多字节字符（如大量中文字符）时，若 UTF-8 编码实际字节数超过 20KB（20480 字节），严格抛出 `AppError(10001, 'Storage key forbidden')`。

5. **AUTH-008 (登录真源水合与假画像残留防护)**:
   - 前端 `miniprogram/src/pages/auth/login.vue` 移除 `usr_current` 硬编码占位画像设置。
   - 登录凭据写入后，必须显式 `await userStore.hydrateProfile()` 阻塞获取真源画像；
   - 若水合失败或网络异常，清理已写入的凭据与状态，给予用户明确失败提示，防止界面展示不合法的假画像或脱靶用户 ID。

6. **AUTH-009 (服务返回值透传与失败状态感知)**:
   - 后端 `backend/app/api/v1/auth.py:revoke` 接收 `auth_service.revoke_tokens(user_id=current_user.id)` 的布尔返回值，透传至 `UserActionResponse(success=success, message="已成功注销所有登录凭据" if success else "注销凭据失败")`。
   - 后端 `backend/app/api/v1/users.py:delete_current_user_account` 接收 `user_service.delete_account(user_id=current_user.id)` 的布尔返回值，透传至 `UserActionResponse(success=success, message="账号已成功注销" if success else "账号注销失败")`。

7. **AUTH-010 (微信登录 HTTP 置换事件循环保护)**:
   - 后端 `backend/app/api/v1/auth.py` 或 `backend/app/services/auth.py` 中，使用 Starlette / FastAPI 提供的标准 `fastapi.concurrency.run_in_threadpool`（或在异步上下文中使用 `run_in_threadpool` 执行微信凭据换取），防止微信接口最长 10s 的同步 HTTP 请求挂起整个 FastAPI 事件循环。

8. **AUTH-011 (依赖项 Fallback 数据库会话上下文托管)**:
   - 修复 `backend/app/api/deps/auth.py` 与 `backend/app/api/deps/user.py`：在无法获取请求级 session 而进入 container fallback 时，使用 `with container.get_session() as session:` 自动回收连接资源，或使用生成器依赖清理，杜绝未关闭 Session 导致的数据库连接池耗尽。

---

### 约束

1. **契约权威与向后兼容**:
   - 后端 Pydantic 模型权威（`schemas/user.py`、`schemas/auth.py`）。
   - 新增请求/响应字段一律**附加可选**，`extra="forbid"`，默认值维持旧契约兼容。
   - 禁止在 TypeScript 中引入 `any`，严格遵循 `types/storage.ts` 与 `types/auth.ts`。
2. **架构分层与依赖规范**:
   - 严格遵循 `import-linter` 规则，路由层禁止跨层引用仓库，依赖项通过 `app.container` 与服务层装配。
   - 前端网络请求层与 Store 状态机遵循单向数据流与无死循环依赖设计。
3. **测试完整性**:
   - 严格遵循“先红后绿”原则，新增/扩展单元测试与接口集成测试。
   - 保持既有测试全绿，禁止弱化已有断言。

---

### 不在范围内

1. 微信真实开放平台网络连通性 mock 外真实联调（单测环境中继续维持 mock 或 deterministic code 路径）。
2. 用户中心其他未上线页面的重构（死页面清理属于后续清理任务）。
3. AUTH 切片非 P2 级 SMELL 重构（如常量重复等非缺陷项）。

---

## Acceptance Criteria

- [ ] **AC-AUTH-004**: 后端注册 `PUT /api/v1/users/me`；传入合法 `nickname` / `avatar_url` 成功更新用户并返回 200 与新资料；用户不存在返回 401；传入非法字段触发 422。前端 `updateUserProfile` 端到端调用不再 405。
- [ ] **AC-AUTH-005**: 前端模拟 401 静默刷新触发并置换新 token 对后，Pinia `userStore.tokens` 与 `storage.getItem('auth_tokens')` 严格同步更新为新 token，`isAuthenticated` 保持 true。
- [ ] **AC-AUTH-006**: 前端构造模拟连续 401 故障响应时，请求拦截在重试 1 次后主动中断刷新循环，抛出 20001 认证错误并触发登出清理，不再无界循环重发。
- [ ] **AC-AUTH-007**: 存储包含大于 20480 字节（即便字符数 ≤ 20480，如 8000 个中文字符约 24KB）的多字节有效载荷时，`storage.setItem` 确切抛出 `AppError(10001, 'Storage key forbidden')`。
- [ ] **AC-AUTH-008**: 登录页 `login.vue` 成功流程不再写入硬编码 `usr_current` 假画像，水合失败时不展示假数据，并给出错误提示与状态清理。
- [ ] **AC-AUTH-009**: 当 service 返回 `False` 时，`POST /api/v1/auth/revoke` 与 `DELETE /api/v1/users/me` 响应体中的 `success` 为 `false` 且包含失败提示文案；service 返回 `True` 时保持 `success=true`。
- [ ] **AC-AUTH-010**: 微信登录代码置换逻辑通过 `run_in_threadpool` 执行，不阻塞主事件循环异步处理其他请求。
- [ ] **AC-AUTH-011**: `deps/auth.py` 与 `deps/user.py` 的 fallback 路径执行完毕后，内部创建的数据库 session 得到显式关闭，无连接悬挂与泄漏。
- [ ] **AC-GATE-BE**: 后端门禁五项全绿：`uv run ruff format --check .`、`uv run ruff check .`、`uv run mypy app`、`uv run lint-imports`、`uv run pytest tests`。
- [ ] **AC-GATE-FE**: 前端门禁三项全绿：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`。

---

## Notes

- 8 条 P2 缺陷均已通过代码审查确证客观存在，无失效或误报项。
- 完整证据链源自 `.trellis/tasks/archive/2026-09/09-27-read-only-bug-audit/research/slice-AUTH.md`。
