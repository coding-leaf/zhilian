# 环境与 CI 准备

> 对应课程要求：中期质量检查 **第 2 步「环境与 CI 准备」**
> 编制日期：2026-10-03
> 关联任务：`.trellis/tasks/10-03-midterm-ci-baseline/`
> 表述方式：角色代号（TechLead / SecLead / Reviewer / DevOpsLead）；本仓库公开，不记载姓名

本目标是**让单元测试与代码评审能自动、稳定执行**。

**一句话结论**：底盘本来就好（CI 能跑、分支保护已配、测试替身齐备、不依赖外部服务），
本次补的是四件缺失的能力——**覆盖率留档、静态扫描、PR 模板落地、基线锚点**。

---

## 1 分支策略

**采用单 `master` 作为集成分支**，不引入 `develop` / `main`（2026-10-03 决策）。

| 项 | 约定 |
| --- | --- |
| 长期分支 | `master`（唯一集成分支、默认分支；**有分支保护，禁止直接推送**） |
| 短期分支 | `类型/任务编号-短描述`，如 `feature/ZL-150-midterm-ci-baseline` |
| 合并路径 | 短期分支 → PR → `master` |
| 合并方式 | **保留合并提交**，不用 squash（使分支结构在 `git log --graph` 中可见） |
| 提交信息 | `类型(scope): 一句话说明`，scope 只取词表：`api` / `services` / `algorithms` / `integrations` / `models` / `miniprogram` / `deploy` / `ci` / `docs` |

### 1.1 仓库的实际分支形态

> ⚠️ **更正（2026-10-03 晚）**：本文件初稿写的是「单 `master` + 短期分支」，**通篇没有提 `dev`** ——
> 因为初稿写于 `dev` 分支出现之前。实际形态如下，**以本节为准**：

```
master                    ← 集成分支 / 默认分支（受保护，禁止直接推送）
├── dev                   ← 中期质量检查的承载分支（PR #7 与 PR #9 的来源）
├── feat/*  feature/*     ← 历史短期分支（按任务编号命名，不追溯改名）
└── codex/*               ← 历史短期分支
```

**`dev` 的定位必须说清楚，避免被误当成 `develop`**：

- 它**不是**《代码管理工作介绍 V1.0》里的 `develop` 长期集成分支；
- 它是**为中期质量检查临时启用的承载分支**——PR #7 的提交先落 `dev`、再合并进 `master`（merge commit `0c301fa`）；
- 它是否升格为长期 `develop`、还是用完即删，属**未决事项**，本文件不擅自定性。

**为什么不改成 `main` + `develop`**：文档《代码管理工作介绍 V1.0》第 3 章确实定义了精简 Git Flow，
但本仓库的偏差是**有起点的历史**——`docs/开发过程文档.md` §6.1 已如实记录，且 §6.2 明确
「历史分支不追溯改名——改写已公开历史的风险大于收益」。引入 `develop` 需要改默认分支、
改保护规则、改 CI 触发分支，风险集中在收益不明的结构性重构上，本次不做。

## 2 保护分支

### 2.1 现状

`master` 上的保护规则为：

| 规则 | 状态 |
| --- | --- |
| 必需状态检查（`verify` 全绿） | ✅ 已启用 |
| 禁止直接推送 | ✅ 已启用 |
| 禁止强推（force push） | ✅ 已启用 |
| 禁止删除分支 | ✅ 已启用 |
| **必需评审人批准** | ⚠️ **可启用，但尚未配置** —— 见 2.2 |

### 2.2 「必需评审人批准」：从「不可执行」变成「还没做」

**初稿（2026-10-03 白天）的结论是「不可执行」**，理由是「仓库只有一个协作账号，
而 GitHub 不允许 PR 作者批准自己的 PR，启用会把 `master` 锁死」。

**该结论在当时成立，但它的前提已经变了。**

> ⚠️ **更正（2026-10-03 晚）**：仓库现在有 **两个** GitHub 账号 ——
> `hennessy9684`（本次工作使用的账号，已接受协作者邀请，实测权限 `push: true`）与
> `coding-leaf`（仓库所有者）。PR 作者与评审人可以是**不同**账号，
> 因此「必需评审人批准」**现在完全可执行**。

