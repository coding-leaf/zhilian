# 执行清单：环境与 CI 准备

> 任务：`10-03-midterm-ci-baseline`
> 依据：`prd.md`、`design.md`
> 执行边界：**只出文件**，不做任何 git 提交 / 推送 / tag（约束 C-2）

## 0 已确认决策（2026-10-03，用户拍板）

| 项 | 决策 |
| --- | --- |
| SonarQube | 接 **SonarCloud**（授权由用户执行） |
| 分支策略 | **沿用单 `master`** |
| 基线范围 | 自 **2026-09-29 收敛起点**至今（实测 66 提交 / 301 文件） |
| 执行边界 | **只出文件，不提交** |

## 1 执行步骤

### S1 规划产物与上下文

- [x] 建任务 `10-03-midterm-ci-baseline`
- [x] `research/ci-and-baseline-facts.md`
- [x] `prd.md` / `design.md` / `implement.md`
- [ ] `implement.jsonl` / `check.jsonl` 各 ≥1 条真实条目
- [ ] `task.py validate` 通过 → `task.py start`

### S2 前端覆盖率依赖

- [x] 备份 `package.json` / `pnpm-lock.yaml`
- [x] `pnpm add -D --lockfile-only @vitest/coverage-v8@1.6.1`
- [x] 校验 `lockfileVersion` 仍为 `9.0` 且 diff 为纯新增
- [ ] `miniprogram/package.json` 追加 `test:cov` 脚本
- [ ] `miniprogram/vitest.config.ts` 追加 `test.coverage`

### S3 CI 流水线改造

- [ ] `Taskfile.yml`：`verify-backend` 的 pytest 追加 `--cov-report=term-missing --cov-report=xml`
- [ ] `Taskfile.yml`：`verify-frontend` 第三步 `test:unit` → `test:cov`
- [ ] `.github/workflows/verify.yml`：backend 命令同步（保持镜像）+ 上传 `backend-coverage` artifact
- [ ] `.github/workflows/verify.yml`：frontend 命令同步 + 上传 `frontend-coverage` artifact
- [ ] `.github/workflows/verify.yml`：新增 `sonar` job（`needs: [backend, frontend]`，token 缺失时短路）
- [ ] 新增 `sonar-project.properties`
- [ ] `.gitignore` 追加 `miniprogram/coverage/`

### S4 模板落地

- [ ] 新增 `.github/PULL_REQUEST_TEMPLATE.md`（由 `中期质量检查/templates/PR-MR模板.md` 派生，零真名）

### S5 文档产出

- [ ] `中期质量检查/环境与CI准备.md`
- [ ] `中期质量检查/基线版本.md`
- [ ] 更新 `中期质量检查/README.md` 索引

### S6 校验与收尾

- [ ] 真名闸门扫描全部新增/修改文件 → 0 命中
- [ ] YAML 语法校验（`verify.yml`）
- [ ] `sonar-project.properties` 语法与字段完整性检视
- [ ] 确认 `git status` **无新提交**
- [ ] 矛盾检查：与 `AGENTS.md` / `Taskfile.yml` / `docs/` 无口径冲突
- [ ] 工作记忆记录

## 2 验证方式

| 项 | 命令 / 方法 | 期望 |
| --- | --- | --- |
| YAML 语法 | `python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/verify.yml',encoding='utf-8'))"` | 无异常 |
| lockfile 版本 | `grep "^lockfileVersion" miniprogram/pnpm-lock.yaml` | `'9.0'` |
| 依赖版本一致 | 比对 `package.json` 中 `vitest` 与 `@vitest/coverage-v8` | 均为 `1.6.1` |
| 真名闸门 | `. .git/hooks/zhilian-name-guard.sh && zhilian_report_hits "<内容>" "<位置>"` | 0 命中 |
| 镜像一致性 | 对比 `Taskfile.yml` 与 `verify.yml` 的门禁命令 | 逐条一致 |
| 无提交 | `git status --porcelain` 中无 `A`/`M` 之外的提交痕迹；`git log -1` 未变 | HEAD 仍为 `e1cef6d` |
| artifact 路径 | `grep -n "upload-artifact" .github/workflows/verify.yml` | 2 处，路径与 design §3.3 一致 |

> **明确不做的验证**：不跑全量 `task verify`。理由——本次改动**不含任何后端业务代码**，
> 后端门禁结果不可能受影响；而前端门禁命令已变，本地 `node_modules` 未安装新依赖（受限 L-4），
> 跑它只会得到"依赖缺失"这一预期内结果，不构成有效证据。此项在 check-evidence 中如实记录。

## 3 风险与回滚

| 风险 | 缓解 | 回滚 |
| --- | --- | --- |
| lockfile 被 pnpm 12 改写导致 CI 失败 | 已实测 `lockfileVersion` 未变、纯新增 | 用备份 `/tmp/zhilian-pnpm-backup-*` 覆盖还原 |
| Sonar job 在未配置 token 时变红 | step 级 `if: env.SONAR_TOKEN == ''` 短路 | 删除 `sonar` job 即可 |
| 前端门禁命令变更导致本地红 | 文档明写需先 `pnpm install` | `verify-frontend` 第三步改回 `test:unit` |
| 模板含真名 | 闸门扫描 | 修正命中行 |

**回滚总原则**：本次全部改动均为**文件级新增/修改且未提交**，回滚 = `git checkout -- <file>` 或删除新增文件，无副作用。

## 4 交付物清单

| 类型 | 路径 |
| --- | --- |
| 新增 | `sonar-project.properties` |
| 新增 | `.github/PULL_REQUEST_TEMPLATE.md` |
| 新增 | `中期质量检查/环境与CI准备.md` |
| 新增 | `中期质量检查/基线版本.md` |
| 修改 | `.github/workflows/verify.yml` |
| 修改 | `Taskfile.yml` |
| 修改 | `.gitignore` |
| 修改 | `miniprogram/vitest.config.ts` |
| 修改 | `miniprogram/package.json` |
| 修改 | `miniprogram/pnpm-lock.yaml`（S2 已改） |
| 修改 | `中期质量检查/README.md` |
