# M1: Git分支合流清理与工作区规范治理

## Goal

在不触碰远端 `origin` 且零历史丢失的前提下，彻底解决本地与远端开发分支分叉冲突，按「一分支一职责」将 `origin/dev` 与 `5f9fa5f`（P1-4 学习统计修复）合流至本地 `master` 主干，清理 10 个已合入本地分支、孤儿 worktree、冗余 AI 配置目录及残留杂物，并将单主干 Git 与工作区规范正式沉淀入 `.trellis/spec/guides/`。

## Background & Verified Evidence

依据 `.trellis/tasks/11-17-repo-refactor-git-hygiene/research/01-git-and-workspace-audit.md` 核实：
- **分叉与混提现状**：`master`（`0c301fa`）之后，`origin/dev`（`10bdd91`，`+22/-0`，含 `midterm-baseline-2026-10-04` 标签、`pyjwt 2.15.1`、`BUG-01/02/03`、`diff-cover` 及 9 个新测试）与本地当前分支 `chore/workspace-configs`（`d223cb5`，`+3/-0`）在 `.gitignore`、`.trellis/workspace/lls/*`、`10-03-midterm-*` 等 **19 个路径**上存在重叠改动；且 `chore/workspace-configs` 上的提交 `5f9fa5f` 包含 24 个文件的 `fix(profile)` 前后端业务修复，未推送至远端。
- **未提交变更**：主工作区含 4 个 Antigravity Trellis 升级改动（`M .trellis/.template-hashes.json`、`M .trellis/workflow.md`、`M AGENTS.md`、`?? .agent/`）及本次规划任务目录 `.trellis/tasks/11-17-*`。
- **分支与 Worktree 冗余**：10 个本地分支（`worktree-agent-a2180bf64392d93fc`、`codex/frontend-ui-loop-repair`、`feat/question-bank-tab`、`feat/material-delete-entry` 及 6 个 `feature/ZL-*`）已 100% 祖先合入 `master`；`.worktrees/frontend-vertical-slices` 检出在 `codex/frontend-vertical-slices`（`51604a4`，`+1/-77`）。
- **工作区与历史任务杂物**：根目录存在 `.claude/`（53 跟踪文件）、`.opencode/`（55 跟踪文件 + 3,667 个 `node_modules` 文件）+ `opencode.json`、`.pi/`、`%SystemDrive%/`（Windows 缓存 `.db`）、空目录 `backend/.trellis/`、违背 `AGENTS.md` 的 WSL 脚本 `sync_to_host.sh`；`.gitattributes:23` 与 `.trellis/workflow.md:144` 指向不存在的 `.trellis/spec/cli/backend/*`；缺少 `.editorconfig`；`.trellis/tasks/` 滞留 5 个代码已落地的 `09-29-*` 任务未归档。

## Requirements

- **R1 — 零丢失本地备份打标与孤儿 Worktree 清理**：
  - 在任何分支变更前，为 `codex/frontend-vertical-slices`（`51604a4`）创建本地标签 `archive/codex-frontend-vertical-slices`，为当前 `chore/workspace-configs`（`d223cb5`）创建本地标签 `archive/pre-m1-chore-workspace-configs`。
  - 移除 `.worktrees/frontend-vertical-slices` 工作树。
- **R2 — `master` 主干合流与职责拆分（本地）**：
  - 将 `origin/dev`（`10bdd91`）完整合流至本地 `master`，保留全部 21 个有效提交及安全/缺陷/门禁改进。
  - 将 `5f9fa5f`（`fix(profile)` P1-4 前后端学习统计修复，24 个文件）从原 `chore/workspace-configs` 剥离并干净合入本地 `master`（消除 `chore/*` 混带 `fix` 代码的违规状态）。
- **R3 — 本地冗余分支清退**：
  - 删除全部 10 个已祖先合入 `master` 的本地分支，以及已完成打标备份/拆分迁移的本地 `codex/frontend-vertical-slices` 与 `chore/workspace-configs`。
  - 从合流后的最新本地 `master` 切出单一职责分支 `chore/m1-workspace-governance` 承载工作区与规范治理改动。
