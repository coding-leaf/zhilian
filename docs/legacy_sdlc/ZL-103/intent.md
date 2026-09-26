# Intent: 用户空间模型、多租户基类与鉴权安全核心

- **任务编号**: ZL-103
- **提出人**: Dev
- **创建时间**: 2026-09-23 19:12
- **初始 Change Tier**: Tier 3
- **当前状态**: Draft / In-Review

---

## 1. 问题与现状背景 (Problem)
在智练自主学习平台中，系统定位于个人化、轻量级智能学习工具，要求严格保障每个学生用户的数据空间独立性与隐私安全（需求规格说明书 FR-59, FR-60, NFR-13, NFR-14）。
当前系统刚完成基础协同基线与资料切分纯函数核（ZL-107），持久化数据模型层与安全鉴权底座尚处于空白阶段：
1. **缺少统一的用户实体数据模型（`users` 表）**：无法持久化存储用户身份（微信 openid、unionid、昵称、头像、账号状态及令牌版本号）；
2. **缺少多租户数据隔离机制与基础设施基类（`TenantModelMixin`）**：后续即将构建的资料表（ZL-104）、知识点与题目表（ZL-105）、练习与答卷表（ZL-106）若无标准统一的多租户字段（`user_id`）及索引约束，极易引发表设计异构、漏加外键或遗漏租户索引；
3. **缺少统一的安全鉴权与令牌核心（`backend/app/core/security.py`）**：缺乏非对称/对称安全的 JWT 双令牌机制（Access Token 2h、Refresh Token 30d 轮换）、缺乏基于 `token_version` 的即时作废与登出注销机制、缺乏用户标识不可逆摘要算法（日志 8 要素脱敏要求）；
4. **缺少接口层归属校验与防水平越权防线**：尚未建立从请求头 Bearer Token 解析用户标识并注入业务上下文的 FastAPI 依赖（`deps/auth.py`），无法防范客户端篡改入参 `user_id` 的水平越权攻击。

若不在当前阶段先确立稳固的租户模型与鉴权核心，后续所有业务表和接口的开发将失去安全与数据隔离基石，带来巨大的跨用户越权与架构返工风险。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [ ] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [x] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **用户空间模型与持久化体系**：
   - 在 `backend/app/models/` 定义 `User` 实体模型（`users` 表），涵盖主键 `id` (UUID)、`openid` (唯一且加索引)、`unionid` (可选索引)、`nickname`、`avatar_url`、`token_version` (整数，默认 1，用于令牌失效与注销)、`is_active`、`is_deleted` (软删除标记) 及标准审计时间戳（`created_at`, `updated_at`）；
   - 提供声明式多租户基类 `TenantModelMixin`，统一定义 `user_id` 外键关联、数据库索引与租户归属属性，作为系统所有多租户业务表的强制基类。
2. **安全鉴权核心计算与令牌管理 (`security.py`)**：
   - 实现高安全性 JWT 双令牌机制：访问令牌（Access Token，有效期 2 小时）与刷新令牌（Refresh Token，有效期 30 天并在刷新时轮换）；
   - 令牌载荷（Payload）仅包含用户标识（`sub`）、令牌类型（`type`）、令牌版本（`token_version`）与过期时间戳（`exp`），严禁包含任何业务数据；
   - 实现令牌版本强一致校验：当用户执行账号注销或登出时，通过更新 `users.token_version` 实现全端历史已签发令牌即时作废；
   - 实现用户脱敏摘要纯函数计算：生成不可逆的前 8 位用户标识哈希值（`user_ref`），供全系统结构化日志安全脱敏使用；
   - 提供凭证安全处理工具函数（密码/敏感摘要哈希校验）。
