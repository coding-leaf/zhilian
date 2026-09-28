# 迁移-模型一致性闸门与后端规范防腐

## Goal

新增离线迁移一致性检查纳入 verify-backend 闸门，防止 ORM 模型与 Alembic 迁移漂移（本次登录 500 的根因）；同步修订 backend spec：补 alembic upgrade head 操作 runbook、沉淀 create_all 测不出漂移的陷阱、去掉会腐化的手抄迁移链与表清单。

## Background

2026-09-29 本地小程序登录 500：`psycopg.errors.UndefinedColumn: column users.avatar_object_key does not exist`。
根因：开发库 `alembic_version` 停在 `0008_question_batch_id`，代码已到 `0009_avatar_object_key`（commit `15a621e`）。
已修复：`uv run alembic upgrade head`，验证为全库逐表逐列漂移比对为空 + `POST /api/v1/auth/login` 返回 200。**本任务不含该故障的修复，只做防腐。**

该漂移没被任何环节拦住，已核实的原因：

1. **测试覆盖不到这个维度**：`tests/integration/test_p0_full_chain_e2e.py:241` 用 `Base.metadata.create_all(engine)` 建表（照模型建，模型有什么建什么）；`tests/unit/models/test_*_migration.py` 是**单条**迁移的 upgrade/downgrade 对称性测试。没有任何一处断言「全链迁移产物 == ORM metadata」。
2. **没有自动化迁移步骤**：无 CI（无 `.github/workflows`）；`deploy/docker-compose.yml` 无迁移步骤；`alembic upgrade` 只出现在 `docs/legacy_sdlc/` 历史文档。
3. **规范写了规矩但没有执行者**：`.trellis/spec/backend/database-guidelines.md:62-70` 已有 `## Migrations` 章节，仍发生了本次漂移；且该章节自身已腐化 —— 第 66 行手抄的迁移链停在 `0008`，第 32 行手抄的表清单同为快照。

## Requirements

### R1 一致性闸门（核心）

- 新增一个**完全离线**的自动化测试，断言「沿 Alembic 迁移链建出的 schema」与 `Base.metadata` 一致。
- 比对粒度：表名集合 + 每张表的列名集合。**不比对**类型、索引、约束（理由见 Constraints）。
- 必须能检出两种漂移：①模型有列而迁移未建该列；②模型有表而迁移未建该表。
- 必须断言迁移链为单一 head（多 head / 断链会让部分迁移永不生效，是同一类故障的另一种成因）。

### R2 门禁接入

- 测试置于 `backend/tests/` 下，由既有 `uv run pytest tests --cov=app --cov-branch --cov-fail-under=80`（即 `task verify-backend`）自动覆盖。
- 不新增门禁命令，不改动 `Taskfile.yml` 与 `AGENTS.md` 中的门禁定义。

### R3 规范防腐（`spec/backend/database-guidelines.md`）

- 补操作 runbook：模型改动后必须执行 `uv run alembic upgrade head`；给出漂移自查方法（比对库内 `alembic_version` 与 `alembic heads`）。
- 移除手抄状态：迁移链清单（第 66 行）与已建表清单（第 32 行）改写为可执行的指路命令，保留「事实源 / 最后核对 / 核对方式」机制。
- 同步更新该文档的「最后核对」时间与 commit、必要时更新 `index.md` 索引行。

### R4 沉淀陷阱知识（`spec/backend/quality-guidelines.md`）

- 沿用既有 `### Scenario:` 格式（Scope/Trigger、Contracts、Wrong vs Correct、Tests Required、代码锚点）新增一条「迁移-模型漂移闸门」。
- 核心沉淀内容：「集成测试用 `create_all`、迁移测试是单条对称性测试，两者都测不出全链漂移」—— 这是不可从代码推导的认知，也是本次故障能发生的直接原因。
- 该 scenario 的 Tests Required 必须指向 R1 新增的测试文件与函数名。

## Constraints

- **测试严禁触碰真实 Postgres。** `migrations/env.py:24-36` 的 `_get_target_db_url()` 优先读 `get_settings()`（`@lru_cache`，读 `.env` 中的真实库 URL）；而 `tests/conftest.py:24` 的网络守卫只拦非环回地址，`127.0.0.1` 被放行。因此测试**不得经由 `env.py` / `alembic.command.upgrade`**，必须在进程内自行回放迁移链。
- **不引入类型比对。** pgvector 列在 SQLite 降级为 `JSON`，UUID 等类型存在方言差异，比类型会产生噪音；表/列集合粒度已精确覆盖目标故障。
- 不修改既有测试（既有迁移测试把 `alembic.op._proxy` 设为模块级全局且不恢复 —— 新测试用 fixture 自行恢复，不回头重构旧测试）。
- 不改动应用代码（`app/**`）与迁移文件本身。

## Acceptance Criteria

- [ ] 新增测试在**干净仓库状态**下通过，且零误报（表与列集合完全一致）。
- [ ] 注入「模型有列、迁移无列」漂移后，该测试**失败**。
- [ ] 注入「模型有表、迁移无表」漂移后，该测试**失败**。
- [ ] 测试运行期间不建立任何到真实数据库的连接（以 URL 断言为 sqlite 内存库 或 「Postgres 不可达时测试仍通过」为准）。
- [ ] `task verify-backend` 全绿：ruff format/check、mypy（strict）、import-linter、pytest（覆盖率 ≥80%）。
- [ ] `database-guidelines.md` 修订完成：runbook 已补、手抄状态清单已移除、「最后核对」已更新。
- [ ] `quality-guidelines.md` 新增 scenario 完成，并与 `database-guidelines.md` 互不矛盾。
- [ ] 规范中每条新增约定都能在真实代码/命令中找到依据（符合 `index.md` 的维护规则）。

## Notes

- **原型已实测通过**（`uv run python -c` 一次性脚本，未落盘）：用 `alembic.script.ScriptDirectory.walk_revisions()` 取真实迁移链 + 进程内 `alembic.op._proxy` 回放（沿用 `tests/unit/models/test_avatar_object_key_migration.py:19-27` 既有模式），在 SQLite 内存库上得到与 `Base.metadata` 完全一致的表与列集合，**零误报**；注入 ghost 列、注入 ghost 表两种漂移均被检出。
- 该原型同时确认 `ScriptDirectory.get_heads() == ['0009_avatar_object_key']`，链完整、单 head，可直接作为 R1 的 head 断言依据。
- 本任务分类为**轻量级**：交付物是一个测试文件 + 两处规范文档修订，技术方案已由原型验证，故 PRD-only，不额外产出 `design.md` / `implement.md`。
- `backend/README.md` 目前是 2 行占位（仅标题 + 一句描述），runbook 落在 spec 而非 README —— 本项目的漂移是 agent 会话产生的，spec 是 agent 动手前会读的文档，泛用性更高。
