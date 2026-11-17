# Implementation Plan — M1: Git分支合流清理与工作区规范治理

## 1. Pre-Start Checklist

- [x] `prd.md` 已完成收敛检查，无未决问题
- [x] `design.md` 已明确分支合流、19 处冲突消解与 `.trellis/**` 权限边界
- [x] `implement.jsonl` 与 `check.jsonl` 已注入真实规范与调研文档条目并通过 `task.py validate`
- [ ] 获得用户对本最终规划摘要的显式确认后执行 `task.py start .trellis/tasks/11-17-m1-git-workspace-governance`

## 2. Ordered Execution Checklist

### Step 1 — 主会话安全快照与本地未跟踪杂物预清理（Main Session）
1. 创建安全备份标签：
   - `git tag -f archive/pre-m1-chore-workspace-configs d223cb5`
   - `git tag -f archive/codex-frontend-vertical-slices 51604a4`
2. 将当前未提交的 `.agent/`、`AGENTS.md`、`.trellis/workflow.md`、`.trellis/.template-hashes.json` 及 `.trellis/tasks/11-17-*` 完整复制备份至会话 `scratch/m1-backup/`。
3. 移除孤儿工作树：`git worktree remove .worktrees/frontend-vertical-slices`（核验 `git worktree list`）。
4. 清理未跟踪本地杂物目录：`%SystemDrive%/`、`backend/.trellis/`、`.pi/`、`.opencode/node_modules/`。

### Step 2 — Swarm 隔离工作树合流与非 `.trellis` 工作区清洁（`git-reconciler`，`XHigh`，`workspace: "share"`）
1. 在 `share` 工作树中基于 `origin/dev`（`10bdd91`，其本身是 `master` `0c301fa` 的快进超集）建立合流基线：
   - 核验 `git merge-base --is-ancestor 0c301fa 10bdd91`。
   - 应用 `5f9fa5f` 中全部 23 个非 `.trellis/**` 业务与测试文件改动（`git checkout 5f9fa5f -- backend miniprogram` 或等价 patch），提交第 1 个干净业务修复提交（不触碰 `.trellis/**`）。
2. 在其上建立第 2 个工作区清洁草稿提交（仅限非 `.trellis/**` 路径）：
   - `git rm -r .opencode`、`git rm -f opencode.json sync_to_host.sh`（若存在 `.claude` 跟踪文件一并移除）；
   - 更新 `.gitignore` 保留 `.pi/`、`.worktrees/`、`delivery_lab5_6/` 忽略项并补充 `.opencode/` 防回流规则；
   - 新建根 `.editorconfig`（UTF-8、LF、final newline、Python 4 空格 / TS&Vue&JSON&YAML 2 空格 / Makefile&Go tab）；
   - 修正 `.gitattributes:23` 中指向不存在 `.trellis/spec/cli/backend/*` 的注释说明。
3. 在 `share` 工作树宿主 `pwsh` 下运行全量质量门禁：
   - `$env:PYTHONIOENCODING='utf-8'; task verify`（或分别运行 `task verify-backend` 与 `task verify-frontend`）。

### Step 3 — Swarm 独立核验（`verifier-m1`，`High`）
1. 对照 `01-git-and-workspace-audit.md` 核验 `git-reconciler` 分支：
   - `10bdd91`（`origin/dev`）为祖先；
   - `5f9fa5f` 除 `.trellis/spec/backend/material-statistics.md` 外的 23 个文件与原提交 `git diff` 零差异；
   - `.claude`、`.opencode`、`opencode.json`、`sync_to_host.sh` 已彻底不存在；
   - `task verify` 真实通过。

### Step 4 — 主会话主干落位、`.trellis/**` 治理与本地分支清退（Main Session）
1. 在主工作区安全暂存/恢复未提交 `.agent/` 与 `.trellis/` 改动后：
   - 将本地 `master` 快进至 `origin/dev`（`10bdd91`），落入包含完整 24 个文件（补齐 `5f9fa5f` 的 `.trellis/spec/backend/material-statistics.md`）的 `fix(profile)` 提交；
   - 从最新本地 `master` 切出并检出 `chore/m1-workspace-governance`，合入 Step 2 的工作区清洁改动及当前 `.agent/`、`AGENTS.md`、`.trellis/workflow.md`（同步修正 `L144` 失效路径说明）。
2. 完成 `.trellis/**` 治理（仅主会话执行）：
   - 清洗 `.trellis/.template-hashes.json`（剔除 `.opencode/**` 与 `__pycache__/*.pyc` 条目）；
   - 编写 `.trellis/spec/guides/git-and-workspace-governance.md` 并更新 `.trellis/spec/guides/index.md`；
   - 归档已落地代码的 5 个历史任务（`09-29-fix-learning-stats`、`09-29-fix-llm-thinking-mode`、`09-29-material-delete-entry`、`09-29-question-bank-page`、`09-29-manual-wrong-mark`），确保当前活跃任务指针保持在 `11-17-m1-git-workspace-governance`。
3. 清理本地旧分支（共 12 个）：
   - 10 个已祖先合入分支：`git branch -d worktree-agent-a2180bf64392d93fc codex/frontend-ui-loop-repair feat/question-bank-tab feat/material-delete-entry feature/ZL-143-lab3-delivery feature/ZL-143-branch-protection-note feature/ZL-143-lab3-screenshots feature/ZL-143-sync-task-status feature/ZL-144-question-bank-autoload feature/ZL-145-record-findings`
   - 2 个已打归档备份标签并完成拆分迁移的旧分支：`git branch -D codex/frontend-vertical-slices chore/workspace-configs`
   - 删除本地残留 `.claude/` 目录（若有未跟踪残留）。
4. 在主工作区运行最终 `task verify` 门禁，输出远端同步参考命令供用户审阅。

## 3. Validation Commands

```powershell
$env:PYTHONIOENCODING='utf-8'
git tag -l "archive/*"
git worktree list
git branch -vv
git status --short
task verify
```

## 4. Risky Files & Rollback Points

- **高关注路径**：`Taskfile.yml`、`.gitignore`、`AGENTS.md`、`.trellis/workflow.md`、`.trellis/.template-hashes.json`、`backend/app/repositories/material.py`（`5f9fa5f` 与 `origin/dev` 交汇点）。
- **回滚点**：
  - 原 `chore/workspace-configs` 完整提交态：`archive/pre-m1-chore-workspace-configs`（`d223cb5`）
  - 原未提交工作区快照：`scratch/m1-backup/`
  - 原 worktree 分支提交态：`archive/codex-frontend-vertical-slices`（`51604a4`）