3. **统一鉴权依赖注入与越权防御体系**：
   - 在 `backend/app/api/deps/auth.py` 中实现 FastAPI 依赖注入项 `get_current_user` / `get_current_user_id`；
   - 强制从 HTTP `Authorization: Bearer <token>` 解析用户标识，接口入参中出现的用户标识一律忽略；
   - 拦截并标准化鉴权异常：未携带 Token、Token 过期、签名非法或版本失效时统一抛出 `AppError`（错误码 `20001`，HTTP 401），响应体不含任何敏感与业务字段；
   - 跨用户资源访问校验失败时统一抛出 `AppError`（错误码 `20002`，HTTP 403）；
   - 编写 100% 拦截的越权负向测试用例套件，确保 `security.py` 行覆盖率 $\ge 95\%$。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - **覆盖率与单测红线**：`backend/app/core/security.py` 行覆盖率必须 $\ge 95\%$；后端全局单测运行时间控制在毫秒级，测试严禁真实联网；纯函数与安全工具严禁使用 Mock 替身打桩内部逻辑；
  - **越权负向测试铁律**：必须包含针对越权访问的负向测试用例（未登录、假 Token、篡改签名、过期 Token、版本失效 Token、篡改请求体 user_id），100% 成功拦截；
  - **结构化日志与绝密脱敏红线**：严格遵守日志 8 要素规范，绝密脱敏红线禁止记录明文用户标识、访问令牌、刷新令牌、密码密钥等敏感信息；日志中仅允许输出 `user_ref`（用户 ID 不可逆摘要前 8 位）；
  - **架构分层与单向依赖**：`app/core/security.py` 严禁导入上层业务模块（`app/services`、`app/api` 等）；`app/repositories` 严禁导入 `fastapi` 与 `app/integrations`；严禁在函数内延迟导入绕过校验；代码必须通过 `python3 tooling/check_layers.py --root backend/app`；
  - **业务异常规范**：统一继承业务异常基类 `AppError`，鉴权问题严格使用 `20xxx` 错误码（`20001` 未登录或登录态失效、`20002` 无权访问该资源），响应体仅含错误码、面向用户的提示文案与请求标识，不泄露堆栈或业务片段；
  - **命名与全英文规范**：代码中标识符全英文，严禁拼音；严格受限于 8 个缩写白名单（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`），Google 风格中文 Docstring。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含微信服务端 API（如 `code2Session`）真实网络通信逻辑（属于后续外部适配层任务，测试统一通过假实现/Stub 注入模拟）；
  - 不包含用户端 HTTP 业务路由实现（`POST /api/v1/auth/login` 与 `POST /api/v1/auth/refresh` 属于 `ZL-126`）；
  - 不包含资料（`materials`）、题目（`questions`）等业务领域表的建模与迁移（分别属于 `ZL-104`、`ZL-105` 等后续任务）；
  - 不实现教务系统对接、第三方开放平台 OAuth2 或复杂多角色 RBAC 权限控制（本系统定位于单人自主学习，永久排除此类复杂架构）。
* **完成判定条件 (Definition of Done)**:
  - `User` 模型与 `TenantModelMixin` 在 `backend/app/models/` 规范定义并通过 mypy 严格类型检查；
  - `backend/app/core/security.py` 完成实现，提供双令牌签发与校验、版本注销检查与 `user_ref` 脱敏摘要；
  - `backend/app/api/deps/auth.py` 提供统一的 FastAPI 鉴权依赖项；
  - 补充全套安全与越权负向测试用例，`security.py` 行覆盖率达到 $\ge 95\%$；
  - 门禁自动化工具链全绿：`ruff format --check .`、`ruff check .`、`mypy app`、`bandit -r app -ll`、`python3 tooling/check_layers.py --root backend/app`、`python3 tooling/check_sdlc_integrity.py` 全部通过，退出码为 0。

## 6. 未决疑问与待探讨点 (Open Questions)
- 1. **主键选型策略**：`users` 表主键与租户 `user_id` 的类型选型：建议统一采用 UUID (UUIDv4) 作为主键类型，相比自增整数能天然阻断 ID 枚举遍历猜测，并降低多端合并与数据迁移冲突。
- 2. **微信 OpenID 与 UnionID 索引设计**：在当前小程序单端形态下，`openid` 必须具有唯一约束 (`unique=True`)；后续若接入多端是否需要同时为可空的 `unionid` 建立独立索引以便未来平滑扩展？建议在设计中为 `unionid` 预留可选字段并增加稀疏/普通索引。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: yezisama / 2026-09-23
