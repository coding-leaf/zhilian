# M1 远端 `origin` 同步与旧分支清理参考清单（待本地验收确认后执行）

> 按照规划约定，`M1` 仅在本地完成 `master` 合流、分支清理与工作区治理，**未对 GitHub `origin` 执行任何推送或远端删除**。
> 当你验收完本地提交并准备同步至远端时，可在仓库根目录 `pwsh` 按序执行以下命令：

## 1. 推送合流后的 `master` 主干与归档备份标签（可选推送标签）

```powershell
# 先预览即将推送到 origin/master 的提交（包含原 origin/dev 21 个提交 + P1-4 个人页学习统计修复）
git log --oneline origin/master..master

# 推送更新后的 master 主干（若在 chore/m1-workspace-governance 合入 master 后再推，可一并推送）
git push origin master
```

## 2. 清理远端已 100% 祖先合入 `master` 的 8 个历史分支

```powershell
git push origin --delete `
  feat/question-bank-tab `
  feat/material-delete-entry `
  feature/ZL-143-lab3-delivery `
  feature/ZL-143-branch-protection-note `
  feature/ZL-143-lab3-screenshots `
  feature/ZL-143-sync-task-status `
  feature/ZL-144-question-bank-autoload `
  feature/ZL-145-record-findings
```

## 3. 在确认 `master` 已成功接收合流内容后，退役远端 `dev` 与 `chore/workspace-configs`

```powershell
# 确认 origin/dev (10bdd91) 已是 master 的祖先
git merge-base --is-ancestor origin/dev master

# 删除已退役的远端分叉分支并修剪本地远程跟踪引用
git push origin --delete dev chore/workspace-configs
git fetch --prune origin
```
