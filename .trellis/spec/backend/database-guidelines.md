# Database Guidelines

> 本项目的数据库模式与约定（以真实模型、迁移与会话装配为准）。

> **事实源**：`backend/app/models/*.py`、`backend/app/repositories/*.py`、`backend/migrations/versions/*.py`、`backend/migrations/env.py`、`backend/alembic.ini`、`backend/app/api/deps/db.py`、`backend/app/container.py`
> **最后核对**：2026-09-29 @ c1d329d
> **核对方式**：`rg "__tablename__|UniqueConstraint|Index|batch_alter_table" backend/app/models backend/migrations/versions`；`rg -n "isinstance\(result, CursorResult\)" backend/app/repositories`

---

## Overview

- **ORM**：SQLAlchemy 2.0 声明式（`DeclarativeBase` + `Mapped[...] = mapped_column(...)`），基类与混入在 `app/models/base.py`。
- **会话**：同步 `Session`，由 `AppContainer` 的 `sessionmaker` 创建；请求级注入见 `backend/app/api/deps/db.py::get_db_session`。
- **迁移**：Alembic，脚本目录 `migrations`（`alembic.ini` 的 `script_location`），版本文件在 `migrations/versions/`。
- **数据库**：本地默认 SQLite（`alembic.ini` 的 `sqlalchemy.url = sqlite:///./zhilian_dev.db`），生产 PostgreSQL（`DatabaseSettings.db_url`）；向量列在 PostgreSQL 用 pgvector，在 SQLite 自动降级为 `JSON`。
- **多租户**：所有归属用户的表继承 `TenantModelMixin`，强制非空 `user_id` 外键（`users.id`，`ON DELETE CASCADE`）并建索引。

代码锚点：`backend/app/models/base.py::Base`、`backend/app/models/base.py::TimestampMixin`、`backend/app/models/base.py::TenantModelMixin`、`backend/app/api/deps/db.py::get_db_session`、`backend/app/container.py::AppContainer.get_session`。

---

## Model Conventions

- 每张表显式声明 `__tablename__`（复数 snake_case）。
- 主键统一 `id: Mapped[uuid.UUID]`（`postgresql.UUID(as_uuid=True)`）。
- 时间戳经 `TimestampMixin` 提供 `created_at`/`updated_at`（`DateTime(timezone=True)`，UTC）。
- 租户隔离经 `TenantModelMixin` 注入 `user_id`。
- 约束与索引集中写在 `__table_args__`：命名唯一约束用 `uq_<table>_<cols>`，索引用 `ix_<table>_<cols>`。
- `__repr__` 必须脱敏，禁止输出用户作答、切片全文等敏感字段。

已建表清单**以命令为准，不在此手抄** —— 手抄的状态清单会随每次迁移腐化，而迁移是常态操作。查询：

```bash
rg -o '__tablename__ = "(\w+)"' -r '$1' backend/app/models
```

代码锚点：`backend/app/models/material.py::Material.__table_args__`、`backend/app/models/question.py::Question.__table_args__`、`backend/app/models/practice.py::AttemptItem.__table_args__`、`backend/app/models/practice.py::WrongRecord.__repr__`。

---

## Query Patterns

- 一律使用 SQLAlchemy 表达式（`select()`/`where()`/`join()`/`selectinload()`），**禁止**裸 SQL 字符串拼接。
- 查询必须带 `user_id` 租户过滤，杜绝越权横向访问。
- **批量预加载，禁止 N+1**：列表装配关联数据时用 `selectinload`（如列表装配版本用 `selectinload(Material.versions)`），或用一次分组查询批量取计数（`count_*_by_folder_ids`）。
- **过滤下推 SQL**：错题多维过滤（`error_type` 等值、`question_snapshot["question_type"].as_string()`、`material_id` 经 `KnowledgePoint` JOIN）都在 DB 层完成，`list` 与 `count` 共享同一 WHERE；禁止内存 `limit=1000` 截断。
- **批量写**：批量创建只 `add` + `flush()`，由外层统一 `commit()`，以保证跨实体单事务原子（见 quality-guidelines 的 Multi-Knowledge-Point / Course Folder Scope 场景）。
- **条件更新（CAS）读影响行数**：并发条件更新 —— `update(...).where(id, user_id, from_status).values(to_status)` —— 判定「本次调用是否赢得跃迁」时，结果行数必须经 `isinstance(result, CursorResult)` 兜底后再读 `.rowcount`。原因：SQLAlchemy 2.0.54 的 `Session.execute` 重载只有 `TypedReturnsRows[_T] -> Result[_T]` 与 `Executable -> Result[Any]`，`Update`/`Delete` 不是 `TypedReturnsRows` 子类，只能落到后者，静态类型 `Result[Any]` 上**不存在** `rowcount`；而运行时返回的确实 `isinstance(..., CursorResult)` 为真，故兜底不改变行为，只消除类型缺口。版本依据与判别命令见 Common Mistakes。
- 分页统一返回 `(items, total)`，`total` 必须为同过滤条件的真实全量计数。

