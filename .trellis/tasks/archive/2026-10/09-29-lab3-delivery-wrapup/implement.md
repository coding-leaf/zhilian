# 执行计划：第3次实验课交付收尾

**本文件与同目录其它产物都会进公开仓库，因此不得写出真实姓名**，一律以「四个真名」指代，
字面量只存在于 `.git/hooks/pre-commit`（不被跟踪）。

## 0 前置核对（开工前一次性）

- [ ] `python ./.trellis/scripts/task.py current` 指向本任务或其子任务
- [ ] 后端在跑：`curl -s -o /dev/null -w "%{http_code}" localhost:8000/docs` → `200`
- [ ] 工作区干净：`git status --porcelain` 只有预期内的未跟踪项
- [ ] 确认当前不在 `master` 上直接改：`git rev-parse --abbrev-ref HEAD`

## 1 先立闸门（**必须早于任何提交**）

- [ ] 写 `.git/hooks/pre-commit`：扫描 `git diff --cached` 内容，命中四个真名即退出 1，
      输出文件名+行号但**不回显姓名**
- [ ] 授权位：`chmod +x .git/hooks/pre-commit`
- [ ] **验证闸门有效**（AC-8 的取证）：
  - [ ] 构造一条含真名的暂存改动 → `git commit` 必须被拒（记录退出码与输出）
  - [ ] 临时移走钩子 → 同一改动可通过（证明拦截来自钩子而非别的东西）
  - [ ] 恢复钩子，清掉这条测试提交

## 2 建分支

- [ ] `git switch -c feature/ZL-143-lab3-delivery master`

## 3 R3 分工产物

