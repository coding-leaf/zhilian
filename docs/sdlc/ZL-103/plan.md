# Plan: 用户空间模型、多租户基类与鉴权安全核心 - 实施计划

- **关联 Spec**: ZL-103
- **实施执行人 / Agent**: Dev
- **当前状态**: In-Execution

---

## 1. 变更文件清单 (Files that change)

### 生产源码文件 (Production Code)
* `backend/app/core/errors.py` (New): 统一业务异常基类 `AppError`，派生 `AuthenticationError` (20001) 与 `PermissionDeniedError` (20002)。
* `backend/app/models/base.py` (New): SQLAlchemy 2.0 `DeclarativeBase` 基类 `Base`、`TimestampMixin`（UTC 审计）与 `TenantModelMixin`（强制级联 user_id 外键与索引）。
* `backend/app/models/user.py` (New): `User` 用户空间核心实体模型，映射 `users` 表，集成 OpenID、版本控制与状态标记。
* `backend/app/models/__init__.py` (New): 导出持久化核心实体与混入基类。
* `backend/app/core/security.py` (New): 纯函数安全计算核，负责 JWT 双令牌签发与验签、版本核对、用户摘要不可逆脱敏。
* `backend/app/api/deps/auth.py` (New): FastAPI 鉴权与租户上下文提取依赖注入，严格遵循架构分层隔离。
* `backend/app/api/deps/__init__.py` (New): 鉴权依赖导出模块。
* `backend/app/api/__init__.py` (New): 路由与接入层初始化标识。

### 自动化测试与工程辅助文件 (Tests & Tooling)
* `backend/tests/conftest.py` (New): 网络阻断与测试脚手架配置，阻断单元测试真实联网。
* `backend/tests/unit/core/test_security.py` (New): 纯函数安全与双令牌单测（覆盖签发、解码、版本校验、不可逆脱敏）。
* `backend/tests/unit/models/test_user.py` (New): User 实体模型与 TenantModelMixin 声明式多租户字段约束单测。
* `backend/tests/unit/api/test_auth_deps.py` (New): 覆盖 AUTH-NEG-01 ~ AUTH-NEG-10 的 10 维越权负向拦截矩阵与租户隔离测试。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Step 1: 统一业务异常体系与纯函数安全核实现 (Fail-repro First & Core Implementation)
* **操作目标**: 建立 `backend/app/core/errors.py` 业务异常基类与 5 位错误码体系，实现 `backend/app/core/security.py` 纯函数 JWT 双令牌签发/验签与 8 位脱敏摘要，编写单元测试。
* **涉及文件**:
  - `backend/app/core/errors.py`
  - `backend/app/core/security.py`
  - `backend/tests/unit/core/test_security.py`
* **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/core/test_security.py -v --cov=app.core.security --cov-report=term-missing
  ```
* **预期判据**: 签发、解密、篡改签名、令牌过期、非法载荷与不可逆脱敏摘要测试全部通过，行覆盖率达到 95% 以上。

### Step 2: SQLAlchemy 2.0 租户混入与用户空间实体模型
* **操作目标**: 实现 `backend/app/models/base.py` 中的 `Base`, `TimestampMixin`, `TenantModelMixin`，以及 `backend/app/models/user.py` 中的 `User` 实体，验证字段约束、主键默认 UUIDv4、级联删除与外键索引声明。
* **涉及文件**:
  - `backend/app/models/base.py`
  - `backend/app/models/user.py`
  - `backend/app/models/__init__.py`
  - `backend/tests/unit/models/test_user.py`
* **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/models/test_user.py -v
  ```
* **预期判据**: 内存数据库正确建表，User 实体默认字段（token_version=1, is_active=True）及 TenantModelMixin 外键映射测试 100% 绿灯。

### Step 3: FastAPI 鉴权依赖注入与 10 维越权负向拦截矩阵
* **操作目标**: 实现 `backend/app/api/deps/auth.py`，提供 `get_current_token_payload` 与 `get_current_user_id` 依赖；在 `backend/tests/unit/api/test_auth_deps.py` 中完整覆盖 AUTH-NEG-01 至 AUTH-NEG-10 的全部拦截场景与水平防越权判定。
* **涉及文件**:
  - `backend/app/api/deps/auth.py`
  - `backend/app/api/deps/__init__.py`
  - `backend/app/api/__init__.py`
  - `backend/tests/unit/api/test_auth_deps.py`
* **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/api/test_auth_deps.py -v
  ```
* **预期判据**: 10 维越权负向拦截测试全部变绿，无 Header、伪造签名、过期令牌、类型混淆、版本吊销、停用账户及篡改 user_id 场景 100% 拦截并返回 401/403。

### Step 4: 架构分层校验与全局门禁闭环
* **操作目标**: 执行单向分层依赖检查，确保 `app/api` 零跨层导入 `app.repositories`；运行代码规范与类型全检。
* **涉及文件**: 全量新增与修改源码文件。
* **局部验证命令**:
  ```bash
  python3 tooling/check_layers.py --root backend/app && \
  cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
  ```
* **预期判据**: 分层检查 0 违规导入，Ruff 与 Mypy 严格检查零警告通过。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**: `cd backend && uv run ruff check . && uv run ruff format --check .` 检查行宽 100 及代码质量。
* **类型与契约安全校验**: `cd backend && uv run mypy app tests` 严格类型检查，无 Any 泄漏与缺失类型标注。
* **分层依赖检查**: `python3 tooling/check_layers.py --root backend/app` 校验无非法跨层导入。
* **全量相关测试回归**: `cd backend && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80` 全量单测与覆盖率门禁。
* **核验结果**: 待执行全局自动化校验。

---

## 4. 实施偏差记录 (Deviations Log)
* 架构与实现完全遵守 `spec.md` 技术契约，无架构破坏性偏差。
* 为支持自动化测试在无真实数据库情况下严密验证租户实体与外键混入，模型测试采用 SQLite 内存引擎，验证 `postgresql.UUID(as_uuid=True)` 的跨平台兼容性。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: yezisama / 2026-09-23
