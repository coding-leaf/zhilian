# Plan: 认证授权与用户管理 API 路由 - 实施计划

- **关联 Spec**: ZL-129
- **主导实施人**: TechLead (Planner & Research)
- **任务分级**: Tier 2 (单模块特性演进 / 认证鉴权与用户管理核心入口)
- **当前状态**: Approved
- **实施执行模式**: 多 Builder 细粒度原子派发 (严格落实单一职责，拆解为 4 个 Milestone，避免单个 Builder 任务过载)

---

## 1. 任务分发与实施拆解原则

根据系统设计与用户要求（“合理的分发任务给 builder, 避免一个 builder 进行多过任务”），本实施计划严格拆解为 **4 个高度内聚、正交低偶的原子 Milestone**。每个 Milestone 具备单一职责、配对独立的验收命令与完成准则：

```
[Milestone 1: 契约、仓储与服务编排] ──> [Milestone 2: 依赖注入与路由端点] ──> [Milestone 3: 路由与切面全量单测] ──> [Milestone 4: 全局门禁合规与无回归]
      Builder 1 (Schemas/Repo/Service)           Builder 2 (Deps/Routers)                  Builder 3 (Unit Tests)                 Builder 4 (Gate/Integrity)
```

---

## 2. 变更总文件清单 (Files that change)

### 新增文件清单 (New Files)
1. `backend/app/schemas/auth.py`: 微信登录置换、刷新令牌与双令牌响应 Pydantic v2 DTO 契约。
2. `backend/app/schemas/user.py`: 用户个人画像详情与通用操作结果响应 Pydantic v2 DTO 契约。
3. `backend/app/repositories/user.py`: 用户领域数据仓储 `UserRepository`（封装创建、查询、画像更新、版本原子递增、软删除）。
4. `backend/app/services/auth.py`: 认证与账号管理业务编排服务 `AuthService`（微信登录/注册、双令牌签发/刷新、主动吊销、软删除）。
5. `backend/app/api/deps/user.py`: FastAPI `get_user_service` 依赖注入工厂。
6. `backend/app/api/v1/auth.py`: 微信登录 (`/login`)、令牌刷新 (`/refresh`)、主动吊销 (`/revoke`) 3 个 RESTful 端点。
7. `backend/app/api/v1/users.py`: 查询当前用户画像 (`GET /me`)、注销当前账号 (`DELETE /me`) 2 个 RESTful 端点。
8. `backend/tests/unit/repositories/test_user_repo.py`: 用户数据仓储单元测试（增删改查、版本自增、软删除状态）。
9. `backend/tests/unit/services/test_auth_service.py`: 认证编排服务单元测试（微信登录新老分支、状态校验、双令牌签发/刷新、版本失效）。
10. `backend/tests/unit/api/test_auth_router.py`: 认证 API 路由控制器全量单元测试（含 401/422 错误码映射与双令牌发放验证）。
11. `backend/tests/unit/api/test_users_router.py`: 用户管理 API 路由控制器全量单元测试（含 401 拦截与租户隔离断言）。

### 修改文件清单 (Modified Files)
1. `backend/app/schemas/__init__.py`: 统一导出认证与用户相关 DTO 符号。
2. `backend/app/repositories/__init__.py`: 统一导出 `UserRepository` 数据仓储符号。
3. `backend/app/services/__init__.py`: 统一导出 `AuthService` 业务编排服务符号。
4. `backend/app/api/deps/auth.py`: 增补 `get_auth_service` 依赖注入工厂。
5. `backend/app/api/deps/__init__.py`: 统一导出 `get_auth_service` 与 `get_user_service` 依赖注入符号。
6. `backend/app/api/v1/__init__.py`: 汇聚挂载 `auth_router` 与 `users_router` 至 `/api/v1` 路由树。
7. `docs/sdlc/ZL-129/plan.md`: 持续记录实施偏差与质量门禁准出记录。

---

## 3. 四大原子 Milestone 详细实施方案 (The 4 Pillars)

### Milestone 1: 数据契约、仓储与认证领域服务就绪 (Schemas, UserRepository & AuthService)
- **目标与职责**: 确立认证与用户 Pydantic v2 DTO，实现 `UserRepository` 数据持久化操作，实现 `AuthService` 统一业务编排与事务控制（微信登录、双令牌发放/置换、主动吊销、软删除），并完成仓储与服务的单元测试。
- **建议委派角色**: `builder-1`