代码锚点：`backend/app/repositories/material.py::MaterialRepository.list_materials`、`backend/app/repositories/diagnosis.py::DiagnosisRepository.list_wrong_records`、`backend/app/repositories/diagnosis.py::DiagnosisRepository.count_wrong_records`、`backend/app/repositories/folder.py::FolderRepository.count_materials_by_folder_ids`、`backend/app/repositories/question.py::QuestionRepository.batch_create_questions`、`backend/app/repositories/material.py::MaterialRepository.try_transition_version_status`、`backend/app/repositories/practice.py::PracticeRepository.try_transition_status`。

---

## Transactions & Session Lifecycle

- `AppContainer.get_session()` 是事务上下文管理器：正常退出不自动 commit，异常时 `rollback()`，最终始终 `close()`。
- Service 层负责 `self.session.commit()` / `self.session.rollback()`；路由层不得开事务。
- 跨多个子操作的单事务编排：内层传 `defer_commit=True` 仅 `flush()`，**仅由最外层**在全部成功时 `commit()`，任一失败 `rollback()` + re-raise。
- 幂等快照等「旁路写入」失败要降级告警，不得让已成功的主事务返回 5xx。

代码锚点：`backend/app/container.py::AppContainer.get_session`、`backend/app/services/question.py::QuestionService.generate_questions_for_knowledge_points`、`backend/app/services/question.py::QuestionService.generate_questions_for_folder`。

---

## Migrations

- 配置：`backend/alembic.ini`（`script_location = migrations`、`version_locations = migrations/versions`）。
- 运行环境：`backend/migrations/env.py` 经 `app.core.config.get_settings()` 读取 `db_url`，并把 `postgresql+asyncpg://` 归一为 `postgresql+psycopg://`、`sqlite+aiosqlite://` 归一为 `sqlite://`。
- 命名：`NNNN_<slug>.py`，`revision` 与文件同名，`down_revision` 指向真实 head。**迁移链以命令为准，不在此手抄**（手抄链会随下一次迁移立即过期）：`uv run alembic history`。
- **应用迁移（模型变更后必做）**：模型新增表/列之后，必须执行 `uv run alembic upgrade head`。Alembic **不会**在应用启动时自动执行（`app/main.py` 的 lifespan 不跑迁移），未应用即运行时 500 —— 2026-09-29 的登录故障（`psycopg.errors.UndefinedColumn: column users.avatar_object_key does not exist`）就是库停在 `0008`、代码已到 `0009` 造成的。
- **漂移自查**：`uv run alembic current`（库内实际版本）应与 `uv run alembic heads`（代码最新修订）一致；不一致即库落后于代码。
- **一致性闸门**：`tests/unit/models/test_migration_model_consistency.py` 已把「迁移链产物 == `Base.metadata`」变成会失败的测试（表名 + 列名集合），随 `task verify-backend` 自动执行；模型与迁移不一致时该测试失败，无需等运行时 500 才发现。
- **SQLite 兼容**：加列/改约束用 `op.batch_alter_table(...)`；需要重建表时 `recreate="always"`。
- **对称性**：每个 `upgrade()` 必须有可执行的 `downgrade()`；迁移单测断言 `upgrade → downgrade → upgrade` 对称。

代码锚点：`backend/migrations/env.py::_get_target_db_url`、`backend/migrations/versions/0005_create_material_folders.py`、`backend/migrations/versions/0007_folder_active_name_unique.py`、`backend/migrations/versions/0009_avatar_object_key.py`、`backend/tests/unit/models/test_migration_model_consistency.py`。

---

## Common Mistakes

