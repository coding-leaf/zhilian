# 修复 AUTH 切片 P0+P1：JWT 密钥与登录语义

## Goal

修复审计清单中 AUTH 切片的 3 条高优先级缺陷：JWT 密钥必须经强类型 Settings 解析（生产注入不再被忽略）、登录不得覆盖用户真实昵称、登录失败不得被误判为会话过期。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（已归档）`research/slice-AUTH.md`：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-AUTH-001 | P0 | backend | `get_secret_key()` 读裸 `SECRET_KEY`，忽略 `ZHILIAN_SECRET_KEY`，回退硬编码默认密钥 → 生产 JWT 可伪造 |
| BUG-AUTH-002 | P1 | cross-layer | 登录固定提交 `nickname='学员用户'`，后端 `nickname is not None` 即覆盖 → 真实昵称被改写 |
| BUG-AUTH-003 | P1 | cross-layer | 登录 401/20001 被 `request()` 当作会话过期，触发静默刷新/重定向并吞掉真实失败原因 |

## Requirements

### 功能要求
1. **AUTH-001**：`core/security.py` 统一经 `get_settings().secret_key.get_secret_value()` 取密钥（保留显式 `secret_key` 入参优先，供测试注入）。生产环境检测到仍为开发默认密钥时**启动期 fail-fast**。裸 `SECRET_KEY` 不再作为真相源。
2. **AUTH-002**：前端登录不再硬编码昵称；未获取真实微信画像时不提交 `nickname`/`avatar_url`（字段缺省）。后端仅在字段被显式提供时更新画像，且不得用空值覆盖已有非空昵称。
3. **AUTH-003**：`request()` 对匿名端点（`skipAuth`，含 `/auth/login`、`/auth/refresh`）的 401/20001 **不触发**静默刷新与登录重定向，直接抛出后端真实错误码与文案。

### 约束
- 契约权威与规范：`.trellis/spec/backend/quality-guidelines.md` 场景「Secret Resolution Must Go Through Strongly-Typed Settings」。
- 不弱化既有测试；不得用 `any` 或关闭规则。
- 密码学/鉴权改动须有回归测试（先红后绿）。

### 不在范围内
- AUTH 其余 P2（`BUG-AUTH-004…011`）→ 后续 P2 批次。
- 用户画像页 `id: 'usr_current'` 占位（`BUG-AUTH-008`）→ 后续批次。

## Acceptance Criteria

- [ ] **AUTH-001**：新增回归——仅设 `ZHILIAN_SECRET_KEY`、清空 `SECRET_KEY` 时 `get_secret_key()` 等于 `get_settings().secret_key`；修复前红、修复后绿。生产 + 默认密钥 → 启动 fail-fast 断言。既有 `test_security.py` 中依赖裸 `SECRET_KEY` 的用例同步更新为真实契约。
- [ ] **AUTH-002**：回归断言登录载荷不含硬编码昵称；后端在未提供昵称时保留既有昵称（不被覆盖为空或占位）。
- [ ] **AUTH-003**：回归断言匿名请求收到 401/20001 时抛出后端真实 `AppError`，且**不**写入/清除 `auth_tokens`、**不**调用 `redirectToLogin`。
- [ ] 后端门禁全绿：`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest`。
- [ ] 前端门禁全绿：`pnpm run lint`、`type-check`、`test:unit`（若含前端改动；否则确认不退化）。
- [ ] 逐条关闭 `bug-ledger.md` BUG-AUTH-001/002/003。

## Notes

- 父任务：`09-27-fullstack-bug-audit-and-fix`；依赖：无前置子任务。
- 完整证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-AUTH.md`。
