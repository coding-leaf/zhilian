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

## Code Review Checklist

1. Does `uv run ruff check .` pass without warnings or errors?
2. Does `uv run ruff format --check .` indicate zero formatting discrepancies?
3. Does `uv run mypy app` pass with zero type errors?
4. Does `uv run lint-imports` satisfy all architectural contracts?
5. Do all tests pass via `uv run pytest tests`?
6. Are any newly created temporary files or sqlite artifacts properly ignored by `.gitignore`?
