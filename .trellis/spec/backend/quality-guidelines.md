# Quality Guidelines

> Code quality standards and verification baseline for backend development.

---

## Overview

Backend quality standards are enforced via automated CI gates, linting rules, type checking, architectural boundary checks, and automated tests.
All backend commands must be run within the `backend/` directory using `uv run`.

### Quality Gate Commands

```bash
cd backend
uv run ruff format --check .    # Code formatting check
uv run ruff check .             # Ruff linter (PEP 8, security, complexity, async)
uv run mypy app                 # Strict type checking on application code
uv run lint-imports             # Architecture dependency boundary verification
uv run pytest tests             # Full unit & integration test suite
```

---

## Forbidden Patterns

- **Architectural Boundary Violations (Enforced by import-linter)**:
  - Repositories (`app.repositories`) MUST NOT import `fastapi`, `app.integrations`, `app.services`, or `app.api`.
  - Core algorithms (`app.core.algorithms`) MUST remain pure functions and MUST NOT import `fastapi`, `sqlalchemy`, `httpx`, `redis`, `boto3`, or upper application layers.
  - Integrations (`app.integrations`) MUST NOT import services (`app.services`) or routes (`app.api`).
  - Core base (`app.core`) MUST NOT import upper application layers (`app.api`, `app.services`, `app.repositories`, `app.integrations`).
- **Unsafe Code & Secrets**:
  - Never hardcode API keys, secrets, or sensitive tokens (flagged by Ruff `S` rules).
  - Never use raw SQL string concatenation; always use parameterized SQLAlchemy queries or ORM expressions.
- **Untyped Public APIs**:
  - Missing type annotations on function parameters or return values in `app/` are forbidden (enforced by Mypy).

---

## Required Patterns

- **Dependency Injection**: Services and repositories should receive their dependencies via constructor injection (AppContainer / ProviderRegistry).
- **Explicit Type Hints**: All functions, methods, and dataclasses/pydantic models must have full type annotations (`def func(param: Type) -> ReturnType:`).
- **Layered Clean Architecture**:
  - `app.api`: Route handling, request validation, HTTP status codes, dependency wiring.
  - `app.services`: Business logic, domain rules, transactions.
  - `app.repositories`: Data access, ORM queries, persistence abstraction.
  - `app.models`: Declarative SQLAlchemy models and Alembic migrations.
  - `app.integrations`: Third-party providers (LLM, OCR, Storage) implementing domain protocols.
  - `app.core`: Configuration, exceptions, pure algorithms, utilities.

---

## Testing Requirements

- **Test Framework**: Pytest with `pytest-asyncio` for async tests.
- **Test Locations**: All tests live under `backend/tests/` (`unit/`, `integration/`, etc.).
- **Coverage & Pass Rate**: 100% test pass rate required. No regressions allowed.
- **Isolation**: Unit tests must use mock adapters, in-memory SQLite, or fake providers to avoid relying on external live services.

---

## Architectural Contracts & Cross-Layer Patterns

### Scenario: Material Parsing Retry & Idempotent Re-queueing

#### 1. Scope / Trigger
- 学习资料解析中断或失败后，前端发起单资料就地重试，或重复上传同哈希失败文件。

#### 2. Signatures
- API: `POST /api/v1/materials/{id}/retry` -> `MaterialDetailResponse` (HTTP 200)
- Service: `MaterialService.retry_material_pipeline(material_id: uuid.UUID, user_id: uuid.UUID) -> MaterialVersion`

#### 3. Contracts
- 校验租户归属（必须匹配 `user_id`，杜绝越权）。
- 将最新版本 `parse_status` 重置为 `QUEUED`，同时必须显式将 `error_message` 和 `failed_stage` 清空为 `None`。
- 将资料主实体 `status` 重置为 `PENDING`。
- 异步重新提交后台解析任务。

#### 4. Wrong vs Correct
##### Wrong
```python
# 错误做法：仅重置 parse_status，遗留历史 error_message 和 failed_stage，导致前端误判仍处于失败
version.parse_status = ParseStatus.QUEUED.value
material.status = MaterialStatus.PENDING.value
```
##### Correct
```python
# 正确做法：彻底清理错误信息与失败阶段，重置为排队解析
version.parse_status = ParseStatus.QUEUED.value
version.error_message = None
version.failed_stage = None
material.status = MaterialStatus.PENDING.value
```

---

### Scenario: Dual-Mode Auth & Deterministic Development OpenID

#### 1. Scope / Trigger
- 小程序登录鉴权支持本地开发联调与线上真实环境无缝切换，避免生成临时假账号分裂数据。

#### 2. Contracts
- 若传入固定 `dev_code`，强制解析为确定性 OpenID `wx_dev_deterministic_user`。
- 若传入 `dev_` 或 `mock_` 前缀，强制解析为 `wx_dev_{code}`。
- 前端在授权失败时，严禁向本地 Store 写入任意未验证或伪造的 Token（如 `mock_access_token_*`），避免 401 拦截器死锁。

---

### Scenario: LangGraph Schema-as-Tool Calling Pipeline

#### 1. Scope / Trigger
- LLM 结构化抽取（知识考点抽取、题目生成等）强制采用原生 OpenAPI Function Calling 模式。

#### 2. Contracts
- 模型选项通过 `LLMOptions(tools=[...], tool_choice={"type": "function", ...})` 透传。
- 状态图节点 `validate_output_node` 优先从 `raw_response.tool_calls` 提取入参反序列化，仅在未命中工具调用时才作为纯文本降级处理。