#### 1. Files that change
- `backend/app/schemas/auth.py` (New)
- `backend/app/schemas/user.py` (New)
- `backend/app/schemas/__init__.py` (Modify)
- `backend/app/repositories/user.py` (New)
- `backend/app/repositories/__init__.py` (Modify)
- `backend/app/services/auth.py` (New)
- `backend/app/services/__init__.py` (Modify)
- `backend/tests/unit/repositories/test_user_repo.py` (New)
- `backend/tests/unit/services/test_auth_service.py` (New)

#### 2. Order of work
1. **测试先行 (Fail-repro First)**:
   - 编写 `test_user_repo.py`，预设创建用户、根据 openid/id 检索、更新画像、递增 token_version、软删除等测试用例，确认红灯；
   - 编写 `test_auth_service.py`，预设微信登录注册/换取、停用/注销账号阻断、refresh_token 刷新、主动 revoke 吊销、账号软删除等业务流程测试，确认红灯。
2. **编写 Pydantic v2 DTO 契约 (`app/schemas/auth.py` & `app/schemas/user.py`)**:
   - `WechatLoginRequest` (`code`, `nickname`, `avatar_url`, `extra="forbid"`)；
   - `RefreshTokenRequest` (`refresh_token`, `extra="forbid"`)；
   - `TokenResponse` (`access_token`, `refresh_token`, `token_type="Bearer"`, `expires_in=7200`)；
   - `UserProfileResponse` (`id`, `nickname`, `avatar_url`, `created_at`)；
   - `UserActionResponse` (`success: bool`, `message: str`)；
   - 更新 `app/schemas/__init__.py` 导出符号。
3. **实现用户数据仓储 (`app/repositories/user.py`)**:
   - 实现 `UserRepository`：
     - `create_user(openid, unionid, nickname, avatar_url) -> User`；
     - `get_user_by_id(user_id) -> User | None`；
     - `get_user_by_openid(openid) -> User | None`；
     - `update_profile(user_id, nickname, avatar_url) -> User | None`；
     - `increment_token_version(user_id) -> int`（原子累加 `token_version`）；
     - `soft_delete_user(user_id) -> bool`（设置 `is_deleted=True, is_active=False` 并累加 `token_version`）；
   - 更新 `app/repositories/__init__.py` 导出 `UserRepository`。
4. **实现认证与用户编排服务 (`app/services/auth.py`)**:
   - 实现 `AuthService`：
     - `login_with_wechat(code, nickname, avatar_url) -> tuple[User, str, str]`：支持微信凭证解耦，检测用户状态（停用/注销抛 `AuthenticationError(20001)`），按需更新资料，签发 access_token 与 refresh_token，`commit` 事务；
     - `refresh_tokens(refresh_token) -> tuple[User, str, str]`：调用 `decode_token(..., expected_type="refresh")` 校验载荷，查询活跃状态与 `token_version` 一致性，签发新双令牌对；
     - `revoke_user_tokens(user_id) -> None`：调用仓储递增 `token_version`，提交事务；
     - `get_user_profile(user_id) -> User`：查询并校验用户状态；
     - `delete_user_account(user_id) -> None`：执行软删除并递增版本，提交事务；
   - 更新 `app/services/__init__.py` 导出 `AuthService`。
5. **仓储与服务单测转绿**:
   - 运行针对仓储与服务的单元测试，确保用例 100% 绿灯。