- **`material_id IS NULL` 恒假**：`KnowledgePoint.material_id` 为 NOT NULL，缺省资料时必须走 `list_all_by_user_id` 聚合，不能按 `material_id=None` 过滤。
- **`Commit` 边界错位**：仓储内部私自定义 `commit()` 会破坏外层单事务原子性；批量写只 `add`+`flush()`。
- **N+1**：列表里逐条查版本/计数会产生与页大小成正比的查询数；用 `selectinload` 或批量分组查询。
- **枚举以字面量持久化**：状态值必须取自 `enum.StrEnum` 成员（`PracticeStatus.IN_PROGRESS.value`），不得硬编码字符串。
- **迁移不对称**：只写 `upgrade` 不写 `downgrade`，或 `batch_alter_table` 在 SQLite 下丢失约束。
- **迁移未应用**：加完模型字段却忘了 `uv run alembic upgrade head`（或部署时漏跑）。测试套件用的是 `create_all` 照模型建表，**跑测试全绿也证明不了迁移生效**；这类漂移只在真实库上以 `UndefinedColumn` 运行时 500 暴露。自查见上文「漂移自查」。
- **手抄状态清单**：把迁移链、表清单、版本号手抄进文档，会在下一次迁移时腐化（本文件第 66 行曾手抄迁移链并停在 `0008`）。文档里凡是可以由命令得出的状态，一律写命令而非写结果。
- **绕过租户过滤**：仓储方法缺 `user_id` 条件会横向越权。
- **直接在 `Session.execute()` 结果上取 `.rowcount`**：症状是 mypy strict 报 `[attr-defined] "Result[Any]" has no attribute "rowcount"`，并因属性访问报错后退化为 `Any`、再被 `warn_return_any` 捕获而连带报 `[no-any-return]`。**这不是运行时缺陷** —— 运行时返回对象确为 `CursorResult`，`.rowcount` 真实可用；缺口只在上游类型标注。判别命令：`rg "CursorResult" .venv/Lib/site-packages/sqlalchemy/orm/session.py` —— SQLAlchemy **2.0.38 存在** `execute(statement: UpdateBase) -> CursorResult[Any]` 重载，**2.0.54 已移除**（`Session.execute` 只剩 `TypedReturnsRows[_T] -> Result[_T]` 与 `Executable -> Result[Any]`），所以过去能过门禁的 `.rowcount` 现在会失败。

Wrong / Correct 对照（CAS 跃迁判定，返回「本次调用是否赢得跃迁」）：

```python
# Wrong —— mypy strict 报 attr-defined + no-any-return
result = self.session.execute(stmt)
self.session.flush()
return result.rowcount == 1

# Correct —— 仓库既有写法，兜底后读真实行数
result = self.session.execute(stmt)
self.session.flush()
count = result.rowcount if isinstance(result, CursorResult) else 0
return count == 1
```

注：`.execution_options(synchronize_session="fetch")` **不是**诱因 —— 加不加它，`Session.execute` 的静态类型都是 `Result[Any]`（已用 `reveal_type` 实测）。新增 DML 语句后若门禁报该错误，先按上面对照补兜底，不要改成 `cast()`：`cast()` 只让类型检查闭嘴，运行时毫不知情，一旦返回对象不是 `CursorResult` 就直接抛 `AttributeError`；而 isinstance 兜底在同样情形下回落为 `count = 0`（判定为「未赢得跃迁」），方向安全且与既有站点一致。本仓库运行时该兜底分支不会触发（实测恒为 `CursorResult`）。

- **错题记录的练习归属被「无归属的 upsert」清除**：`upsert_wrong_record` 的更新分支若无条件
  `record.practice_id = practice_id`，手工标记路径（传 `None`）会把判题写下的真实来源
  **静默抹成 NULL** —— 无报错、无信号，数据已损坏。改为**「非 None 才覆盖」**，
  把不变量写在方法自己身上；加 `preserve_scope: bool = False` 开关则依赖每个未来调用方
  记得传它，而漏传的后果恰好是不可见的。
  同理：`wrong_records.practice_id IS NULL` **就是**「手工记录」的定义，
  不要再加一列表达同一件事（两个字段表达同一件事必然漂移）。
- **把「记录来源」塞进「错因归因」枚举**：`ErrorType` 既有四个成员是 FR-55 的四因归因，
  手工标记**没有错因**。新增的 `MANUAL = "manual"` 是**来源标记**，维度不同。
  它满足「枚举必须取自 `StrEnum` 成员」这条约定，但未来做归因分布统计时**必须排除**它。
  （已核查：前端从不渲染 `error_type`，且 `normalize_error_type` 对未知值原样透传，
  故新增取值对现有代码零影响。）

代码锚点：`backend/app/repositories/knowledge.py::KnowledgeRepository.list_all_by_user_id`、`backend/app/repositories/material.py::MaterialRepository.try_transition_version_status`、`backend/app/repositories/practice.py::PracticeRepository.try_transition_status`、`backend/app/repositories/grading.py::GradingRepository.update_final_flag`、`backend/app/repositories/user.py::UserRepository.soft_delete_user`、`backend/app/services/question.py::QuestionService.generate_questions_for_knowledge_points`、`backend/app/models/practice.py::PracticeStatus`、`backend/tests/unit/models/test_practice_migrations.py`。
