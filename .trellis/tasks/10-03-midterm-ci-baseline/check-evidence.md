# 检查取证（Phase 2.2）与 spec 更新判定（Phase 3.3）

> 任务：`10-03-midterm-ci-baseline`
> 执行日期：2026-10-03

## 1 Phase 2.2 质量检查结果

| 检查项 | 方法 | 结果 |
| --- | --- | --- |
| `verify.yml` 语法 | `yaml.safe_load` | **通过**；jobs = `backend`(10 步) / `frontend`(8 步) / `sonar`(4 步, needs=[backend,frontend]) |
| `Taskfile.yml` 语法 | `yaml.safe_load` | **通过**；`verify-backend` 末条与 CI 逐字一致 |
| 门禁镜像一致性 | 对比 `Taskfile.yml` 与 `verify.yml` | **逐字一致**（后端 pytest 串、前端 lint/type-check/test:cov） |
| `sonar-project.properties` | 字段完整性检视 | 12 个有效键，覆盖 host/project/sources/tests/coverage/exclusions |
| lockfile 兼容性 | `grep lockfileVersion` + `git diff --numstat` | `9.0` **未变**；`107 insertions / 0 deletions`（纯新增） |
| 依赖版本 | 比对 `vitest` 与 `@vitest/coverage-v8` | 锁定解析值均为 `1.6.1` |
| 真名闸门 | `.git/hooks/zhilian-name-guard.sh` 扫描全部新增/修改文件 | **0 命中** |
| 引用死链 | 逐个 `[ -e ]` 核对 24 个被引用路径 | 22/22 存在的全部 OK；2 项为**运行产物路径**（`backend/coverage.xml`、`miniprogram/coverage/`），本就尚未生成 |
| 未产生提交 | `git log -1` / `git status --porcelain` | HEAD 仍为 `e1cef6d`；仅 `M`/`??`，**无新提交** |
| 远程 tag 现状 | `git ls-remote --tags origin` | 输出为空 → 远程无 tag（已写入《基线版本》§7.3） |

### 1.1 关于「跑不跑 `task verify`」的判定

**结论：不跑，且这不是省事。**

1. **后端**：本次未改动任何后端 `.py` 文件，后端门禁结果不可能受到影响。
2. **前端**：门禁命令已由 `test:unit` 改为 `test:cov`，但**本机 `node_modules` 未安装
   `@vitest/coverage-v8`**（刻意用 `--lockfile-only` 规避本机杀软对 pnpm 的干扰）。
   此时跑 `task verify-frontend` 只会得到「模块缺失」这一**预期内**结果，
   不构成任何有效证据——它证明的是环境未同步，不是代码有问题。
3. **CI 侧**：`pnpm install --frozen-lockfile` 会按更新后的 lockfile 正常装上该依赖。

**因此本次的验证边界是：配置的语法正确性 + 门禁镜像一致性 + 待跑前置条件已明确登记（L-4）。**
真实运行证据需由用户在 `pnpm install` 后取得，或推送后由 GitHub Actions 提供。

## 2 Phase 3.3 spec 更新判定

**判定：本次不直接改 `.trellis/spec/`，把两条新知识登记为待办。**

| 问题 | 判断 |
| --- | --- |
| 是否产生新知识？ | **是**。① CI 门禁命令的**唯一事实源**关系（`Taskfile.yml` ↔ `verify.yml` 必须逐字一致，改动需成对）；② 覆盖率留档与 artifact 约定；③ 本机 pnpm 版本（12）与 CI（10）不一致时，用 `--lockfile-only` + 校验 `lockfileVersion` 的**安全改依赖**做法。 |
| 是否该在本任务落库？ | **否**。约束 C-5 限定不改 `.trellis/spec/` 与既有 `docs/`；且本项目已有先例——spec 刷新是独立任务（`09-28-refresh-trellis-spec`）。 |
| 落库建议 | 并入第 1 步已登记的 spec 刷新任务：新增「门禁命令成对修改」纪律到 `.trellis/spec/guides/`；在 frontend spec 补一条「vitest 覆盖率接入方式」。 |

## 3 遗留与交接

| 项 | 交接状态 |
| --- | --- |
| 基线 tag（`midterm-baseline-2026-10-03`） | **待用户执行**（本次不提交，约束 C-2），命令见《基线版本》§2 |
| SonarCloud 授权与两个占位符回填 | **待用户执行**，六步见《环境与CI准备》§5.2 |
| 本地 `pnpm install`（装上新增依赖） | **待用户执行**，之后 `task verify-frontend` 才可本地跑通 |
| 在真实 Actions 上验证新 job | 推送后自动发生（L-1） |
| 前端覆盖率阈值定档 | M0-2（取实测值后） |
| `diff-cover` 增量门禁接线 | 后续任务（《单测计划》§3.1） |
| spec 刷新 | 独立 spec 任务 |
