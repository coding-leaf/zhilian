# PRD：中期质量检查 · 环境与 CI 准备

> 任务：`10-03-midterm-ci-baseline`
> 对应课程要求：中期质量检查 **第 2 步「环境与 CI 准备」**
> 编制日期：2026-10-03

## Goal

让单元测试与代码评审**能自动、稳定执行**，并为本次评审提供**可锚定的基线版本**。

课程列出的五项工作与仓库现状的差距见 `research/ci-and-baseline-facts.md` §3（G-1 ~ G-6）。
一句话概括：**底盘已有（CI 能跑、保护已配、测试替身齐备），缺的是「覆盖率留档、静态扫描、模板落地、基线锚点」四件。**

## Requirements

### 范围

| 项 | 交付形态 |
| --- | --- |
| 覆盖率留档 | CI 产出 `coverage.xml` / `lcov.info` 并上传 artifact |
| SonarCloud 静态扫描 | `sonar-project.properties` + CI `sonar` job |
| PR/MR 模板 | `.github/PULL_REQUEST_TEMPLATE.md`（GitHub 自动套用） |
| 前端覆盖率能力 | `vitest.config.ts` coverage 配置 + `test:cov` 脚本 + 依赖声明 |
| 基线版本与评审范围 | `中期质量检查/基线版本.md`（含 tag 命令，**不代为执行**） |
| 依赖环境与可重复运行 | `中期质量检查/环境与CI准备.md` |
| 索引 | 更新 `中期质量检查/README.md` |

**不在范围**：

- 不引入 `develop` / `main`（用户决策：沿用单 `master`）。
- 不启用「必需评审人批准」——单账号仓库下不可执行，会锁死 `master`；维持组织层约定。
- 不改后端覆盖率口径（仍为全量 ≥80%）；**增量口径**属第 1 步《单测计划》§3 的后续任务。
- 不给前端设覆盖率阈值，只统计与留档（理由见 research §4 R-3）。
- 不修改既有 `docs/` 文档（含《开发过程文档》《团队分工》）。
- 不执行任何 git 写操作（见 Constraints C-2）。

### R1 覆盖率留档（G-1）

后端 `pytest` 增加 XML 报告输出并上传 artifact；前端产出 `lcov` 并上传 artifact。

- R1.1 backend job 生成 `backend/coverage.xml` 并 `upload-artifact`。
- R1.2 frontend job 生成 `miniprogram/coverage/lcov.info` 并 `upload-artifact`。
- R1.3 本地等价命令可复现：`task verify-backend` 仍按原样通过（**不新增本地强制项**）。

### R2 SonarCloud 静态扫描（G-2）

- R2.1 新增 `sonar-project.properties`，声明 `sonar.projectKey` / `sonar.organization` / `sonar.sources` / 覆盖率报告路径 / 排除清单。
- R2.2 `verify.yml` 新增 `sonar` job，`needs: [backend, frontend]`，`fetch-depth: 0`。
- R2.3 **未配置 `SONAR_TOKEN` 时该 job 仍为绿色**（输出 notice 并跳过扫描）。
- R2.4 配置方式与授权步骤写成文档，用户可照做。

### R3 PR/MR 模板落地（G-4）

- R3.1 `.github/PULL_REQUEST_TEMPLATE.md` 存在，内容与 `中期质量检查/templates/PR-MR模板.md` 同源。
- R3.2 保留七小节结构（变更目的与关联任务 / 变更内容 / 影响面自查 / 验证方式与证据 / 风险与回滚方案 / 自查清单 / 评审关注点）。
- R3.3 **零真名**（闸门 0 命中）。

### R4 前端覆盖率能力（G-3）

- R4.1 `miniprogram/package.json` 声明 `@vitest/coverage-v8`（版本与 `vitest` 一致）。
- R4.2 `pnpm-lock.yaml` 已同步，且 `lockfileVersion` 保持 `9.0`（兼容 CI 的 pnpm 10）。
- R4.3 `vitest.config.ts` 增加 `test.coverage` 配置：`provider: 'v8'`、`reporter: ['text','lcov']`、含排除清单。
- R4.4 新增 `test:cov` 脚本；**原有 `test:unit` 行为不变**（CI 现有步骤不受影响）。

### R5 基线版本与评审范围（G-5）

