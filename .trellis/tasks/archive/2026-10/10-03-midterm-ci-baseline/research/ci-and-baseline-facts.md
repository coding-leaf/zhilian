# 研究底稿：环境与 CI 准备（现状事实 · 缺口 · 实测数据）

> 任务：`10-03-midterm-ci-baseline`
> 采集日期：2026-10-03
> 纪律：本文所有易变数字均附**取得命令**，不手抄（沿用第 1 步立下的规矩）。

## 1 已确认的用户决策（2026-10-03）

| 项 | 决策 |
| --- | --- |
| SonarQube | **接 SonarCloud**（公开仓库免费）；CI 与配置由本任务落地，GitHub 侧授权由用户执行 |
| 分支策略 | **沿用单 `master`**，不引入 develop/main |
| 基线范围 | **自 2026-09-29 收敛起点至今** |
| 执行边界 | **只出文件，不做任何 git 提交 / 推送 / tag** —— 基线 tag 只给命令 |

## 2 现状事实（附命令）

### 2.1 CI 流水线

`cat .github/workflows/verify.yml`

| 项 | 现状 |
| --- | --- |
| 触发 | `push` / `pull_request` → `master` |
| 并发 | `concurrency: verify-${{ github.ref }}`，`cancel-in-progress: true` |
| job `backend` | uv 安装 → Python 3.13 → `uv sync --frozen --extra dev` → `ruff format --check .` → `ruff check .` → `mypy app` → `lint-imports` → `pytest tests --cov=app --cov-branch --cov-fail-under=80` |
| job `frontend` | pnpm 10 → Node 22 → `pnpm install --frozen-lockfile` → `pnpm run lint` → `pnpm run type-check` → `pnpm run test:unit` |
| 外部服务 | **无**（不挂 postgres/redis service 容器） |
| 与本地关系 | 命令**精确镜像** `Taskfile.yml` 的 `verify-backend` / `verify-frontend` |

### 2.2 覆盖率能力

| 项 | 现状 | 命令 |
| --- | --- | --- |
| 后端工具 | `pytest-cov>=5.0.0` 已在 `[project.optional-dependencies].dev` | `grep -n "pytest-cov" backend/pyproject.toml` |
| 后端门禁 | `--cov-fail-under=80`（**全量**口径） | 见 2.1 |
| 后端留档 | **无** —— CI 里没有 `upload-artifact`、没有 `coverage.xml` 落盘 | `grep -n "upload-artifact\|codecov" .github/workflows/verify.yml` → 空 |
| 前端工具 | 本任务前**无** coverage 依赖 | `grep -n coverage miniprogram/package.json` → 空 |
| 前端门禁 | **无阈值** | 见 2.1 |

### 2.3 分支与保护

| 项 | 现状 | 命令 / 出处 |
| --- | --- | --- |
| 默认分支 | `master`（`origin/HEAD -> origin/master`） | `git branch -r` |
| 保护规则 | 已在 `master` 启用：必需状态检查 + 禁止直接推送 + 禁止强推 + 禁止删除 | `docs/开发过程文档.md` §6.1 |
| 必需评审 | **不启用** —— 单账号仓库，GitHub 不允许 PR 作者批准自己的 PR，启用会锁死 `master` | 同上 §6.1 |
| 分支命名 | 自 `ZL-143` 起用 `类型/任务编号-短描述` | 同上 §6.2 |
| 合并方式 | 走 PR，保留合并提交（历史 PR #2–#5 已可见） | `git log --oneline` |
| 现有 tag | 仅 `backup/session-2026-09-28-before-trellis`（备份 tag，非版本基线） | `git tag -l` |

### 2.4 基线 commit 范围（实测）

| 项 | 值 | 命令 |
| --- | --- | --- |
| 范围起点（base，不含） | `61b9ee1` · 2026-09-28 19:21:42 · `chore(task): archive 09-28-frontend-ui-redesign` | `git log --format="%H" --until="2026-09-29 00:00" -1` |
| 范围起点（首个纳入） | `609e7f1` · 2026-09-29 00:45:20 | `git log --since="2026-09-29 00:00" \| tail -1` |
| 范围终点 | `e1cef6d` · 2026-09-29 12:05:34 · `Merge pull request #5` | `git log -1` |
| 提交数 | **66** | `git rev-list --count 61b9ee1..HEAD` |
| 涉及文件数 | **301** | `git diff --name-only 61b9ee1..HEAD \| wc -l` |
| 仓库总提交数 | 263 | `git rev-list --count HEAD` |

