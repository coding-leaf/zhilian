# 技术设计：AUTH 切片 P2 缺陷修复

## 1. 背景与根因分析

### BUG-AUTH-004: 前端画像更新契约悬空（405）
- **根因**: 前端 `miniprogram/src/api/user.ts:34-42` 定义了 `updateUserProfile(payload)` 发起 `PUT /api/v1/users/me`；但后端 `backend/app/api/v1/users.py` 仅注册了 `GET /me` 与 `DELETE /me`。后端仓库层 `UserRepository.update_profile`（`repositories/user.py:86-113`）具备更新逻辑，但上游缺少 Schema、Service 门面和 API 路由，契约悬空。
- **方案**:
  1. 在 `backend/app/schemas/user.py` 定义 `UpdateUserProfileRequest`（包含可选 `nickname: str | None = None` 与 `avatar_url: str | None = None`，`extra="forbid"`）。
  2. 在 `backend/app/services/auth.py` 新增 `update_user_profile(user_id: uuid.UUID, nickname: str | None = None, avatar_url: str | None = None) -> UserProfileResponse`，并在 `UserRepository.update_profile` 成功后提交事务，返回更新后的 `UserProfileResponse`；用户未找到则抛出 `AuthenticationError("用户不存在或已注销")`。
  3. 在 `backend/app/api/v1/users.py` 注册 `@router.put("/me", response_model=UserProfileResponse)` 路由。

### BUG-AUTH-005: 401 静默刷新未同步 Pinia Store 内存态
- **根因**: 在 `miniprogram/src/utils/request.ts:160-175` 中，静默刷新成功后直接调用 `storage.setItem('auth_tokens', newTokens)`，由于避免循环依赖，`request.ts` 没有引入 `userStore.ts`。但 `userStore.ts:16-20` 的 `tokens` ref 并未感知底层刷新，导致内存状态依旧指向旧 token，产生“存储态为新值，内存态为旧值”的分歧。
- **方案**:
  1. 在 `miniprogram/src/utils/request.ts` 导出轻量事件钩子注册方法：
     ```ts
     type TokenRefreshListener = (tokens: TokenPairResponse) => void;
     let tokenRefreshListener: TokenRefreshListener | null = null;
     export function onTokenRefreshed(listener: TokenRefreshListener): void {
       tokenRefreshListener = listener;
     }
     ```
  2. 在 `handle401Error` 成功完成 `storage.setItem('auth_tokens', newTokens)` 后触发 `tokenRefreshListener?.(newTokens)`。
  3. 在 `miniprogram/src/stores/userStore.ts` 内部调用 `onTokenRefreshed((newTokens) => { tokens.value = newTokens; })`，实现无依赖循环的单向响应。

### BUG-AUTH-006: 401 静默重试无界循环与请求挂起风险
- **根因**: `miniprogram/src/utils/request.ts:166` 与 `172` 在刷新 token 成功后直接对原始 `options` 调用 `request<T>(options)` 重放。如果遇到服务端特殊半失效状态（例如刷新接口成功返回新 token，但业务接口对新 token 持续判定 401），重放请求会再次触发 `handle401Error`，陷入刷新-重放-刷新无界死循环，Promise 永久挂起。
- **方案**:
  1. 在 `miniprogram/src/types/request.ts`（或 `RequestOptions`）扩展内部重试计数 `_retryCount?: number`。
  2. 在 `handle401Error` 重放原请求与队列请求时，将 `options` 复制并打标：`const retryOptions = { ...options, _retryCount: (options._retryCount || 0) + 1 };`。
  3. 在 `request.ts:269` 校验 401 时增加短路判定：`if (is401 && !isRefreshUrl && !isAnonymous)` 分支中，如果 `(options._retryCount || 0) >= 1`，则判定为重试失败，直接清理会话（`storage.removeItem('auth_tokens')`）、执行 `redirectToLogin()` 并抛出 `AppError(20001, '登录状态已过期，请重新登录', { status_code: 401 })`，阻止进入死循环。