**实证**：PR #9 打开后，GitHub 依 `.github/CODEOWNERS`（`* @coding-leaf`）**自动请求了
`coding-leaf` 评审**，PR 随即显示 `mergeable_state: blocked`。
注意此时三个 CI check **全部是 success** —— `blocked` 来自**评审要求**，不是 CI 失败。

**所以这条的性质变了：从「当前形态下做不到」变成「还没去配」。**
需要在 `master` 的保护规则里启用 `Require approvals`（步骤见 2.3）。
在配置之前，评审仍是**组织层约定**（`docs/团队分工.md`），不在服务端强制。

> **`docs/开发过程文档.md` §6.1 的同类表述刻意不改**：那份文档的覆盖区间是
> 2026-09-23 → 2026-09-29，「不可执行」是**当时的事实**；改它等于篡改历史记录。
> 现状变化在本文件交代，两份文档各守其时间定位。

**与「机器门禁」的分工**（不变）：机器管「人容易漏的」——静态检查、类型检查、架构契约、
单元测试、覆盖率门槛、静态扫描；人管「机器看不见的」——接线是否正确、归因是否成立。
两者互补，而不是用一个假装成另一个。

### 2.3 若要调整保护规则（手工步骤）

GitHub → 仓库 `Settings` → `Branches` → `Branch protection rules` → `master`：

1. 确认勾选 **Require status checks to pass before merging**，并把 `verify` 加入必需检查；
2. 确认勾选 **Do not allow bypassing the above settings**；
3. **现在可以勾选 `Require approvals`（设为 1 人）** —— 前提见 2.2，仓库已有两个账号；
   勾选后由 `coding-leaf`（或任一非作者账号）批准即可合并，不会再锁死；
4. 勾选 **Require review from Code Owners**，让 `.github/CODEOWNERS` 的路径级要求真正生效
   （高风险路径 `core/algorithms/`、`core/security.py`、`api/deps/`、`deploy/`、`.github/workflows/`
   目前都落在 `@coding-leaf`）；
5. 建议勾选 **Require conversation resolution before merging**（评审意见闭环的机器抓手）。

## 3 CI 流水线

### 3.1 拓扑

`.github/workflows/verify.yml` 现有 **3 个 job**：

```
verify
├── backend   后端门禁 + 覆盖率报告
├── frontend  前端门禁 + 覆盖率报告
└── sonar     静态扫描（needs: backend, frontend；无 token 时短路）
```

| job | 步骤 |
| --- | --- |
| `backend` | uv → Python 3.13 → `uv sync --frozen --extra dev` → `ruff format --check` → `ruff check` → `mypy app` → `lint-imports` → `pytest`（覆盖率 ≥80%，另产出 `coverage.xml`）→ 上传 `backend-coverage` artifact |
| `frontend` | pnpm 10 → Node 22 → `pnpm install --frozen-lockfile` → `eslint` → `vue-tsc` → `vitest --coverage` → 上传 `frontend-coverage` artifact |
| `sonar` | 校验 token → 完整历史检出 → 下载覆盖率 artifact → SonarCloud 扫描 |

| 项 | 设置 |
| --- | --- |
| 触发 | `push` / `pull_request` → `master` |
| 并发 | 同一 ref 的重复运行自动取消（`cancel-in-progress`） |
| 外部服务 | **无**——不挂 postgres / redis service 容器 |
| artifact 保留 | 14 天 |

#### ❌ 未接入的一环：编译 / 构建（2026-10-03 核查）

课程要求的流水线含「**编译**」，但**当前 CI 的任何一个 job 里都没有构建步骤**：

| 端 | 有没有构建 | 说明 |
| --- | --- | --- |
| 后端 | 不适用 | Python 无编译期；「安装依赖」即 `uv sync --frozen --extra dev` |
| 前端 | **有脚本、没进 CI** | `pnpm run build:mp-weixin`（= `uni build -p mp-weixin`）**从未在 CI 跑过** |

这意味着「代码能不能构建出小程序包」目前**没有任何自动化在看**。
`eslint` 与 `vue-tsc` 只能证明**风格与类型**没问题，**不等于能构建** ——
这与本项目已记录过的那类错误同源：「被测单元正确 ≠ 接线正确」。

> **为什么先不贸然接入**：需先确认 `uni build` 在**无微信开发者工具的 Linux runner** 上能否跑通。
> 本机未验证，直接加进 CI 有制造红灯的风险。**列为待办，不当作已完成。**

