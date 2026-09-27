# Directory Structure

> 后端代码在本项目中的组织方式（以真实目录与配置为准）。

> **事实源**：`backend/app/`、`backend/pyproject.toml`、`backend/alembic.ini`、`Taskfile.yml`
> **最后核对**：2026-09-28 @ ca062a1
> **核对方式**：`rg "packages|layers|source_modules|testpaths|pythonpath" backend/pyproject.toml`

---

## Overview

后端是 Python 3.12 + FastAPI + SQLAlchemy 2.0（async 风格 ORM 使用，实际以同步 `Session` 装配）的单体应用，包名 `app`。
构建与打包由 Hatchling 负责（`[tool.hatch.build.targets.wheel].packages = ["app"]`），依赖安装与命令执行统一走 `uv run`。

分层遵循「五层单向架构依赖契约」（见下文 import-linter 配置），核心原则是**上层可依赖下层，下层不得反向依赖上层**：

```
app.api → app.services → app.repositories → app.models
                    ↘ app.integrations（适配器，仅被 services 层装配）
app.core（基础：配置/异常/安全/纯算法，不依赖任何上层）
```

- 路由 `app.api` 只做 HTTP 协议解析、参数校验、依赖注入与 Service 调用。
- 业务规则与事务边界在 `app.services`。
- 数据访问在 `app.repositories`。
- 声明式 ORM 模型与迁移在 `app.models` / `backend/migrations`。
- 第三方能力（LLM/OCR/Embedding/Search/Storage/Queue/Idempotency）以 Protocol + Factory 形态封装在 `app.integrations`。
- 配置、异常、安全、纯算法在 `app.core`（其中 `app.core.algorithms` 为无 IO 纯函数核）。

---

## Directory Layout

```
backend/
├── alembic.ini                     # Alembic 配置（script_location=migrations）
├── pyproject.toml                  # 依赖、hatch 打包、ruff/mypy/pytest/import-linter 配置
├── app/
│   ├── main.py                     # FastAPI 应用装配、lifespan、全局异常处理器、/health
│   ├── container.py                # AppContainer：引擎/session/Provider/8 大服务工厂
│   ├── api/
│   │   ├── deps/                   # FastAPI 依赖项（auth/container/db/各领域 service 注入）
│   │   └── v1/                     # v1 路由（auth/users/materials/folders/knowledge/questions/practices/grading/diagnosis）
│   ├── cli/                        # Headless CLI（python -m app.cli）
│   │   ├── main.py                 # 参数解析与统一异常→退出码
│   │   ├── errors.py               # CliError 与退出码常量
│   │   ├── context.py / report.py  # CLI 上下文、脱敏输出
│   │   ├── smoke.py                # 端到端 11 阶段闭环
│   │   └── commands/               # 各子命令（auth/db/doctor/material/question/practice/grading）
│   ├── core/
│   │   ├── config.py               # pydantic-settings 强类型配置（ZHILIAN_ 前缀）
│   │   ├── errors.py               # AppError 体系与 5 位错误码
│   │   ├── security.py             # JWT 签发/验签/脱敏纯函数
│   │   └── algorithms/             # 纯算法核（chunking/search/grading/question_quality/...）
│   ├── integrations/               # 第三方适配器（Protocol + Fake + 生产实现 + factory）
│   │   ├── llm/ embedding/ search/ storage/ queue/ idempotency/ ocr/
│   │   └── container.py            # ProviderRegistry
│   ├── models/                     # SQLAlchemy 声明式模型（material/knowledge/question/practice/user/base）
│   ├── repositories/               # 数据访问（每领域一文件）
│   ├── schemas/                    # Pydantic v2 请求/响应契约
│   └── services/                   # 业务编排（auth/material/folder/knowledge/question/practice/grading/diagnosis）
├── migrations/
│   ├── env.py                      # 迁移运行环境（读取 AppSettings，兼容 asyncpg/aiosqlite DSN）
│   └── versions/                   # 0001..0008 迁移脚本
└── tests/
    ├── unit/                       # 单元测试（api/core/integrations/models/repositories/schemas/services/cli）
    └── integration/                # 集成/E2E（p0 全链路、真实基础设施）
```

代码锚点：`backend/app/main.py`、`backend/app/container.py`、`backend/app/api/v1/__init__.py`、`backend/app/integrations/container.py`、`backend/app/core/algorithms/`、`backend/migrations/env.py`。

---

## Module Organization

新增后端能力时的落位约定：