### BUG-AUTH-007: 本地存储大小校验字符串 length 与字节数口径漂移
- **根因**: `miniprogram/src/utils/storage.ts:11` 定义常量 `MAX_STORAGE_BYTES = 20 * 1024`（20KB 字节限制），但在第 73 行执行 `if (serialized.length > MAX_STORAGE_BYTES)`。JavaScript 字符串 `.length` 统计 UTF-16 code units，对于 UTF-8 多字节编码（如中文每个字 3 字节），8000 个汉字 length 仅 8000，但字节高达 24KB，能够绕过 20KB 限制写入本地存储。
- **方案**:
  1. 在 `storage.ts` 中实现精确计算 UTF-8 字节长度的辅助函数 `calculateUtf8Bytes(str: string): number`：
     - 若运行环境存在 `TextEncoder`，直接使用 `new TextEncoder().encode(str).length`。
     - 若兼容部分无 TextEncoder 的运行时，回退至正则匹配与计算：`unescape(encodeURIComponent(str)).length`。
  2. 将大小判断统一改为：`if (calculateUtf8Bytes(serialized) > MAX_STORAGE_BYTES)`。

### BUG-AUTH-008: 登录页硬编码占位画像及水合失败脏数据残留
- **根因**: `miniprogram/src/pages/auth/login.vue:72-80` 在登录后立即写入占位数据 `{ id: 'usr_current', nickname: '学员用户', ... }`，并执行非阻塞的 `void userStore.hydrateProfile()`。如果网络抖动或接口报错，前端将永远保留 `usr_current` 这个非法 UUID 的伪造画像并在 UI 展示，违背了画像由真实后端水合作为真源的原则。
- **方案**:
  1. 移除 `login.vue` 中 `userStore.setUserProfile({ id: 'usr_current', ... })` 的占位调用。
  2. 登录拿到 token 后，执行 `await userStore.hydrateProfile()`，等待真实用户信息获取完成。
  3. 若 `hydrateProfile()` 抛错或返回空，在 catch 块中清理已设置的 tokens（`userStore.clearTokens()`），并向用户展示“获取用户资料失败，请重新登录”的 Toast 提示，终止进入首页。

### BUG-AUTH-009: 凭据吊销与账号注销端点丢弃 Service 返回值
- **根因**:
  - `backend/app/api/v1/auth.py:92-93`: `auth_service.revoke_tokens(user_id=current_user.id)` 返回 `bool`（是否成功自增 token_version），但端点丢弃了返回值，恒返回 `UserActionResponse(success=True, message="已成功注销所有登录凭据")`。
  - `backend/app/api/v1/users.py:65-66`: `user_service.delete_account(user_id=current_user.id)` 返回 `bool`（软删除是否命中 rowcount > 0），但端点同样丢弃，恒返回 `UserActionResponse(success=True, message="账号已成功注销")`。
- **方案**:
  1. `api/v1/auth.py:revoke`:
     ```python
     success = auth_service.revoke_tokens(user_id=current_user.id)
     message = "已成功注销所有登录凭据" if success else "注销所有登录凭据失败"
     return UserActionResponse(success=success, message=message)
     ```
  2. `api/v1/users.py:delete_current_user_account`:
     ```python
     success = user_service.delete_account(user_id=current_user.id)
     message = "账号已成功注销" if success else "注销账号失败"
     return UserActionResponse(success=success, message=message)
     ```

### BUG-AUTH-010: 同步 httpx 调用阻塞 FastAPI 异步事件循环
- **根因**: `backend/app/services/auth.py:123` 在 `_resolve_wechat_openid` 中使用同步阻塞的 `httpx.get(url, params=params, timeout=10.0)`。然而外层调用链 `backend/app/api/v1/auth.py:30` 是一个 `async def login`。当高并发登录请求到来时，单个最长 10 秒的同步 HTTP 微信请求会完全霸占 Python asyncio 事件循环线程，导致所有其他异步接口处理出现全局延迟挂起。
- **方案**:
  - 在 `fastapi.concurrency` 引入 `run_in_threadpool`。
  - 将 `auth.py:login` 路由中的调用通过 `run_in_threadpool` 执行：
    ```python
    _, token_response = await run_in_threadpool(
        auth_service.login_with_wechat,
        code=request.code,
        nickname=request.nickname,
        avatar_url=request.avatar_url,
    )
    ```
  - 既有 `AuthService.login_with_wechat` 属于同步编排服务（配合同步 SQLAlchemy 会话），通过线程池调度既不破坏服务层同步契约，又能完全释放主事件循环。