### 3.2 与本地门禁的关系（关键约定）

CI 命令**精确镜像** `Taskfile.yml`，**不另立第二套门禁**：

| 门禁 | 本地 | CI |
| --- | --- | --- |
| 后端 | `task verify-backend` | 同一串命令 |
| 前端 | `task verify-frontend` | 同一串命令 |
| 全部 | `task verify` | 两个 job 并行 |

**本地跑绿即 CI 跑绿**，避免两边标准漂移。本次改动保持了这个不变量：
两边同步修改，没有出现「CI 比本地严」或「本地比 CI 严」。

### 3.3 本次对门禁的改动（只有两处，语义不变）

| 位置 | 改动 | 门禁语义变化 |
| --- | --- | --- |
| `verify-backend` | pytest 追加 `--cov-report=term-missing --cov-report=xml` | **无**（`--cov-fail-under=80` 原样保留） |
| `verify-frontend` | 第三步 `test:unit` → `test:cov` | **无**（前端覆盖率只统计、不设阈值） |

> `test:unit` 脚本本身**未改**；`test:cov` 是新增的 `vitest run --coverage`。
> 因此本地快速迭代仍可用 `task test-frontend`（无覆盖率开销）。

## 4 测试环境、Mock 与可重复运行

这是本项目做得最扎实的一块，也是「单测可重复运行」的**实际保障**。

### 4.1 依赖环境

| 层 | 依赖 | 说明 |
| --- | --- | --- |
| 后端 | Python 3.13 + uv | `uv sync --frozen --extra dev`；锁文件冻结保证可重复 |
| 前端 | Node 22 + pnpm 10 | `pnpm install --frozen-lockfile`；锁文件冻结保证可重复 |

### 4.2 Mock 服务（测试替身）

**外部能力全部走协议抽象 + 纯内存假实现**，因此全量测试**不依赖数据库与网络**：

| 能力 | 替身 | 位置 |
| --- | --- | --- |
| 大模型 | `FakeLLMAdapter` | `backend/app/integrations/llm/fake.py` |
| OCR | `FakeOCRAdapter` | `backend/app/integrations/ocr/fake.py` |
| 向量化 | `FakeEmbeddingAdapter` | `backend/app/integrations/embedding/fake.py` |
| 队列 | `MemoryQueueAdapter` | `backend/app/integrations/queue/memory.py` |
| 幂等 | `MemoryIdempotencyAdapter` | `backend/app/integrations/idempotency/memory.py` |
| 存储 / 检索 | 内存实现 | `backend/app/integrations/{storage,search}/` |

前端则替掉 uni-app API：`miniprogram/tests/setup.ts` 用内存 Map 实现
`uni.getStorageSync` / `setStorageSync` 等，页面与组合式函数在 Node 下即可挂载。

### 4.3 测试夹具

| 位置 | 内容 |
| --- | --- |
| `backend/tests/conftest.py` | 后端共享夹具 |
| `miniprogram/tests/setup.ts` | uni API 替身，全局注入 |
| `miniprogram/tests/fixtures/` | 前后端契约样本（如 `backendResponses.ts`） |

### 4.4 「可重复运行」的三个保障

1. **锁文件冻结**——前后端均用 `--frozen` / `--frozen-lockfile`，依赖版本不会漂移；
2. **无外部服务**——不挂 service 容器，不受网络与中间件状态影响；
3. **无墙钟依赖**——除 6 处已知的算法核微基准断言外（见 §7），用例不依赖真实时间。

> 测试慢是覆盖率下滑的第一原因，把依赖摘掉是维持覆盖率最有效的手段。
> 当前全量测试**秒级跑完**，这也是本项目后端覆盖率能维持在 90%+ 的原因之一。

### 4.5 本地复现 CI

```bash
# 全量
task verify

# 分别
task verify-backend
task verify-frontend

# 只跑覆盖率（不跑其他门禁）
cd backend && uv run pytest tests --cov=app --cov-branch --cov-report=term-missing --cov-report=xml
cd miniprogram && pnpm run test:cov
```

⚠️ **前端新增了 `@vitest/coverage-v8` 依赖**，改完代码后若本地 `test:cov` 报模块缺失，
先执行 `pnpm install` 即可（这是新增依赖的正常代价）。

## 5 SonarCloud 接入手册

### 5.1 已完成（仓库侧接线）—— 但**尚未启用**

