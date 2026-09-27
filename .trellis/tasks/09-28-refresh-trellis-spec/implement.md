# Implement — Refresh Trellis specs against actual codebase

> 执行前状态：`task.py start` 之后才可动笔。本清单为有序 checklist；每完成一项勾选。
> 全程只改 `.trellis/spec/**` 与任务目录，**禁止改产品代码**。

## W0. 基线固化

- [ ] 记录基线提交：`git rev-parse --short HEAD`，写入各 spec front-matter 的「最后核对」。
- [ ] 确认工作区 spec 现状：`git status --short .trellis/spec`（应无未提交的 spec 改动；
      若有，先与用户确认）。
- [ ] 建立审计台账空表：`audit-backend.md`（25 行）、`audit-frontend.md`（16 行）。

## W1. 后端空壳填实（4 份）

对每份：先读对应代码，再写；每小节附锚点。

- [ ] `backend/directory-structure.md` — 依据 `backend/app/**`、`pyproject.toml`、import-linter 分层。
- [ ] `backend/database-guidelines.md` — 依据 `app/models/*`、`migrations/versions/*`、`alembic.ini`、`app/api/deps/db.py`。
- [ ] `backend/error-handling.md` — 依据 `app/core/errors.py`、`app/api/**` 异常映射、`app/cli/errors.py`。
- [ ] `backend/logging-guidelines.md` — 依据 `rg "logger|logging" backend/app` 的真实用法与配置。
- [ ] 每份加入 §3.1 front-matter 块。

## W2. 前端空壳填实（5 份）

- [ ] `frontend/directory-structure.md` — 依据 `miniprogram/src/**`、`pages.json`、`vite.config.ts`。
- [ ] `frontend/component-guidelines.md` — 依据 `src/components/**`、`subpackages/**/components/**`。
- [ ] `frontend/hook-guidelines.md` — 依据 `**/composables/*`。
- [ ] `frontend/state-management.md` — 依据 `src/stores/*`。
- [ ] `frontend/type-safety.md` — 依据 `src/types/*`、`tsconfig.json`、ESLint no-explicit-any。
- [ ] 每份加入 §3.1 front-matter 块；引用 `docs/DESIGN.md` 作为设计参数事实源。

## W3. 后端 quality-guidelines 逐条核对（25 scenario）

对每个 scenario 执行 §4 的 抽取→定位→裁决→回填 流程。

- [ ] 25 个 scenario 全部产出裁决行写入 `audit-backend.md`（无遗漏）。
- [ ] `removed` 项在台账写明原因与替代位置。
- [ ] 保留项补 `#### 代码锚点`。
- [ ] 文档顶部加 front-matter 块。

## W4. 前端 quality-guidelines 逐条核对（16 scenario）

- [ ] 16 个 scenario 全部产出裁决行写入 `audit-frontend.md`。
- [ ] 保留项补 `#### 代码锚点`；`removed` 项写明原因。
- [ ] 文档顶部加 front-matter 块。

## W5. guides 本地化

- [ ] `cross-layer-thinking-guide.md`：删除三段重复块；删除 Trellis 包内部章节；
      改写为 backend ↔ miniprogram 跨层指南（字段名钉死、状态/序列化边界）。
- [ ] `code-reuse-thinking-guide.md`：删除 Trellis 模板注册相关小节；
      以本项目 `composables/`、`utils/`、`stores/` 为例改写。
- [ ] 保留的每处「Real-world example」都换成智练真实案例或删除。

## W6. index 与语言声明

- [ ] `backend/index.md`：列真实文件、覆盖范围、事实源、最后核对日期；删除 “English” 行，改中文声明。
- [ ] `frontend/index.md`：同上。
- [ ] `guides/index.md`：更新两份 guide 的描述与用途。

## W7. 验证（完成判据）

- [ ] 空壳清零：
      `rg -n "To be filled by the team|<To be filled>|To fill" .trellis/spec`
      预期无输出。
- [ ] 重复清零：`rg -n "^## Cross-Platform Template Consistency|^## Mode-Detection Probe Checklist" .trellis/spec/guides` 预期无输出。
- [ ] guides 不引用不存在的 Trellis 路径：
      `rg -n "src/templates|docs-site|@mindfoldhq/trellis" .trellis/spec/guides` 预期无输出。
- [ ] 台账完整：`audit-backend.md` 25 行、`audit-frontend.md` 16 行裁决。
- [ ] 锚点抽查：对每份 spec 随机抽 3 个锚点符号执行 `rg`，全部命中。
- [ ] 变更范围：`git status --short` 仅出现 `.trellis/spec/**` 与任务目录；**无** `backend/app`、`miniprogram/src` 改动。
- [ ] 质量门禁（因未改产品代码，应原样通过）：`task verify`。

## 回滚点

- 每个 W 段完成后是一个可回滚点（独立 `git` 提交粒度）。
- 出错时：`git checkout -- .trellis/spec`（回到基线），保留任务目录与台账重来。

## task.py start 前的复查

- [ ] `prd.md` / `design.md` / `implement.md` 三者一致，无未决问题。
- [ ] `implement.jsonl`、`check.jsonl` 已按 spec/research 事实源curated（非空、无遗留 `_example`）。
- [ ] 用户已对最终规划摘要给出**显式**开始许可。
