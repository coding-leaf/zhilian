# Refresh Trellis specs against actual codebase

## Goal

让 `.trellis/spec/` 成为本项目准确、抗腐坏的事实源：每份 spec 要么与真实的
`backend/`、`miniprogram/` 代码一致，要么被删除。读者（人或 AI）应能相信某条 spec 断言
在当前代码下仍然成立。

## Background（已验证证据）

- `.trellis/spec/` 归本项目所有：spec 文件**不在** `.trellis/.template-hashes.json`
  中（只有各平台 skills 在里面），`trellis update` 不会覆盖它们。改写/删除是安全且持久的。
- 当前内容分三类：
  1. **从未填写的模板空壳**（`To be filled by the team`）：
     `backend/{directory-structure,database-guidelines,error-handling,logging-guidelines}.md`、
     `frontend/{directory-structure,component-guidelines,hook-guidelines,state-management,type-safety}.md`。
  2. **活的项目专属 spec**（由 `docs(spec):` 提交持续维护）：
     `backend/quality-guidelines.md`（845 行，25 个 `### Scenario:` 契约块）、
     `frontend/quality-guidelines.md`（602 行，16 个 `### Scenario:` 契约块）。
  3. **被误植入本仓库的 Trellis 工具文档**：`guides/*.md` 描述的是 Trellis 包本身
     （`src/templates/*/commands/trellis/`、`docs-site/`、`@mindfoldhq/trellis`、`cli_adapter.py`），
     与智练产品无关。`cross-layer-thinking-guide.md` 含**三段逐字重复**（约 131-142 vs 228-239、
     146-165 vs 243-269、202-224 vs 272-292）。
- `backend/index.md`、`frontend/index.md` 的 “Status” 列仍写 `To fill`；
  `guides/index.md` 只列了两份 guide。
- 两个 index 声称 “All documentation should be written in **English**”，但现存
  quality-guidelines 正文、代码注释、`docs/DESIGN.md`、提交信息均为中文——声明与事实不符。
- 真实代码布局：
  - 后端 `backend/app/{api/{deps,v1},cli,core/{algorithms},integrations,models,repositories,schemas,services}`、
    `backend/migrations/versions/*`、`backend/tests/{unit,integration}`。Python 3.12、FastAPI、
    SQLAlchemy async、Alembic、LangGraph、pydantic-settings；门禁用 `uv run`（ruff format/check、
    mypy strict、lint-imports、pytest `--cov-fail-under=80`），见 `backend/pyproject.toml` 与 `Taskfile.yml`。
  - 前端 `miniprogram/src/{api,components,pages,stores,subpackages,types,utils}`；UniApp + Vue 3 +
    Pinia + Wot Design Uni + Vitest；门禁用 `pnpm`（lint、type-check、test:unit）。
  - 额外事实源：`docs/DESIGN.md`（前端设计参数）、`docs/specs_extracted/*.md`（需求规格）。

## Key Decisions

- **D1 范围**：执行**全面逐条核对**（41 个 scenario）+ 填实 9 个空壳 + 本地化 guides + 修正 index。
- **D2 guides**：**本地化重写并保留**——删除重复块与 Trellis 包内部内容，改写为面向
  backend ↔ miniprogram 的跨层契约/代码复用指南。
- **D3 语言**：**以中文为主**的正文；修正两个 index 里与实际不符的 “English” 声明。
- **D4 任务结构**：单个复杂任务。理由：9 个壳文件、41 个 scenario、guides 与 index 共享同一套
  抗腐坏约定与事实源，拆成子任务会导致约定不一致、审计台账割裂。
- **D5 抗腐坏机制**：为每份 spec 引入「事实源 + 最后核对 + 核对命令」的 front-matter，
  并为每个 scenario/断言附**可 grep 的代码锚点**（详见 `design.md`）。

## Requirements

- R1：空壳按真实代码填实（不是理想态），每份都引用仓库中的具体路径/符号：
  后端 `directory-structure`、`database-guidelines`、`error-handling`、`logging-guidelines`；
  前端 `directory-structure`、`component-guidelines`、`hook-guidelines`、`state-management`、`type-safety`。
- R2：核对**全部 41** 个 `quality-guidelines.md` scenario（后端 25 + 前端 16）与当前代码/API
  schema 的一致性。逐条给出裁决：仍成立 / 修正 / 标记或删除过期；不得留未核对项。
- R3：本地化 `guides/*.md`：去掉逐字重复块与 Trellis 包内部章节，仅保留并改写适用于智练
  backend ↔ miniprogram 的指导。
- R4：三个 `index.md` 反映真实文件清单与状态，并落地抗腐坏约定，使后人能判断每份 spec
  的最后核对时间与依据。
- R5：保留现存 quality-guidelines 中仍然成立的每一条事实、`file:line` 锚点与决策，不得静默丢失。

## Acceptance Criteria

- [ ] `.trellis/spec/**/*.md` 中不再出现 `To be filled by the team`、`<To be filled>` 或 `To fill` 状态。
- [ ] 41 个 scenario 全部有裁决记录（仍成立 / 修正 / 删除）及其核对的代码位置；审计台账作为证据保留在任务目录。
- [ ] 每份重写文档中提到的符号/路径都能在核对时刻于仓库中 grep 到。
- [ ] `guides/cross-layer-thinking-guide.md` 无重复章节（同一标题只出现一次），且不引用本仓库不存在的 Trellis 包路径。
- [ ] `backend/index.md`、`frontend/index.md`、`guides/index.md` 列出的文件与其目录实际内容一致。
- [ ] 本任务不修改 `backend/app` 与 `miniprogram/src` 下的产品代码；仅改 `.trellis/spec/**` 与任务目录。
- [ ] 因未改产品代码，前后端质量门禁仍原样通过（`task verify`）。

## Out of Scope

- 修改应用行为或重构产品代码。
- 修复/整理 `docs/specs_extracted/` 与 `docs/legacy_sdlc/`（独立语料库）。
- 重写 `.trellis/scripts/` 下的 Trellis 工具或各平台 skills。

## Open Questions

- 无阻塞项（D1/D2/D3 已定）。