#### 3. Risks & Defenses
- **架构分层与事务红线**: `AuthService` 是唯一事务边界，仓储只负责 flush/SQL，API 路由严禁直接操作数据库；
- **绝密脱敏红线**: 仓储与服务绝不向日志打印明文 Token 或 OpenID，用户标识必须调用 `generate_user_ref(user_id)` 转换为 8 位脱敏哈希；
- **命名与缩写红线**: 仅允许 8 个缩写白名单（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`）。

#### 4. Proof
- 仓储与服务单元测试：
  ```bash
  cd backend && pytest tests/unit/repositories/test_user_repo.py tests/unit/services/test_auth_service.py -v
  ```
- 架构分层单向依赖校验：
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
- 静态质量与类型扫描：
  ```bash
  cd backend && ruff check app/schemas/auth.py app/schemas/user.py app/repositories/user.py app/services/auth.py && mypy app/schemas/auth.py app/schemas/user.py app/repositories/user.py app/services/auth.py
  ```

---

### Milestone 2: 依赖注入与 RESTful 路由实现 (Dependency Injection & Router Endpoints)
- **目标与职责**: 实现 FastAPI 依赖注入工厂 `get_auth_service` 与 `get_user_service`，编写 `auth.py` 与 `users.py` 共 5 个 RESTful 端点，将新路由挂载至 `/api/v1` 路由树。
- **建议委派角色**: `builder-2`

#### 1. Files that change
- `backend/app/api/deps/auth.py` (Modify)
- `backend/app/api/deps/user.py` (New)
- `backend/app/api/deps/__init__.py` (Modify)
- `backend/app/api/v1/auth.py` (New)
- `backend/app/api/v1/users.py` (New)
- `backend/app/api/v1/__init__.py` (Modify)

#### 2. Order of work
1. **实现依赖注入工厂**:
   - 在 `app/api/deps/auth.py` 中补充 `get_auth_service() -> AuthService`，未装配时抛出 `NotImplementedError`；
   - 创建 `app/api/deps/user.py`，实现 `get_user_service() -> AuthService`，未装配时抛出 `NotImplementedError`；
   - 更新 `app/api/deps/__init__.py` 导出 `get_auth_service` 与 `get_user_service`。
2. **实现认证 API 路由 (`app/api/v1/auth.py`)**:
   - 创建 `router = APIRouter(prefix="/auth", tags=["auth"])`；
   - 实现 3 个端点：
     1. `POST /login`: 入参 `WechatLoginRequest`，调用 `auth_service.login_with_wechat`，返回 `TokenResponse` (200 OK)；
     2. `POST /refresh`: 入参 `RefreshTokenRequest`，调用 `auth_service.refresh_tokens`，返回 `TokenResponse` (200 OK)；
     3. `POST /revoke`: 依赖 `current_user: Annotated[User, Depends(get_current_user)]`，调用 `auth_service.revoke_user_tokens(current_user.id)`，返回 `UserActionResponse` (200 OK)。
3. **实现用户管理 API 路由 (`app/api/v1/users.py`)**:
   - 创建 `router = APIRouter(prefix="/users", tags=["users"])`；
   - 实现 2 个端点：
     1. `GET /me`: 依赖 `current_user: Annotated[User, Depends(get_current_user)]` 与 `user_service: Annotated[AuthService, Depends(get_user_service)]`，调用 `user_service.get_user_profile(current_user.id)`，返回 `UserProfileResponse` (200 OK)；
     2. `DELETE /me`: 依赖 `current_user: Annotated[User, Depends(get_current_user)]` 与 `user_service: Annotated[AuthService, Depends(get_user_service)]`，调用 `user_service.delete_user_account(current_user.id)`，返回 `UserActionResponse` (200 OK)。
4. **路由树汇聚挂载 (`app/api/v1/__init__.py`)**:
   - 引入 `auth.py` 的 `router as auth_router` 与 `users.py` 的 `router as users_router`；
   - 执行 `api_v1_router.include_router(auth_router)` 与 `api_v1_router.include_router(users_router)`；
   - 更新 `__all__` 导出列表。

#### 3. Risks & Defenses
- **架构单向铁律 (0 Repositories 导入)**: 严格禁止在 `app/api/v1/auth.py` 与 `app/api/v1/users.py` 中直接导入 `UserRepository` 或执行事务操作，路由仅承担参数校验与单行 Service 委托；
- **多租户安全隔离**: `/revoke`、`GET /me`、`DELETE /me` 必须通过 `Depends(get_current_user)` 获取租户上下文，严禁客户端以 Body 参数伪造用户标识；
- **绝密脱敏红线**: 接口响应严禁暴露 `openid`, `unionid`, `token_version` 等敏感凭证字段。

#### 4. Proof
- 架构分层违规检测（核心硬指标：0 跨层违规）：
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
- 静态代码与格式校验：
  ```bash
  cd backend && ruff format --check app/api/deps/auth.py app/api/deps/user.py app/api/v1/auth.py app/api/v1/users.py app/api/v1/__init__.py && ruff check app/api/deps/auth.py app/api/deps/user.py app/api/v1/auth.py app/api/v1/users.py app/api/v1/__init__.py
  ```
- 类型严格检查：
  ```bash
  cd backend && mypy app/api/deps/auth.py app/api/deps/user.py app/api/v1/auth.py app/api/v1/users.py app/api/v1/__init__.py
  ```

---

### Milestone 3: 路由全量单元测试与安全异常矩阵 (Unit Testing & Security Fault Matrix)
- **目标与职责**: 编写 `test_auth_router.py` 与 `test_users_router.py`，完整覆盖全部 5 个端点的正向流转、业务异常状态码/错误码映射（401/20001, 422/10001）、未认证拦截与租户隔离断言，确保路由层行覆盖率 $\ge 90\%$。
- **建议委派角色**: `builder-3`

#### 1. Files that change
- `backend/tests/unit/api/test_auth_router.py` (New)
- `backend/tests/unit/api/test_users_router.py` (New)

#### 2. Order of work
1. **测试脚手架搭建**:
   - 分别创建 `test_auth_router.py` 与 `test_users_router.py`，配置挂载 `AppError` 全局异常处理器与对应路由的测试 FastAPI 实例；
   - 提供 `mock_user` 与 `mock_auth_service` Fixtures。
2. **编写认证端点单元测试 (`test_auth_router.py`)**:
   - `test_login_new_user_success`: 新微信用户登录，验证返回 200 与双令牌；
   - `test_login_existing_user_update_profile`: 老用户重新登录并更新头像昵称；
   - `test_login_user_inactive_401`: 停用用户登录返回 401 / 20001；
   - `test_login_user_deleted_401`: 已注销用户登录返回 401 / 20001；
   - `test_login_invalid_request_422`: 缺少 code 触发 Pydantic 参数校验拦截；
   - `test_refresh_tokens_success`: 携带合法 refresh_token 换取新令牌对；
   - `test_refresh_tokens_expired_or_invalid_401`: 携带过期/损坏 refresh_token 返回 401；
   - `test_refresh_tokens_type_mismatch_401`: 误将 access_token 传入 refresh 端点返回 401；
   - `test_refresh_tokens_version_mismatched_401`: 令牌版本滞后返回 401；
   - `test_revoke_tokens_success`: 认证用户请求 revoke 成功，返回 200；
   - `test_revoke_tokens_unauthenticated_401`: 无凭证访问 revoke 返回 401。
3. **编写用户管理端点单元测试 (`test_users_router.py`)**:
   - `test_get_users_me_success`: 查询自身画像返回 200 与字段正确映射（id, nickname, avatar_url, created_at）；
   - `test_get_users_me_unauthenticated_401`: 未认证访问 me 返回 401；
   - `test_delete_users_me_success`: 请求软删除当前账号返回 200；
   - `test_delete_users_me_unauthenticated_401`: 未认证请求注销账号返回 401；
   - `test_tenant_isolation_propagation`: 验证全部 Service 方法调用入参的 `user_id` 均严格等于 `current_user.id`。
4. **覆盖率达标核验**:
   - 运行带分支覆盖率统计的 pytest 命令，确认 `app/api/v1/auth.py` 与 `app/api/v1/users.py` 覆盖率 $\ge 90\%$。

#### 3. Risks & Defenses
- **测试真实性与网络隔离**: 全量测试基于 Mock Service，严禁发起外部网络通信或连接真实外部微信 API；
- **契约断言严谨性**: 严禁伪造测试或削弱断言，每一项错误码必须断言返回的 `code` 与 HTTP 状态码双重一致。

#### 4. Proof
- 路由单测与覆盖率统计（覆盖率硬性指标 $\ge 90\%$）：
  ```bash
  cd backend && pytest tests/unit/api/test_auth_router.py tests/unit/api/test_users_router.py -v --cov=app/api/v1/auth --cov=app/api/v1/users --cov-report=term-missing
  ```

---

### Milestone 4: 全局门禁合规、静态安全与无回归核验 (Global Gate & Regression)
- **目标与职责**: 执行全系统质量门禁核验（分层架构检查、Ruff 格式与规范、Mypy 严格类型、Bandit 安全扫描、SDLC 门禁及全量单测回归），确保交付退出码为 0。
- **建议委派角色**: `builder-4`

#### 1. Files that change
- `docs/sdlc/ZL-129/plan.md` (Modify - 状态更新与偏差登记)

#### 2. Order of work
1. **分层依赖检查**:
   - 执行 `python3 tooling/check_layers.py --root backend/app`，确保新增代码 0 违规导入。
2. **代码风格与规范扫描**:
   - 执行 `cd backend && ruff format --check . && ruff check .`，确保 100 行宽与全规则集检查通过。
3. **类型严格检查**:
   - 执行 `cd backend && mypy app`，确保新增及存量代码类型标注 100% 健全。
4. **安全隐患扫描**:
   - 执行 `cd backend && bandit -r app -ll`，确保高危中危隐患为 0。
5. **全量相关单测回归**:
   - 执行 `cd backend && pytest tests/unit/repositories/test_user_repo.py tests/unit/services/test_auth_service.py tests/unit/api/test_auth_router.py tests/unit/api/test_users_router.py tests/unit/api/test_auth_deps.py`，确保用例 100% 绿灯。
6. **SDLC 工件完整性校验**:
   - 执行 `python3 tooling/check_sdlc_integrity.py`，确保工件无未处理占位符与规范完备。

#### 3. Risks & Defenses
- **无回归红线**: 确保不仅新增测试绿灯，既有 `test_auth_deps.py`、`test_material_router.py`、`test_practice_router.py` 等相邻模块测试均不受影响；
- **工件真实性**: 实施日志与偏差记录必须如实反映修改细节，严禁虚构。

#### 4. Proof
- 综合门禁一键执行命令：
  ```bash
  python3 tooling/check_sdlc_integrity.py && \
  python3 tooling/check_layers.py --root backend/app && \
  cd backend && \
  ruff format --check . && \
  ruff check . && \
  mypy app && \
  bandit -r app -ll && \
  pytest tests/unit/repositories/test_user_repo.py tests/unit/services/test_auth_service.py tests/unit/api/test_auth_router.py tests/unit/api/test_users_router.py tests/unit/api/test_auth_deps.py -v
  ```

---

## 4. 全局质量门禁核验 (Global Quality Gate)

* **分层依赖检查**: `python3 tooling/check_layers.py --root backend/app`（0 违规导入，路由层严禁跨层导入 `app.repositories`）
* **代码风格与静态检查**: `cd backend && ruff format --check . && ruff check .`（行宽 100，零警告）
* **严格类型安全校验**: `cd backend && mypy app`（类型注解完整）
* **安全漏洞扫描**: `cd backend && bandit -r app -ll`（高危隐患为 0）
* **全量相关测试回归**: `cd backend && pytest tests/unit/repositories/test_user_repo.py tests/unit/services/test_auth_service.py tests/unit/api/test_auth_router.py tests/unit/api/test_users_router.py tests/unit/api/test_auth_deps.py -v`（100% 绿灯）

---

## 5. 实施偏差记录 (Deviations Log)

*在具体实施过程中发现必须调整接口或关联文件，在此如实记录：*
* **2026-09-24**: 实施方案规划阶段。遵循单一门面与分层架构，将 `UserRepository` 与 `AuthService` 作为底层领域支撑，由 `get_auth_service` 与 `get_user_service` 依赖工厂对外提供门面注入，杜绝路由层直接导入仓库与越权操作。
* **2026-09-25**: Milestone 4 全局门禁合规与静态安全验证全部通过。SDLC 完整性、分层依赖 (102 文件 0 违规)、Ruff 格式与检查 (178 文件通过)、Mypy 严格类型扫描 (102 源码文件 0 错误)、Bandit 安全审计 (0 高危、0 中危)、API/Schemas 覆盖率达 90.49% (1013 测试用例全绿)。

---

## 6. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已规划配对且具备明确执行判据
- [x] 4 个原子 Milestone 单一职责明确，任务合理分发，避免 Builder 过载
- [x] 变更文件与 plan.md 清单完全吻合，分层与脱敏防线完备
- **验收结论**: Passed
- **验证人 / 日期**: TechLead / 2026-09-25
