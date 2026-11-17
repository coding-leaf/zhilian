# Git 分支与工作区治理指南

> **用途**：在切分支、开并发子代理（Swarm / Worktree）与收尾提交前快速核对，防止多主干分叉、`chore/*` 混带业务代码及多平台配置泛滥复发。

---

## 1. 单主干与短期分支规范（Single-Trunk Flow）

- **唯一长期主干**：`master` 是本仓库**唯一**长期受保护主干（CI `.github/workflows/verify.yml` 以 `master` 为准；历史 `dev` 分支已退役，不再新建长期 `dev`/`develop` 分支）。
- **短期任务分支命名**：一律从最新 `master` 切出，格式为 `<type>/<scope-or-slug>`：
  - `feat/<slug>`：新业务功能
  - `fix/<slug>`：缺陷修复
  - `refactor/<slug>`：不改变外部产品语义的结构重构与清理
  - `chore/<slug>`：构建、依赖、工作区配置、门禁脚本调整
  - `docs/<slug>`：纯文档或 `.trellis/spec/` 规范修订
- **一分支一职责红线（One-Branch-One-Purpose）**：
  - 严禁在 `chore/*` 或 `docs/*` 分支上混入 `backend/app/**` 或 `miniprogram/src/**` 的功能/修复提交。
  - 分支合入 `master` 后立即删除本地与远端同名短期分支，禁止长期滞留已合入分支。

---

## 2. Worktree 与 Antigravity Swarm 隔离生命周期

1. **手动 Git Worktree 规范**：
   - 若手动创建 worktree，统一放置在 `.worktrees/<slug>/`（已被 `.gitignore` 忽略）。
   - 任务合入或放弃前必须执行 `git worktree remove`（若放弃未合入实验，先打 `archive/<slug>` 本地备份标签再删分支）。
2. **原生 `Swarm` 并发工作树（`workspace: "share"`）铁律**：
   - 多作者并行修改代码时必须使用 `workspace: "share"`，只读调研与独立 Verifier 使用默认的 `inherit`。
   - **子代理禁区**：任何 Swarm Worker / Subagent **严禁修改 `.trellis/**`**，严禁执行 `git push` 或操作远端引用；`.trellis/**` 任务状态与规范仅由主会话维护。
   - **先落盘后销毁**：主会话调用 `swarm{action: "kill"}` 前，必须先将已通过门禁验证的提交/差异合入主工作区（`kill` 会永久删除对应 `share` 工作树）。
   - **归档零残留检查**：执行 `/trellis-finish-work` 前，`git worktree list` 必须仅剩主工作区 1 条记录，且本地不存在任何 `swarm-*` 或 `worktree-agent-*` 残留分支。

---

## 3. 工作区目录与跨平台编码契约

- **受控 AI 平台目录白名单**：仓库根目录仅保留 `.agent/`（Antigravity）、`.agents/` + `.codex/`（Codex）、`.trellis/` 与 `AGENTS.md`。禁止提交未使用的第三方 AI 目录（如 `.claude/`、`.opencode/`、`opencode.json`）或将任何 `node_modules/`、`__pycache__/` 混入 `.trellis/.template-hashes.json`。
- **宿主 Windows Shell 直跑原则**：
  - 所有后端（`uv run`）与前端（`pnpm`）命令及 `task verify` 直接在宿主 Windows `pwsh`（设置 `$env:PYTHONIOENCODING='utf-8'`）中运行，**禁止绕道 WSL / Linux 容器或新增 WSL 同步脚本**。
  - 必须在仓库根目录执行 `trellis` / `task.py` 命令，严禁在 `backend/` 或 `miniprogram/` 子目录内执行（防止生成嵌套空壳 `.trellis/`）。
- **行尾与编码**：全仓遵循根 `.editorconfig` 与 `.gitattributes` 约定，统一使用 `UTF-8`（无 BOM）与 `LF` 行尾。

---

## 4. 开工前与收工前速查清单

### 开工前（Pre-Work）
- [ ] 当前工作目录是否为仓库根目录 `d:\code\Workspace\zhilian`？
- [ ] `git status --short` 是否干净，当前分支是否从最新 `master` 切出且前缀与任务性质一致？
- [ ] 规划工件（`prd.md`，复杂任务含 `design.md`、`implement.md`、`implement.jsonl`、`check.jsonl`）是否已通过 `task.py validate`？

### 收工前（Pre-Finish）
- [ ] 宿主 `pwsh` 下 `task verify`（`task verify-backend` + `task verify-frontend`）是否全绿？
- [ ] `git worktree list` 是否仅剩主目录，`git branch` 是否无临时/孤儿分支？
- [ ] 新发现的契约/踩坑是否已同步至 `.trellis/spec/`？
- [ ] 已完成任务是否已执行 `task.py archive` 归档（不在 `.trellis/tasks/` 根目录堆积已完成工单）？