- R5.1 `中期质量检查/基线版本.md` 给出基线 tag 名、目标 commit、命令。
- R5.2 明确评审 commit 范围，且**范围数字附取得命令**。
- R5.3 文档**明确标注 tag 尚未执行**（由用户执行），不得写成已完成。

### R6 依赖环境与可重复运行（G-6）

- R6.1 `中期质量检查/环境与CI准备.md` 写明：外部能力替身清单、夹具位置、默认运行依赖（无 DB / 无网络）、如何本地复现 CI。
- R6.2 说明分支策略现状与保护规则现状，并**如实标注「必需评审不可执行」**。

### R7 索引

- R7.1 `中期质量检查/README.md` 收录第 2 步两份文档，阅读顺序与目录结构同步更新。

## Acceptance Criteria

- [ ] **AC-1.1** `verify.yml` 的 backend job 生成 `backend/coverage.xml` 并 `upload-artifact`。
- [ ] **AC-1.2** frontend job 生成 `miniprogram/coverage/lcov.info` 并 `upload-artifact`。
- [ ] **AC-1.3** `task verify-backend` 对应的本地命令未变（`Taskfile.yml` 的 verify 任务只增不改）。
- [ ] **AC-2.1** `sonar-project.properties` 存在且字段完整。
- [ ] **AC-2.2** `sonar` job 存在、`needs` 正确、`fetch-depth: 0`。
- [ ] **AC-2.3** 无 `SONAR_TOKEN` 时 sonar job 绿色（逻辑可静态检视）。
- [ ] **AC-2.4** 授权步骤文档存在且可照做。
- [ ] **AC-3.1** `.github/PULL_REQUEST_TEMPLATE.md` 存在。
- [ ] **AC-3.2** 七小节结构完整。
- [ ] **AC-3.3** 真名闸门 0 命中。
- [ ] **AC-4.1** `@vitest/coverage-v8` 已声明，版本 `1.6.1`（与 `vitest@1.6.1` 一致）。
- [ ] **AC-4.2** `lockfileVersion` 仍为 `9.0`。
- [ ] **AC-4.3** `vitest.config.ts` 含 `test.coverage`。
- [ ] **AC-4.4** `test:cov` 存在，`test:unit` 未变。
- [ ] **AC-5.1** `基线版本.md` 含 tag 名与命令。
- [ ] **AC-5.2** 评审范围数字附命令。
- [ ] **AC-5.3** 文档标注 tag 未执行。
- [ ] **AC-6.1** `环境与CI准备.md` 含六项说明。
- [ ] **AC-6.2** 如实标注「必需评审不可执行」。
- [ ] **AC-7.1** `README.md` 索引已更新。

## Constraints

| 编号 | 约束 |
| --- | --- |
| C-1 | 仓库公开，**任何进仓库的内容不得含真实姓名**（沿用四代号） |
| C-2 | **只出文件**：不执行 `git commit` / `push` / `tag` / 任何远程操作 |
| C-3 | CI 命令继续**精确镜像** `Taskfile.yml`，不另立第二套门禁 |
| C-4 | 不引入会让当前 CI 变红的硬阈值（前端覆盖率**只统计不设阈值**） |
| C-5 | 不修改既有 `docs/` 文档；不修改 `AGENTS.md` |
| C-6 | 遵守 `AGENTS.md`：**禁止经由 WSL 执行**；不触碰 `tests/unit/core/algorithms/` 的墙钟阈值 |

## Notes

### 不补缺口的后果

| 缺口 | 后果 |
| --- | --- |
| G-1 | 覆盖率只说在日志里；评审无法看趋势，「覆盖率准出」无法判真 |
| G-2 | 课程要求项直接缺失 |
| G-3 | 「新增代码覆盖率」在前端永远无法取证 |
| G-4 | 每份 PR 描述靠人自由发挥，评审要点散落 |
| G-5 | 评审范围无锚点，「本次评审了哪些提交」说不清 |

### 完成定义（DoD）

1. R1 ~ R7 全部满足；
2. 真名闸门对全部新增/修改文件 **0 命中**；
3. `verify.yml` 通过 YAML 语法校验，`sonar-project.properties` 通过 properties 语法校验；
4. `git status` 显示**无任何新提交**（工作区文件改动，由用户自行提交）；
5. 与 `AGENTS.md`、`Taskfile.yml`、既有 `docs/` 文档**无口径冲突**。