- **新增一个 HTTP 端点**：在 `app/api/v1/<domain>.py` 定义 `APIRouter`，路由内 `Depends` 获取 Service，禁止直接 import 仓储或开事务；服务装配走 `app/api/deps/<domain>.py` 的 `get_<domain>_service`。
- **新增业务规则/事务**：写在 `app/services/<domain>.py`，Service 只依赖 `app.repositories`、`app.core` 与构造注入的 `app.integrations` 适配器。
- **新增数据访问**：写在 `app/repositories/<domain>.py`，只使用 SQLAlchemy 表达式，返回 ORM 实体或标量，不得 import `fastapi`/`app.services`/`app.api`/`app.integrations`。
- **新增表/字段**：先改 `app/models/<domain>.py`，再补 `migrations/versions/NNNN_*.py`，并补对称的 `downgrade()`。
- **新增第三方能力**：在 `app/integrations/<capability>/` 下定义 `protocol.py`（Protocol + 数据模型）、`fake.py`、生产实现、`factory.py`，并在 `app/integrations/container.py` 的 `ProviderRegistry` 注册；Service 通过构造函数接收。
- **新增无 IO 算法**：写在 `app/core/algorithms/<name>.py`，保持纯函数，禁止 import `fastapi`/`sqlalchemy`/`httpx`/`redis`/`boto3`。
- **新增配置项**：改 `app/core/config.py` 的对应 `*Settings` 子模型，环境变量经 `ZHILIAN_` 前缀与 `__` 嵌套解析。

架构边界由 import-linter 强制（`backend/pyproject.toml`）：

- `type = "layers"`：`app.api` → `app.services` → `app.repositories`。
- `forbidden`：`app.repositories` 禁 `fastapi`/`app.integrations`/`app.services`/`app.api`。
- `forbidden`：`app.core.algorithms` 禁 `fastapi`/`sqlalchemy`/`httpx`/`redis`/`boto3` 及上层。
- `forbidden`：`app.integrations` 禁 `app.services`/`app.api`。
- `forbidden`：`app.core` 禁 `app.api`/`app.services`/`app.repositories`/`app.integrations`。

代码锚点：`backend/pyproject.toml::[tool.importlinter.contracts]`、`backend/app/services/material.py::MaterialService`、`backend/app/repositories/material.py::MaterialRepository`、`backend/app/api/deps/material.py::get_material_service`、`backend/app/container.py::AppContainer.create_*_service`。

---

## Naming Conventions

- **Python 包/模块**：小写 snake_case；每领域一文件（`material.py`、`question.py`…），与领域名一致。
- **类名**：PascalCase；Service 以 `Service` 结尾，仓储以 `Repository` 结尾，模型名即业务实体名（`MaterialVersion`），DTO 以 `Request`/`Response`/`DTO` 结尾。
- **环境变量**：`ZHILIAN_` 前缀 + 嵌套 `__`（如 `ZHILIAN_LLM__MODEL`），由 `AppSettings.model_config` 派生。
- **数据库表**：复数 snake_case（`materials`、`material_versions`、`question_quality_checks`）；索引 `ix_<table>_<cols>`、唯一约束 `uq_<table>_<cols>`（见 `backend/app/models/material.py::Material.__table_args__`）。
- **错误码**：5 位数字，前缀即域：`1xxxx` 参数、`2xxxx` 鉴权、`3xxxx` 外部能力、`4xxxx` 算法/门禁、`5xxxx` 内部（见 `app/core/errors.py` 模块 docstring）。
- **迁移文件名**：`NNNN_<slug>.py`，`revision` 与文件名一致，`down_revision` 指向真实 head。

代码锚点：`backend/app/core/config.py::AppSettings.model_config`、`backend/app/models/material.py::Material.__table_args__`、`backend/app/core/errors.py`、`backend/migrations/versions/0008_question_batch_id.py`。

---

## Quality Gates

项目根 `Taskfile.yml` 定义统一门禁；后端命令均需在 `backend/` 目录下以 `uv run` 执行：

```bash
task verify-backend   # ruff format --check . && ruff check . && mypy app && lint-imports && pytest tests --cov=app --cov-branch --cov-fail-under=80
```

单项：
- 格式/静态检查：`uv run ruff format --check .`、`uv run ruff check .`（`select = ["E","F","I","N","UP","B","SIM","S","RUF","ASYNC","C901"]`，`tests/**` 放行 `S101`）。
- 类型：`uv run mypy app`（`strict = true`）。
- 架构：`uv run lint-imports`。
- 测试：`uv run pytest tests`（`testpaths=["tests"]`、`pythonpath=["."]`）。

代码锚点：`Taskfile.yml::verify-backend`、`backend/pyproject.toml::[tool.ruff]`、`backend/pyproject.toml::[tool.mypy]`、`backend/pyproject.toml::[tool.pytest.ini_options]`。
