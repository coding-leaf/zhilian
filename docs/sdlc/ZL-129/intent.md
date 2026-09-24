# Intent: 认证授权与用户管理 API 路由

- **任务编号**: ZL-129
- **提出人**: TechLead
- **创建时间**: 2026-09-24 22:30
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft

---

## 1. 问题与现状背景 (Problem)
在先前的阶段（ZL-103、ZL-125~128）中，系统已经建立了基于 `User` 模型、JWT 双令牌签发验证计算核（`app/core/security.py`）以及各业务模块（资料、题目、练习、判题、诊断）的端点鉴权依赖（`Depends(get_current_user)`）。
然而，目前系统尚未提供用户登录认证与账号管理的 HTTP RESTful API（`app/api/v1/auth.py` 与 `app/api/v1/users.py`），缺少持久化用户仓储（`UserRepository`）与认证业务服务（`AuthService`）。小程序客户端无法通过微信凭证登录并获取 JWT 双令牌、无法进行无感静默刷新、无法查询自身画像信息，亦无法执行令牌版本主动吊销与账号注销操作。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **数据持久化与服务编排** (`app/repositories/user.py` & `app/services/auth.py`):
   - `UserRepository`: 提供按 `id` / `openid` 查询用户、新建/更新微信用户信息、递增 `token_version` 实现即时吊销、账号软删除等原子操作；
   - `AuthService`: 编排微信凭据换取身份、JWT 双令牌签发（`access_token` 有效期 2 小时，`refresh_token` 30 天）、令牌无感静默刷新（严格核对版本）、主动吊销所有历史令牌及账号注销。
2. **Pydantic v2 DTO 数据契约** (`app/schemas/auth.py` & `app/schemas/user.py`):
   - 微信登录请求（`WechatLoginRequest`：微信 code、可选 nickname、avatar_url）；
   - 双令牌响应（`TokenResponse`：access_token, refresh_token, token_type, expires_in）；
   - 令牌刷新请求（`RefreshTokenRequest`：refresh_token）；
   - 用户画像响应（`UserProfileResponse`：id, nickname, avatar_url, created_at）；
   - 账号注销与操作结果响应（`UserActionResponse`）。
3. **认证授权与用户 RESTful 路由** (`app/api/v1/auth.py` & `app/api/v1/users.py`):
   - `POST /api/v1/auth/login`: 微信 Code 换取 JWT 双令牌与用户基础信息；
   - `POST /api/v1/auth/refresh`: 使用有效 Refresh Token 换取新 Access Token（防篡改与版本校验）；
   - `POST /api/v1/auth/revoke`: 主动吊销当前用户全端历史有效凭据（递增 `token_version`）；
   - `GET /api/v1/users/me`: 获取当前登录用户的画像与偏好；
   - `DELETE /api/v1/users/me`: 注销当前账号（标记软删除并立即使所有令牌失效）。
4. **统一汇聚与装配** (`app/api/v1/__init__.py`):
   - 挂载 `auth_router` 与 `users_router` 至 `/api/v1`。
5. **门禁与安全质量保证**:
   - `check_layers.py` 自动化检测 0 违规，严禁在路由层导入 `app.repositories`，路由仅做 1 行委托至 Service；
   - 严格落实鉴权与安全红线，未登录统一返回 HTTP 401 与错误码 `20001` (`AuthenticationError`)；
   - 全套单元测试覆盖登录、刷新、版本吊销、注销软删除与越权防护，覆盖率 $\ge 90\%$。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 严格遵守 5 层单向架构，`app/api/v1` 严禁直接导入 `app.repositories` 或调用 ORM 原生事务；
  - 缩写白名单仅限 8 个：`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`；
  - 日志 8 要素结构化且严禁记录敏感凭证与全明文标识；
  - 单元测试运行时间控制在毫秒级，严禁外部真实联网。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含微信开放平台真实网络通信（测试中采用 Fake 适配器或标准 mock 置换）；
  - 不包含前端小程序登录按钮与交互界面（由 ZL-131 承担）。
* **完成判定条件 (Definition of Done)**:
  - `python3 tooling/check_layers.py --root backend/app` 0 违规；
  - `ruff format --check .`、`ruff check .`、`mypy app`、`bandit -r app -ll` 全绿；
  - `backend/app/api/v1/auth.py` 与 `users.py` 路由测试覆盖率 $\ge 90\%$；
  - 全量后端单测 100% 通过且无联网报错。

## 6. 未决疑问与待探讨点 (Open Questions)
- 微信 code2session 交互如何解耦？
  - 方案确认：在 `AuthService` 中保留微信 code 转换协议/钩子，测试环境和默认实现通过确定性生成/Mock 处理，确保单元测试完全物理隔离。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: TechLead / 2026-09-24 22:33
