# 版本控制证据与仓库门面

> 父任务：`09-29-lab3-delivery-wrapup`，覆盖其 **R4**。
> **排期约束**：本任务的产物要与 `lab3-process-docs` / `lab3-ui-screenshots` /
> `lab3-team-roster` 的产物**同批走 `feature/ZL-143-lab3-delivery` 分支**，不单独提前合并。
> **对外授权**：推分支、开 PR、合并、改分支保护与仓库元信息已由用户于 2026-09-29 授权
> （父任务 D-1），执行时仍需在收尾说明中如实报告每一步的真实结果。

## Goal

消除「文档承诺一套、仓库实证另一套」的落差。课程名为「代码实现与版本控制」，
老师第 2 条又专门索取代码管理平台链接，故必须让分支、合并请求、门禁在公开仓库中**真实存在**。

## 背景事实（父任务已核实）

- 远端仅 `master`，250 个提交无一个合并提交，0 PR，`.github/` 不存在。
- 本地功能分支**已全部并入 master**（`ahead=0`），GitHub 不支持对无独有提交的分支开 PR
  —— 因此历史不可回补，只能**从现在开始真的走一遍**。

## Acceptance Criteria

- [ ] AC-1 `.github/workflows/verify.yml` 存在，两个 job 的命令精确镜像 `Taskfile.yml`
- [ ] AC-2 CI 在 GitHub Actions 上**实际跑绿**（以 Actions 运行结论为准，非本地模拟）
- [ ] AC-3 `.github/CODEOWNERS` 存在，注释指向 `docs/团队分工.md`，不含真名
- [ ] AC-4 `LICENSE` 存在
- [ ] AC-5 公开仓库可见 `feature/ZL-143-lab3-delivery` 分支与**已合并**的 PR
- [ ] AC-6 `master` 历史出现 ≥1 个合并提交（`git log --merges` 非空）
- [ ] AC-7 `master` 分支保护生效：直接推送被拒（记录原始输出）；配置**不含必需评审**
  （单账号会自锁，见父任务 design.md 5.2）
- [ ] AC-8 已推送 `feat/question-bank-tab`、`feat/material-delete-entry`；
  `codex/*` 与 `worktree-agent-*` 未推送
- [ ] AC-9 仓库 `description`、`topics` 非空
- [ ] AC-10 若墙钟微基准导致 CI 红：按父任务 design.md 4.3 归因并**留痕排除**，
  同步 `AGENTS.md`；**不放宽阈值**

## 风险与回滚

见父任务 `design.md` 第 6 节。**合并提交与 PR 记录不可完全撤销**，执行前已获授权。

## Out of Scope

- 不重命名默认分支、不引入 `develop`（父任务 D-3）。
- 不启用必需评审的分支保护（父任务 D-4）。
- 不改写已公开历史（C-2）。