> ⚠️ **状态更正（2026-10-03 晚）：这是「接了线，没通电」。**
> `sonar` job 在 CI 上显示 **success**，但那是**短路保绿**的结果，**不是扫描通过**：
> `sonar-project.properties` 的 `sonar.organization` / `sonar.projectKey` **仍是占位符**
> （`ORGANIZATION-KEY` / `PROJECT-KEY`），仓库也没有配置 `SONAR_TOKEN`。
> **也就是说，SonarCloud 至今对这份代码什么都没扫过。**
> 「绿色」在这里的含义是「**未启用**」，不是「没问题」——这一点不能含糊。

已完成的部分（仓库侧）：

- `sonar-project.properties`（仓库根）：声明源码/测试路径、覆盖率报告路径、排除清单；
- `.github/workflows/verify.yml` 的 `sonar` job：依赖前后端 job，消费 artifact 后扫描；
- 扫描 Action 固定 `@v8` —— **v6.0.0 修复了 args 命令注入漏洞（CVE-2025-59844），
  不可降到 v5 及以下**（这是查证后的结论，不是随手写的版本号）。

**设计要点**：`fetch-depth: 0` 是必需的——SonarCloud 需要完整历史来判定「新代码」，
浅克隆会让新增代码覆盖率失真。

**距真正启用只差 5.2 的账号侧步骤。**

### 5.2 待执行（账号侧，需在 GitHub / SonarCloud 网页完成）

