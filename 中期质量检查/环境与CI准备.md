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

**采用单 `master` + 短期分支**，不引入 `develop` / `main`（2026-10-03 决策）。

| 项 | 约定 |
| --- | --- |
| 长期分支 | `master`（唯一集成分支） |
| 短期分支 | `类型/任务编号-短描述`，如 `feature/ZL-150-midterm-ci-baseline` |
| 合并路径 | `feature/* → PR → master` |
| 合并方式 | **保留合并提交**，不用 squash（使分支结构在 `git log --graph` 中可见） |
| 提交信息 | `类型(scope): 一句话说明`，scope 只取词表：`api` / `services` / `algorithms` / `integrations` / `models` / `miniprogram` / `deploy` / `ci` / `docs` |

**为什么不改成 `main` + `develop`**：文档《代码管理工作介绍 V1.0》第 3 章确实定义了精简 Git Flow，
但本仓库的偏差是**有起点的历史**——`docs/开发过程文档.md` §6.1 已如实记录，且 §6.2 明确
「历史分支不追溯改名——改写已公开历史的风险大于收益」。引入 `develop` 需要改默认分支、
改保护规则、改 CI 触发分支，风险集中在收益不明的结构性重构上，本次不做。

## 2 保护分支

### 2.1 现状（已启用）

`master` 上的保护规则为：

| 规则 | 状态 |
| --- | --- |
| 必需状态检查（`verify` 全绿） | ✅ 已启用 |
| 禁止直接推送 | ✅ 已启用 |
| 禁止强推（force push） | ✅ 已启用 |
| 禁止删除分支 | ✅ 已启用 |
| **必需评审人批准** | ❌ **不可执行** —— 见 2.2 |

### 2.2 「必需评审人批准」为何不可执行

本项目在 GitHub 上目前**只有一个协作账号**，而 GitHub **不允许 PR 作者批准自己的 PR**。
若启用「必需评审人批准」，本仓库的 PR 将**永远无法满足合并条件**——等于把 `master` 锁死。

因此评审要求作为**组织层约定**由团队内部执行（见 `docs/团队分工.md`），不在服务端强制。

> **这一条不隐瞒**：它不是「做到了」，而是「当前形态下不可执行」。
> 这是 `docs/开发过程文档.md` §6.1 已有的记录，本次维持不变。

**可行的替代补偿**（已在本次 CI 中落地）：把**能自动化的部分全部自动化**——
静态检查、类型检查、架构契约、单元测试、覆盖率门槛、静态扫描。
人手评审覆盖「机器看不见的部分」（接线是否正确、归因是否成立），
机器门禁覆盖「人容易漏的部分」。两者互补，而不是用一个假装成另一个。

### 2.3 若要调整保护规则（手工步骤）

GitHub → 仓库 `Settings` → `Branches` → `Branch protection rules` → `master`：

1. 确认勾选 **Require status checks to pass before merging**，并把 `verify` 加入必需检查；
2. 确认勾选 **Do not allow bypassing the above settings**；
3. **不要**勾选 `Require approvals`（原因见 2.2）；
4. 建议勾选 **Require conversation resolution before merging**（评审意见闭环的机器抓手）。

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
3. **无墙钟依赖**——除 4 处已知的算法核微基准断言外（见 §7），用例不依赖真实时间。

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

### 5.1 已完成（仓库侧）

- `sonar-project.properties`（仓库根）：声明源码/测试路径、覆盖率报告路径、排除清单；
- `.github/workflows/verify.yml` 的 `sonar` job：依赖前后端 job，消费 artifact 后扫描。

**设计要点**：`fetch-depth: 0` 是必需的——SonarCloud 需要完整历史来判定「新代码」，
浅克隆会让新增代码覆盖率失真。

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

| 编号 | 限制 |
| --- | --- |
| L-1 | **新增 CI job 未在真实 GitHub Actions 上跑过**。本次只出文件、不推送，且 `sonar` job 在无 token 时短路，故其正确性目前**只有静态检视证据**，没有运行证据 |
| L-2 | `sonar-project.properties` 的 `organization` / `projectKey` 为**占位符**，需用户回填 |
| L-3 | 前端覆盖率**只有报告、无阈值**，暂不能作为准出判据。首次接入无历史基线，直接设阈值会让 CI 立刻红灯——阈值待 M0 基线化后定（见《单测计划》M0-2） |
| L-4 | 本机 `node_modules` **未安装** `@vitest/coverage-v8`（刻意用 `--lockfile-only` 规避杀软干扰），本地 `test:cov` 需先 `pnpm install` |
| L-5 | **增量覆盖率门禁（`diff-cover`）仍未接入**，属后续任务（《单测计划》§3.1 已给方案） |
| L-6 | `tests/unit/core/algorithms/` 的 4 处墙钟断言在全量套件下仍会抖动——既有测试设计问题，`AGENTS.md` 已定案**不放宽阈值**，本次不动 |

## 8 与「稳定执行」的关系

课程要求「让单元测试和代码评审能自动、**稳定**执行」。对应到本项目：

| 目标 | 手段 | 状态 |
| --- | --- | --- |
| 自动 | push / PR 触发 CI，前后端门禁全自动 | ✅ 已有 |
| 稳定（不假失败） | `PYTHONIOENCODING=utf-8` 修掉 Windows GBK 假失败；**禁止绕道 WSL** | ✅ 已有 |
| 稳定（不假通过） | 「退出码与覆盖率都会骗人」——要求逐段看输出、要求变异验证 | ✅ 已有纪律 |
| 可追溯 | 覆盖率 artifact 留档 14 天 + SonarCloud 趋势 | ✅ 本次新增 |
| 可锚定 | 基线 tag + 明确的评审 commit 范围 | ✅ 本次新增（见《基线版本》） |
| 待补 | 墙钟抖动（L-6）、增量口径（L-5） | ⏳ 已登记 |