- **R4 — AI 配置目录与根目录杂物清洁**：
  - 保留 `.agent/`、`.agents/`、`.codex/`、`AGENTS.md`、`.trellis/`；彻底移除 `.claude/`、`.opencode/`（含 `.opencode/node_modules/`）、`opencode.json` 及本地 `.pi/`。
  - 删除根目录字面量 `%SystemDrive%/`、空目录 `backend/.trellis/` 及 WSL 专用脚本 `sync_to_host.sh`。
  - 新增根 `.editorconfig`（强制 UTF-8 与 `end_of_line = lf`），合并保留 `.gitignore` 中对 `.pi/`、`.worktrees/`、`delivery_lab5_6/` 的忽略规则，修正 `.gitattributes:23` 与 `.trellis/workflow.md:144` 中失效的 `.trellis/spec/cli/backend/*` 引用。
- **R5 — Trellis 元数据清洗与已落地历史任务归档**：
  - 清理 `.trellis/.template-hashes.json` 中已移除的 `.opencode/**` 条目及误收录的 19 个 `.trellis/scripts/common/__pycache__/*.pyc` 条目。
  - 核验并归档代码已落地的历史任务（`09-29-fix-learning-stats`、`09-29-fix-llm-thinking-mode`、`09-29-material-delete-entry`、`09-29-question-bank-page`、`09-29-manual-wrong-mark`）至 `.trellis/tasks/archive/`。
- **R6 — 工作区与 Git 规范落盘及远端清理清单输出**：
  - 新建 `.trellis/spec/guides/git-and-workspace-governance.md` 并在 `.trellis/spec/guides/index.md` 注册索引，明确：单主干 `master`、短期分支命名（`feat|fix|refactor|chore|docs/<slug>`）、一分支一职责、Worktree 与 Antigravity `Swarm` `share` 生命周期及零残留红线。
  - 在任务产物中附上供用户验收后手动/授权执行的远端 `origin` 同步与 8+2 个远端旧分支清理命令清单（本里程碑严禁自行执行 `git push`）。

## Acceptance Criteria

- [ ] **AC1**：`git tag -l "archive/*"` 存在 `archive/codex-frontend-vertical-slices` 与 `archive/pre-m1-chore-workspace-configs`，指向原分支 tip hash。
- [ ] **AC2**：`git worktree list` 仅剩主工作区 `D:/code/Workspace/zhilian` 1 条记录，`.worktrees/frontend-vertical-slices` 已彻底移除。
- [ ] **AC3**：本地 `master` 同时包含 `origin/dev`（`10bdd91`）是其祖先且包含 `5f9fa5f` 的全部 24 个文件业务与测试改动；`git branch` 本地仅保留 `master` 与当前活跃治理分支 `chore/m1-workspace-governance`。
- [ ] **AC4**：仓库根目录不存在 `.claude/`、`.opencode/`、`opencode.json`、`.pi/`、`%SystemDrive%/`、`backend/.trellis/`、`sync_to_host.sh`；存在 `.agent/`、`.agents/`、`.codex/`、`.editorconfig`。
- [ ] **AC5**：`.trellis/.template-hashes.json` 中 `0` 条 `.opencode` 与 `0` 条 `__pycache__` 记录；5 个已落地的 `09-29-*` 任务已迁入 `.trellis/tasks/archive/`。
- [ ] **AC6**：`.trellis/spec/guides/git-and-workspace-governance.md` 已创建并被 `.trellis/spec/guides/index.md` 索引引用。
- [ ] **AC7**：宿主 Windows `pwsh` 执行 `task verify`（`task verify-backend` + `task verify-frontend`）全量通过（后端若遇既有算法墙钟阈值并发波动，单独重跑对应算法测试全部通过）。
- [ ] **AC8**：远端 `origin/*` 引用未发生任何未经授权的推送或删除。

## Out of Scope

- 对 GitHub `origin` 执行 `git push` 或 `git push origin --delete`（留待用户验收本地结果后触发）。
- 修改前后端业务源码逻辑、卸载 `miniprogram/package.json` 依赖或拆分 Service/组件（归属 `M2`、`M3`）。
- 尚未开发的 4 个开放历史规划任务（`09-29-field-test-fix-batch-1`、`09-29-fix-parse-stuck`、`09-29-fix-qgen-feedback`、`09-29-question-bank-tab` 父容器）的业务实现。