> 说明：《开发过程文档》§6.2 以「`ZL-143` 提交」标记收敛起点，但 `git log --grep="ZL-143"` 为**空**——
> `ZL-143` 是**任务编号**，不在提交信息里。故基线范围改用**可复现的 commit 边界**表达（上表）。

### 2.5 测试环境与可重复运行

| 项 | 现状 | 出处 |
| --- | --- | --- |
| 后端外部能力替身 | `app/integrations/` 下 6 类：`llm/fake`、`ocr/fake`、`embedding/fake`、`storage`、`queue/memory`、`idempotency/memory`、`search` | `find backend/app/integrations -type d` |
| 后端测试夹具 | `backend/tests/conftest.py` | `find backend/tests -name conftest.py` |
| 前端 uni API 替身 | `miniprogram/tests/setup.ts` —— 内存 Map 实现的 `uni.getStorageSync` 等 | 实读 |
| 前端夹具 | `miniprogram/tests/fixtures/`（如 `backendResponses.ts`） | 实读 |
| 默认运行依赖 | 不依赖数据库与网络，秒级跑完 | `docs/开发过程文档.md` §5.2 |
| 前端测试文件数 | **14** 个 `.spec.ts`（另有 `setup.ts` 与 `fixtures/`） | `ls miniprogram/tests/*.spec.ts \| wc -l` |

### 2.6 模板与其他

| 项 | 现状 | 命令 |
| --- | --- | --- |
| `.github/` 内容 | 仅 `CODEOWNERS` + `workflows/verify.yml` | `find .github -type f` |
| PR 模板 | **不存在**（`.github/PULL_REQUEST_TEMPLATE.md` 缺失） | 同上 |
| Issue 模板 / dependabot | **不存在** | 同上 |
| Sonar 配置 | **零配置**（全仓库无 `sonar*` 文件、无 sonar 相关 workflow 步骤） | `find . -iname "*sonar*"` |
| 已有 PR 模板正文 | `中期质量检查/templates/PR-MR模板.md`（第 1 步产出） | 实读 |

## 3 缺口清单（本任务要补的）

| 编号 | 缺口 | 影响 |
| --- | --- | --- |
| G-1 | CI 无覆盖率**留档**（无 artifact、无报告文件） | 「覆盖率统计」只活在日志里，无法评审、无法进 Sonar |
| G-2 | **无 SonarQube/SonarCloud** 静态扫描 | 课程要求项缺失 |
| G-3 | 前端**无覆盖率**（无工具、无阈值） | 「新增代码覆盖率」在前端无法取证 |
| G-4 | **PR 模板未落地** | GitHub 新建 PR 不会自动套用模板 |
| G-5 | **无版本基线 tag** | 评审 commit 范围无锚点 |
| G-6 | 无成文的「依赖环境与可重复运行」说明 | 课程要求项无书面证据 |

## 4 关键技术风险与已验证的缓解

### R-1 lockfile 格式风险（**已验证通过**）

- 风险：本机 pnpm `12.6.0`，CI 用 pnpm `10`；若 `pnpm add` 把 `lockfileVersion` 升级，CI 的 `--frozen-lockfile` 会失败。
- 处置：先备份 `package.json` / `pnpm-lock.yaml`，再用 `pnpm add -D --lockfile-only @vitest/coverage-v8@1.6.1`（**不动 node_modules**）。
- 实测结果：`lockfileVersion` **仍为 `9.0`**；diff 为 **108 行纯新增、0 删除**。风险解除。

### R-2 无 SONAR_TOKEN 时 CI 变红

- 风险：Sonar job 在未配置 secret 时失败，会让「未授权」看起来像「代码有问题」。
- 处置：Sonar job 内用 `env.SONAR_TOKEN` 判断，未配置时输出 notice 并**跳过扫描步骤**，job 保持绿色。

### R-3 前端覆盖率首次接入可能踩到阈值

- 风险：初装 coverage 时真实行覆盖率可能低于拟定阈值，直接设硬阈值会立刻红灯。
- 处置：**先只统计不设阈值**（`--coverage` 报告 + artifact 留档），阈值待 M0 基线化取到实测值后再设。