### BUG-AUTH-011: 依赖注入 Fallback 分支未关闭 Session 导致连接泄漏
- **根因**: `backend/app/api/deps/auth.py:144, 193` 以及 `backend/app/api/deps/user.py:44` 在无法从常规依赖注入获取 session 时，作为兜底调用了 `container.session_factory()`。但是该 session 从未被调用 `close()`，也没有放在上下文管理器中，导致该连接从连接池借出后永久泄露。
- **方案**:
  1. 在 `deps/auth.py:get_current_user` 中：
     使用 `with container.get_session() as session:` 自动回收连接：
     ```python
     with container.get_session() as session:
         active_auth_svc = container.create_auth_service(session=session)
         user = active_auth_svc.get_user_by_id(user_uuid)
         token_version = payload.get("token_version", 1)
         return validate_user_status(user, token_version)
     ```
  2. 在 `deps/auth.py:get_auth_service` 与 `deps/user.py:get_user_service` 中：
     因为它们是 FastAPI Depends 函数，如果入参未传入 session，生成一个独立 session 返回服务实例会导致生命周期脱管。为此将其签名明确依赖 `session: Annotated[Session, Depends(get_db_session)]`，移除直接 `container.session_factory()` 的未关闭代码；或者确保任何 fallback 生成器均在 `get_session()` 上下文或通过 generator 托管。

---

## 2. 契约设计

### 2.1 后端契约变更（`backend/app/schemas/user.py`）
```python
class UpdateUserProfileRequest(BaseModel):
    """更新用户个人画像请求体契约。"""
    model_config = ConfigDict(extra="forbid")

    nickname: str | None = Field(default=None, max_length=50, description="用户昵称")
    avatar_url: str | None = Field(default=None, max_length=500, description="用户头像 URL")
```

### 2.2 路由端点（`backend/app/api/v1/users.py`）
```python
@router.put(
    "/me",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="更新当前登录用户画像资料",
)
async def update_current_user_profile(
    payload: UpdateUserProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    user_service: Annotated[AuthService, Depends(get_user_service)],
) -> UserProfileResponse:
    ...
```

### 2.3 前端事件钩子契约（`miniprogram/src/utils/request.ts`）
```typescript
export interface RequestOptions {
  url: string;
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  data?: unknown;
  header?: Record<string, string>;
  timeout?: number;
  skipAuth?: boolean;
  _retryCount?: number; // 内部重试防无界循环计数
}

export type TokenRefreshListener = (tokens: TokenPairResponse) => void;
export function setTokenRefreshListener(listener: TokenRefreshListener | null): void;
```

---

## 3. 影响文件清单

### 后端 (backend)
- `backend/app/schemas/user.py`: 新增 `UpdateUserProfileRequest`
- `backend/app/services/auth.py`: 补齐 `update_user_profile` 业务方法
- `backend/app/api/v1/users.py`: 增加 `@router.put("/me")`，改进 `delete_current_user_account` 返回值透传
- `backend/app/api/v1/auth.py`: 改进 `revoke` 返回值透传，使用 `run_in_threadpool` 包装微信登录
- `backend/app/api/deps/auth.py`: 修复 fallback session 泄漏
- `backend/app/api/deps/user.py`: 修复 fallback session 泄漏

### 前端 (miniprogram)
- `miniprogram/src/types/request.ts` 或 `miniprogram/src/utils/request.ts`: 增加 `_retryCount`、`setTokenRefreshListener`、死循环断路器
- `miniprogram/src/stores/userStore.ts`: 订阅 token 刷新并同步内存态
- `miniprogram/src/utils/storage.ts`: 引入 UTF-8 实际字节长度计算与 20KB 真实防御
- `miniprogram/src/pages/auth/login.vue`: 移除硬编码 `usr_current`，改为阻塞水合与异常回滚

### 测试套件 (tests)
- `backend/tests/unit/api/test_users_router.py`: 新增 PUT `/me` 单元测试，补充 DELETE 失败分支测试
- `backend/tests/unit/api/test_auth_router.py`: 补充 revoke 失败分支测试，验证微信登录 async 行为
- `backend/tests/unit/services/test_auth_service.py`: 补充 `update_user_profile` 单元测试
- `backend/tests/unit/api/test_auth_deps.py`: 测试 fallback 分支 session 正确回收
- `miniprogram/tests/unit/utils/request.spec.ts`: 增加 token 刷新回调通知测试、401 连续失败重试 1 次短路断开测试
- `miniprogram/tests/unit/utils/storage.spec.ts`: 增加中文字符串/多字节大载荷（>20KB 字节但字符数少）超限拦截测试
- `miniprogram/tests/unit/stores/userStore.spec.ts`: 测试内存态同步