- [ ] 仓库外建 `D:\code\Workspace\zhilian-lab3-deliverables\`
- [ ] 写真名版《小组分工与个人工作小结》：四人角色、职责边界、RACI、代码所有权，
      每人一节个人小结（**按仓库真实产物回填**：谁拥有哪些目录、哪些 ZL 任务、
      哪些提交；使老师核对提交记录时对得上）
- [ ] 仓库内写 `docs/团队分工.md`（代号版 TechLead / SecLead / Reviewer / DevOpsLead，
      沿用《代码管理工作介绍》既有别名，并给出别名↔角色的对应表）
- [ ] 消除悬空引用：确认 `docs/团队分工.md` 能被《代码管理工作介绍》1.2 节引到
- [ ] 处置 `miniprogram/` 所有权冲突（**D-9 已定案**）：**不改**《代码管理工作介绍》，
      两份新分工文档按基线（SecLead）对齐该行，并加一行注记说明取舍依据

## 4 R1 交付文档

- [ ] 根 `README.md`：项目定位 / 技术栈 / 主链路 / 目录结构 / 启动 / 门禁 / 完成度与已知问题入口
- [ ] `docs/开发过程文档.md`：时间线、任务体系（35 个 ZL + 9 个 Trellis 任务）、
      迭代节奏、关键决策、**缺陷修复史**（重点写「静默失效」类：判题不落库、
      浮层吞输入、无归属 upsert 清空归属）、质量证据、**版本控制章节**（含 design.md 5.2 的偏差留痕）
- [ ] `docs/后续待解决问题.md`：未收口的 9 个任务 + 已知问题清单 + P1 延期与永久排除

## 5 R2 界面截图

- [ ] 仓库外 `D:\code\Workspace\zhilian-lab3-tools\` 装 `miniprogram-automator`
- [ ] 写驱动脚本：`automator.launch({ cliPath, projectPath })` → 逐页 `screenshot()`
- [ ] 若 `dist/dev/mp-weixin` 过期：`cd miniprogram && pnpm run build:mp-weixin`
- [ ] 按 design.md 3.2 的 12 项目标清单抓图，产物落 `docs/screenshots/`
- [ ] 写 `docs/screenshots/README.md`：每张图的页面、状态、链路位置
- [ ] **逐张目视检查有无真实姓名/用户名**（C-1 的盲区，L2 拦不住）
- [ ] 抓不到的态如实列入清单并标注原因
- [ ] 自动化不可用时按 design.md 3.3 降级，不伪造

## 6 R4 仓库配置（随分支一起提交的部分）

- [ ] `.github/workflows/verify.yml`：两个 job，命令精确镜像 `Taskfile.yml`
- [ ] `.github/CODEOWNERS`：以实际账号表达，注释指向 `docs/团队分工.md`
- [ ] `LICENSE`
- [ ] 实现期校准 design.md 4.2 的未定项（pnpm 版本、`--extra dev` 是否必需）

## 7 本地门禁（提交前）

- [ ] `task verify` → 退出码 0
- [ ] 若墙钟微基准失败：单独跑 `backend/tests/unit/core/algorithms/` 确认全过，
      判定为既有抖动，**不放宽阈值**，按 design.md 4.3 在 CI 中留痕排除
- [ ] `git grep` 四个真名在全部被跟踪文件中 0 命中（AC-9）

## 8 提交与推送（对外动作，已获授权）

- [ ] 提交信息遵循 3.2 节：`type(scope): 中文描述`，scope 只取词表内值（`docs`/`ci`），
      **不含真名**
- [ ] `git push -u origin feature/ZL-143-lab3-delivery`
- [ ] 开 PR（base `master`）：正文写清覆盖的 4 条课程要求与验收证据
- [ ] **观察 CI 实际运行结论**（AC-10 以 Actions 为准，不以本地模拟为准）
  - [ ] 绿 → 继续
  - [ ] 红 → 按 design.md 4.3 归因后处理，必要时留痕排除

## 9 分支保护与合并

- [ ] 配置 `master` 保护：必需状态检查 + 禁止强推/删除 + **不设必需评审**（design.md 5.2）
- [ ] 取证 AC-12：直接 `git push origin master` 必须被拒，记录原始输出
- [ ] 用**合并提交**合并 PR（D-5），不在本地手工 merge 后推
- [ ] `git log --merges --oneline` 应出现合并提交（AC-11）

## 10 补齐已有分支与仓库门面

- [ ] 推 `feat/question-bank-tab`、`feat/material-delete-entry`（不推 `codex/*`、`worktree-agent-*`）
- [ ] 设 `description`、`topics`（API，凭据经 `git credential fill` 取用，**不回显、不落盘**）
- [ ] 确认 `LICENSE` 已在 master 上可见

## 11 收尾核验

- [ ] 逐条过 `prd.md` 的 AC-1 ~ AC-14，每条记录取证命令与原始输出
- [ ] 再跑一次 `task verify`
- [ ] 父任务跨子任务复核：4 条课程要求逐条能指认到产物
- [ ] 更新 `AGENTS.md`（若 CI 排除项成立）
- [ ] 归档子任务，再归档父任务（注意互引链接）

## 回滚点

| 阶段 | 可逆性 | 回滚方式 |
| --- | --- | --- |
| 1 钩子 | 完全可逆 | 删除 `.git/hooks/pre-commit` |
| 3-6 本地产物 | 完全可逆 | `git switch master` 丢弃分支 |
| 8 推送分支 | 可逆 | `git push origin --delete feature/ZL-143-lab3-delivery` |
| 8 开 PR | 可关闭，**记录不可删** | 关闭 PR（不删，留痕更诚实） |
| 9 合并 | 内容可退，**历史痕迹保留** | `git revert -m 1 <merge>` |
| 9 分支保护 | 可逆 | `DELETE /repos/:owner/:repo/branches/master/protection` |
| 10 元信息 | 可逆 | 重新 PATCH |

## 开工前必须已确认

- [ ] 用户已批准 `prd.md` / `design.md` / `implement.md` 的最终规划摘要
- [ ] 用户已知悉：推送、开 PR、合并、改分支保护与仓库元信息均为**对外可见且部分不可撤销**
