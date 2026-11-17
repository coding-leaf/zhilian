# 全仓逻辑重构清洁与Git工作区规范治理（Parent）

## Goal

通过 `M1 → M2 → M3 → M4` 四个串并结合、逐级过门禁（`task verify`）的里程碑，完成全仓 Git 分叉合流与分支清理、工作区与多端 AI 配置收敛、前后端死代码/死依赖清退与 P0 契约修复、千行级上帝模块与超标页面解耦，以及工程规范与脆弱测试对齐，为后续业务功能重构与迭代提供干净、低耦合的单主干工程基线。

## Background & Confirmed Repository Evidence

四份只读审计与交叉复核报告位于本父任务 `research/` 目录：
- `.trellis/tasks/11-17-repo-refactor-git-hygiene/research/01-git-and-workspace-audit.md`
- `.trellis/tasks/11-17-repo-refactor-git-hygiene/research/02-backend-architecture-audit.md`
- `.trellis/tasks/11-17-repo-refactor-git-hygiene/research/03-frontend-architecture-audit.md`
- `.trellis/tasks/11-17-repo-refactor-git-hygiene/research/04-cross-layer-and-synthesis.md`

核心实证结论：
1. **Git 与工作区（`01`）**：主干 `master`（`0c301fa`）外存在 `origin/dev`（`+22/-0`，含 `pyjwt 2.15.1`、`BUG-01/02/03`、`diff-cover`、`midterm-baseline-2026-10-04`）与本地 `chore/workspace-configs`（`+3/-0`，含未推送的 24 文件业务修复 `5f9fa5f` 及 4 个未提交 Antigravity Trellis 路径），二者在 19 个路径上重叠；另有 10 本地 + 8 远端已合入旧分支、孤儿工作树 `.worktrees/frontend-vertical-slices`（`51604a4`）、6 套并存 AI 目录（`.opencode/node_modules` 含 3,667 文件）、`%SystemDrive%/`、`backend/.trellis/`、WSL 脚本 `sync_to_host.sh` 及 9 个 `09-29-*` 历史任务。
2. **跨层契约与文档（`04`）**：`miniprogram/src/subpackages/material/pages/course/index.vue:73,132-133` 与 `miniprogram/src/types/index.ts:109-150` 误读 `page_number`/`similarity`/`key_phrases`（后端 `backend/app/schemas/knowledge.py:16-78` 实返 `page_index`/`chapter_title`），导致原文切片页码恒显示「第 1 页」；64 个 `/api/v1/*` 路由中含隐藏重复路由 `GET /api/v1/mastery/overview`（`backend/app/api/v1/diagnosis.py:202-208`）及前端零调用包装器 `apiGetDiagnosisReport`（`miniprogram/src/api/index.ts:489-494`）；`apiCreatePractice`（`miniprogram/src/api/index.ts:366-375`）存在多余二次请求；`docs/DESIGN.md`、`README.md` 与 `.trellis/spec/**` 严重滞后。
3. **后端架构与冗余（`02`）**：`backend/pyproject.toml:16,34-36` 将生产依赖 `httpx` 错置入 `dev`；7 个 `backend/app/api/deps/*.py` fallback 未关闭 `session_factory()`；`backend/app/services/knowledge.py:373-388` 异常时二次重跑 LangGraph 且 `question.py:876-881` 绕过 `LLMProtocol.generate_structured`；`GradingService`、`PracticeService`、`MaterialService` 含裸 `select()`/`session.delete()` 与 ORM 动态属性挂载；五大 Service 超千行且 `DiagnosisService.generate_diagnosis_report` 达 417 行 / CC=73；存在 20+ 零业务调用 Repo/Service 别名与 3 个零调用异常类。
4. **前端架构与冗余（`03`）**：`miniprogram/package.json` 含 7 个零引用依赖（`wot-design-uni`、`unocss` 三件套、`prettier` 三件套）；死页面 `miniprogram/src/subpackages/material/pages/upload/index.vue`；11 个无消费 Store 成员与 10+ 死导出；6 个 `.vue` 超 300 行（最高 906 行）、`api/index.ts`（553 行）与 `types/index.ts`（509 行）全站单文件堆砌；`profile/index.vue:89,136` 直调底层 `uploadFile`；384 处裸 Hex 色值与 4 处重复弹窗样式。

## Resolved User Decisions & Constraints

