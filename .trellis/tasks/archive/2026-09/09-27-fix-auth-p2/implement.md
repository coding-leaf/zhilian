# 执行计划：AUTH 切片 P2 缺陷修复

## 前置
- 任务：`09-27-fix-auth-p2`（父任务：`09-27-fullstack-bug-audit-and-fix`）。
- 需求详见 `prd.md`，架构与接口设计详见 `design.md`。

---

## 执行清单（有序）

### Step 1 — 失败回归用例编写（先红）
- [x] 1.1 后端：在 `tests/unit/api/test_users_router.py` 增加 `PUT /api/v1/users/me` 的测试用例（正常修改、更新部分字段、405/422 校验）。目前路由未实现，执行将直接 405/404（红）。
- [x] 1.2 后端：在 `tests/unit/api/test_auth_router.py` 与 `test_users_router.py` 中增加 service 返回 `False` 时响应体的断言（断言 `success=False`）。目前后端恒返回 `True`（红）。
- [x] 1.3 前端：在 `tests/unit/utils/storage.spec.ts` 增加多字节测试（如包含 8000 个中文字符的 payload），断言其抛出 `AppError(10001, 'Storage key forbidden')`。目前基于 `.length` 校验无法拦截（红）。
- [x] 1.4 前端：在 `tests/unit/utils/request.spec.ts` 增加：
  - 断言静默刷新后调用已注册的 token 监听器；
  - 构造重放请求继续 401 的场景，断言其在重试 1 次后主动中断，不再无限调用刷新（红）。
- [x] 1.5 运行相关单测确认新增断言呈现预期失败（红）。

---

### Step 2 — BUG-AUTH-004、009、010、011 后端实现（变绿）
- [x] 2.1 在 `backend/app/schemas/user.py` 声明 `UpdateUserProfileRequest`。
- [x] 2.2 在 `backend/app/services/auth.py` 补齐 `update_user_profile` 方法，并在 `repositories/user.py:update_profile` 成功后提交事务，返回 `UserProfileResponse`。
- [x] 2.3 在 `backend/app/api/v1/users.py` 注册 `@router.put("/me")`，并在 `delete_current_user_account` 接收并透传 service 返回的布尔状态。
- [x] 2.4 在 `backend/app/api/v1/auth.py` 中：
  - `revoke` 路由接收并透传 `revoke_tokens` 的布尔值；
  - `login` 路由使用 `run_in_threadpool` 包装 `auth_service.login_with_wechat` 调用，避免阻塞主事件循环。
- [x] 2.5 在 `backend/app/api/deps/auth.py` 与 `deps/user.py` 中，将 fallback 分支的 session 创建纳入上下文管理或确保关闭，消除潜在连接池泄漏。
- [x] 2.6 运行后端测试验证 Step 1.1 与 1.2 变绿。

---

### Step 3 — BUG-AUTH-005、006、007、008 前端实现（变绿）
- [x] 3.1 在 `miniprogram/src/utils/storage.ts` 中实现 UTF-8 真实字节数计算函数，替换原有 `serialized.length` 检查。
- [x] 3.2 在 `miniprogram/src/utils/request.ts` 中：
  - 引入 `setTokenRefreshListener` 回调机制并在静默刷新完成后触发通知；
  - 在 `options` 中加入 `_retryCount` 计数控制，限制 401 重放最大 1 次，超出直接清理会话抛出认证错误。
- [x] 3.3 在 `miniprogram/src/stores/userStore.ts` 注册监听器，静默刷新时同步更新 `tokens.value` 内存状态。
- [x] 3.4 在 `miniprogram/src/pages/auth/login.vue` 中移除硬编码占位画像设置，改为 `await userStore.hydrateProfile()` 并在失败时完整清理会话与给予提示。
- [x] 3.5 运行前端测试验证 Step 1.3 与 1.4 变绿。

---

### Step 4 — 全门禁验证与交付
- [x] 4.1 运行后端全门禁：
  - 代码格式与风格检查：`uv run ruff format --check .`、`uv run ruff check .`
  - 强类型检查：`uv run mypy app`
  - 分层与无反向依赖校验：`uv run lint-imports`
  - 全量自动化测试：`uv run pytest tests`
- [x] 4.2 运行前端全门禁：
  - 代码风格检查：`pnpm run lint`
  - TypeScript 类型检查：`pnpm run type-check`
  - 单元测试套件：`pnpm run test:unit`
- [x] 4.3 确认所有 AC 条件达成，准备会话总结。

---

## 验证命令

```bash
# 后端（workdir: backend）
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run lint-imports
uv run pytest tests

# 前端（workdir: miniprogram）
pnpm run lint
pnpm run type-check
pnpm run test:unit
```

---

## 评审门禁
- **Gate A (Red-to-Green)**: 所有 8 项缺陷对应的复现/边界断言先红，实现后全绿。
- **Gate B (Architecture & Quality)**: 零 `any`、不跨层导入、契约 `extra="forbid"`、无内存/连接泄漏。
- **Gate C (Zero Regression)**: 既有测试用例保持 100% 通过率。

---

## 回滚点
- 若画像更新产生未知副作用，移除 `PUT /api/v1/users/me` 路由与对应 schema 即可恢复。
- 若 401 重试计数机制产生意外阻断，可将限制条件放宽或复位为无计数重放。
- 若 UTF-8 字节计算在极端兼容性环境报错，可降级为既有字符串判断并打日志。