| 步骤 | 操作 |
| --- | --- |
| 1 | 用 GitHub 账号登录 https://sonarcloud.io |
| 2 | `+` → `Analyze new project` → 导入仓库 `coding-leaf/zhilian` |
| 3 | 记下 **Organization Key** 与 **Project Key**（形如 `<org>_zhilian`） |
| 4 | 回填 `sonar-project.properties` 中的 `sonar.organization` 与 `sonar.projectKey` 两个占位符 |
| 5 | SonarCloud → `My Account` → `Security` → 生成 token |
| 6 | GitHub 仓库 → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`，名称 `SONAR_TOKEN`，值为上一步 token |
| 7 | 合并改动后，推送到 `master` 或开 PR，观察 `verify` 中 `sonar` job |

### 5.3 未配置时会怎样

**不会变红**。`sonar` job 内的步骤带条件 `if: env.SONAR_TOKEN == ''` / `!= ''`，
未配置 token 时只输出一条 notice 并跳过扫描，**job 保持绿色**。

这样设计的原因：未启用 SonarCloud 应该表现为「未启用」，而不是看起来像「代码有问题」。

> 当前 `sonar-project.properties` 里 `sonar.organization` / `sonar.projectKey` **仍是占位符**，
> 必须完成 5.2 的步骤 3–4 才能实际生效。

## 6 本次改动清单

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| 新增 | `sonar-project.properties` | SonarCloud 配置 |
| 新增 | `.github/PULL_REQUEST_TEMPLATE.md` | PR 模板，GitHub 自动套用 |
| 修改 | `.github/workflows/verify.yml` | 覆盖率 artifact ×2 + `sonar` job |
| 修改 | `Taskfile.yml` | 后端补报告格式；前端 `test:unit` → `test:cov` |
| 修改 | `.gitignore` | 追加 `miniprogram/coverage/` |
| 修改 | `miniprogram/package.json` | 新增 `@vitest/coverage-v8@1.6.1` + `test:cov` 脚本 |
| 修改 | `miniprogram/pnpm-lock.yaml` | 同步依赖（**纯新增 108 行，`lockfileVersion` 保持 9.0**） |
| 修改 | `miniprogram/vitest.config.ts` | 新增 `test.coverage` |

**PR / MR 模板**同时存在于两处，互为同源：

- `.github/PULL_REQUEST_TEMPLATE.md` —— GitHub 新建 PR 时自动套用；
- `中期质量检查/templates/PR-MR模板.md` —— 课程交付版（含标题格式、评审与合并规则、禁止项）。

改其中一处请同步另一处。

## 7 未验证项与已知限制（如实登记）

| 编号 | 限制 | 状态 |
| --- | --- | --- |
| L-1 | ~~新增 CI job 未在真实 GitHub Actions 上跑过~~ | **已消除** —— PR #7 / PR #9 的 `verify` 三个 job 均在真实 Actions 上跑过 |
| L-2 | `sonar-project.properties` 的 `organization` / `projectKey` 为**占位符**，且无 `SONAR_TOKEN` → **SonarCloud 尚未真正扫描任何代码** | **未解决**（需账号侧操作，见 §5.2） |
| L-3 | 前端覆盖率**只有报告、无阈值**，暂不能作为准出判据（首次接入无历史基线） | 未解决（待 M0 基线化） |
| L-4 | 本机 `node_modules` **未安装** `@vitest/coverage-v8`；本地 `test:cov` 需先 `pnpm install` | 未解决（本机环境问题） |
| L-5 | ~~增量覆盖率门禁（`diff-cover`）仍未接入~~ | **已解决** —— 已接入 `Taskfile.yml` 与 CI，并实测通过（含反证） |
| L-6 | `tests/unit/core/algorithms/` 的 6 处墙钟断言在全量套件下仍会抖动 —— 既有测试设计问题，`AGENTS.md` 定案**不放宽阈值** | 未解决（既有问题，本次不动） |
| **L-7** | **CI 没有任何「编译 / 构建」步骤**；前端 `build:mp-weixin` 从未在 CI 跑过（详见 §3.1） | **未解决**（待验证后接入） |
| **L-8** | **T0 接口层 `app/api/deps/` 实测 83%，未达 90% 目标**（`user.py` 3 行未覆盖）；门禁暂设 80% 防下滑 | **未达标**，已登记（《单测计划》§4） |
| **L-9** | **必需评审人批准尚未在服务端启用**（前提已具备，见 §2.2） | **未配置** |
| **L-10** | 「T0 **增量**覆盖率」未能实现 —— diff-cover 的 `--include` 在本项目布局下**静默放行**，已改用 `coverage report --include` 的**绝对**口径替代 | 口径已调整，**非遗漏**（详见《单测计划》§3.1） |

## 8 与「稳定执行」的关系

课程要求「让单元测试和代码评审能自动、**稳定**执行」。对应到本项目 —— **这张表是本文的结论**：

| 目标 | 手段 | 状态 |
| --- | --- | --- |
| 自动 | push / PR 触发 CI，前后端门禁全自动 | ✅ 已有 |
| 稳定（不假失败） | `PYTHONIOENCODING=utf-8` 修掉 Windows GBK 假失败；**禁止绕道 WSL** | ✅ 已有 |
| 稳定（不假通过） | 「退出码与覆盖率都会骗人」——要求逐段看输出、要求变异验证 | ✅ 已有纪律 |
| 可追溯 | 覆盖率 artifact 留档 14 天 | ✅ 已有 |
| 可锚定 | 基线 tag + 明确的评审 commit 范围 | ✅ 已有（见《基线版本》） |
| **编译** | CI 构建小程序包 | ❌ **缺**（L-7） |
| **静态扫描** | SonarCloud 真实扫描 | ⚠️ **接了线没通电**（L-2） |
| **禁止未评审合并** | `Require approvals` | ⚠️ **可配但未配**（L-9） |
| 待补 | 墙钟抖动（L-6）、前端覆盖率阈值（L-3）、T0 接口层达标（L-8） | ⏳ 已登记 |

### 8.1 一句话结论

课程第 2 步的三项主要工作，**没有全部完成**：

| 课程要求的「主要工作」 | 完成度 |
| --- | --- |
| 确定分支策略（feature → develop/main） | ⚠️ **部分** —— 实际是 `master` + `dev` + 历史短期分支；**没有 develop / main**（§1.1） |
| 配置保护分支：禁止未通过 CI 合并 | ✅ 已生效 |
| 配置保护分支：禁止**未评审**合并 | ⚠️ **可做但没配**（§2.2） |
| 搭建 CI：**编译** | ❌ **缺失**（§3.1） |
| 搭建 CI：单元测试 | ✅ |
| 搭建 CI：覆盖率统计 | ✅ 全量 + 增量 + T0 三档，已实测 |
| 搭建 CI：Lint | ✅ ruff（format/check）+ eslint |
| 搭建 CI：**SonarQube 静态扫描** | ⚠️ **接了线没通电**（§5.1） |

**3 项达成、4 项未达成或只完成一半。** 未达成的每一项都在上文写清了**具体缺什么、为什么、谁来补**，
没有一项被记成「已完成」。