1. **推进策略**：许可全量分四阶段里程碑推进（`M1` → `M2` → `M3` → `M4`），每阶段独立验证落盘。
2. **子代理模型分级策略**：统一使用原生 `Swarm` 按任务复杂度动态绑定模型：
   - **高难任务（`很难`）**：使用 `gemini-4-hydrogen-xhigh`（`Gemini 4 Hydrogen (XHigh)`），用于 19 文件分叉合流、千行级高圈复杂度 Service 拆解、巨型 `.vue` 拆解与核心集成审查；
   - **常规任务（`不难`）**：使用 `gemini-4-hydrogen-high`（`Gemini 4 Hydrogen (High)`），用于死代码/死依赖清理、常规单测补齐、文档更新与常规巡检。
3. **AI 配置目录取舍**：保留 Antigravity + Codex（`.agent/`、`.agents/`、`.codex/` 及 `AGENTS.md`、`.trellis/`），清理 `.claude/`、`.opencode/`（含 3,667 个 `node_modules` 文件与根 `opencode.json`）及 `.pi/`。
4. **Git 远端操作边界**：`M1` 仅在本地完成 `master` 合流、提交拆分及 10 个本地已合入分支/孤儿 worktree 清理，**禁止自动 `git push` 或删除远端 `origin/*` 分支**（仅输出远端同步核对脚本供用户验收后手动或授权执行）。
5. **后端未调用接口策略**：保留 25 个后端已实现的业务扩展接口（供后续功能重构与优化复用），仅清理确认重复的隐藏路由 `GET /api/v1/mastery/overview` 与前端死包装器 `apiGetDiagnosisReport`。

## Milestone Decomposition & Requirements

- **PR-M1（`.trellis/tasks/11-17-m1-git-workspace-governance`）**：本地备份打标、移除孤儿 worktree、将 `origin/dev` 与 `5f9fa5f`（P1-4）干净合流至本地 `master`，在独立 `chore/m1-workspace-governance` 分支落地工作区清洁（清理 `.claude`/`.opencode`/`opencode.json`/`%SystemDrive%`/`backend/.trellis`/`sync_to_host.sh`/`.pi`，补 `.editorconfig`，归档已落地 `09-29-*` 任务，沉淀工作区与 Git 规范至 `.trellis/spec/guides/git-and-workspace-governance.md`），清理全部本地冗余分支。
- **PR-M2（`.trellis/tasks/11-17-m2-dead-code-and-p0-fixes`）**：前后端双轨并行清退死依赖/死页面/零调用符号，修复后端 `httpx` 依赖分类、`api/deps` Session 泄漏、LangGraph 双重调用，修复前端 `course/index.vue` 切片页码 P0 契约 Bug、`profile` 头像上传越层调用与 `POST /practices` 双重请求。
- **PR-M3（`.trellis/tasks/11-17-m3-modularization-and-layering`）**：前后端双轨并行结构解耦——后端裸 SQL 下沉 Repo、显式 DTO 替代 ORM monkey-patch、拆分五大巨型 Service 并下调 Ruff `max-complexity <= 15`；前端按域拆分 `api/` 与 `types/`、拆解 6 个超标 `.vue` 页面、抽离通用轮询/弹窗组件并收敛 SCSS 设计 Token。
- **PR-M4（`.trellis/tasks/11-17-m4-docs-specs-and-test-hardening`）**：对齐重写 `docs/DESIGN.md`、`README.md`、`docs/后续待解决问题.md` 与 `.trellis/spec/{backend,frontend}/*.md`，稳定算法墙钟阈值测试，补齐前端 `reportView.ts` 等核心单测。

## Acceptance Criteria

- [ ] **AC-P1**：四个子里程碑依次完成后，宿主 Windows `pwsh` 下 `task verify`（`task verify-backend` + `task verify-frontend`）全绿通过。
- [ ] **AC-P2**：本地分支遵循单主干 `master` + 单一职责短期分支规范，零孤儿 worktree、零未备份丢失提交、未经额外授权零远端破坏操作。
- [ ] **AC-P3**：所有已确认 P0/P1 缺陷、死依赖、死页面、越层查询与巨型模块耦合按各里程碑验收标准消除，`.trellis/spec/**` 与真实代码一致。

## Out of Scope

- 变更小程序或后端现有对外业务产品需求（后续功能级优化在本重构基线完成后另建任务推进）。
- 下线那 25 个已实现但当前小程序尚未接入的后端扩展路由。
- 未经用户验收后二次明确指令前，对 GitHub `origin` 执行 `git push` 或远端分支删除。
