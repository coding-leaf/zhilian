# 基线调研：代码规模、改动热度与风险分级

> 任务：`10-03-midterm-quality-prep`（中期质量检查 · 准备与计划）
> 采集时间：2026-10-03
> 采集方式：本机 `git log --name-only` 聚合 + `wc -l` + `Taskfile.yml` 实读
> 用途：为《中期质量计划》《评审清单》《单测计划》《排期表》提供**可定位出处**的依据

## 1 代码规模基线

| 区域 | 目录 | 代码行数 | 说明 |
| --- | --- | ---: | --- |
| 后端 `app/` | 合计 | 40,717 | 仅应用代码，不含 `tests/`、`migrations/` |
| ├ api | `backend/app/api` | 4,101 | v1 路由 + deps |
| ├ core | `backend/app/core` | 7,047 | errors / security / algorithms |
| ├ services | `backend/app/services` | 9,334 | 业务编排，单层最大 |
| ├ repositories | `backend/app/repositories` | 4,168 | 数据访问 |
| ├ schemas | `backend/app/schemas` | 2,773 | 对外契约 |
| ├ models | `backend/app/models` | 2,373 | ORM |
| └ integrations | `backend/app/integrations` | 7,095 | llm / ocr / embedding / storage / queue / search / idempotency |
| 前端 `src/` | `miniprogram/src` | 8,927 | .vue + .ts 合计 |

**测试规模（本机实测，2026-10-03）**

| 端 | 文件数 | 用例计数方式 | 计数 |
| --- | ---: | --- | ---: |
| 后端 | 91 个 `test_*.py` | `grep -rho "def test_" backend/tests \| wc -l` | 1,383 |
| 前端 | 14 个 `*.spec.ts` | `grep -rho "it(\|test(" miniprogram/tests/*.spec.ts \| wc -l` | 129 |

> ⚠️ **基线漂移（需在中期检查中重新基线化）**：`docs/开发过程文档.md` 5.2 节记载
> 「后端测试文件/函数 91/548、前端测试文件/用例 13/125」，与本机实测（91 文件、
> 前端 14 文件/129 用例）不一致；`.trellis/spec/frontend/quality-guidelines.md` 又记
> 「9 个 spec / 69 用例」。三处数字互不相同 —— 说明文档里的测试规模数字**已过期**。
> 中期检查第一步应把它重新基线化，并把"数字只从实时命令取、不在文档里手抄"写成纪律。

## 2 改动热度（churn）——「修改频繁模块」的客观定义

取全历史 `git log --pretty=format: --name-only` 的文件出现次数 Top 30（已剔除纯文档/日志）：

| 排名 | 文件 | 改动次数 | 所属层 |
| ---: | --- | ---: | --- |
| 1 | `backend/app/core/errors.py` | 16 | 后端核心 |
| 2 | `backend/app/services/question.py` | 14 | 后端服务 |
| 3 | `miniprogram/src/utils/request.ts` | 12 | 前端网络出口 |
| 4 | `miniprogram/src/pages/index/index.vue` | 12 | 前端主页面 |
| 5 | `backend/app/services/practice.py` | 12 | 后端服务 |
| 6 | `backend/app/schemas/practice.py` | 11 | 后端契约 |
| 7 | `miniprogram/src/types/question.ts` | 10 | 前端类型 |
| 8 | `backend/tests/unit/services/test_question_service.py` | 10 | 后端测试 |
| 9 | `backend/app/services/material.py` | 10 | 后端服务 |
| 10 | `backend/app/schemas/question.py` | 10 | 后端契约 |
| 11 | `backend/app/repositories/material.py` | 10 | 后端数据访问 |
| 12 | `backend/app/core/algorithms/__init__.py` | 10 | 后端算法核 |
| 13 | `miniprogram/src/types/report.ts` | 9 | 前端类型 |
| 14 | `miniprogram/src/types/practice.ts` | 9 | 前端类型 |
| 15 | `miniprogram/src/subpackages/report/pages/detail/index.vue` | 9 | 前端报告页 |
| 16 | `miniprogram/src/subpackages/material/pages/questions/index.vue` | 9 | 前端出题核对页 |
| 17 | `miniprogram/src/pages.json` | 9 | 前端路由表 |
| 18 | `miniprogram/src/api/material.ts` | 9 | 前端 API |
| 19 | `miniprogram/src/api/index.ts` | 9 | 前端 API |
| 20 | `backend/app/api/v1/questions.py` | 9 | 后端路由 |

**结论**：改动最频繁的 20 个文件里，**17 个落在后端 service/schema/repository/core 与前端
网络层/主页面/出题页/报告页** —— 与「核心业务」高度重合。churn 与"核心"两条线指向同一批
文件，评审范围优先级因此可以直接由它们确定，不必另造标准。

## 3 风险分级（评审范围的初稿）

| 级别 | 判定依据 | 模块（后端） | 模块（前端） |
| --- | --- | --- | --- |
| **T0 高危**<br>（双人评审） | 命中 churn Top20 **且** 在主链路上 **且** 编译器管不到（算法/鉴权/错误契约） | `core/algorithms/`、`core/errors.py`、`core/security.py`、`api/deps/`、`services/{material,question,practice}.py`、`repositories/material.py`、`api/v1/{questions,materials,practices}.py` | `utils/request.ts`、`stores/{practice,material,diagnosis}.ts`、`api/adapters/*`、`pages/index/index.vue`、`subpackages/material/pages/questions/index.vue`、`subpackages/report/pages/detail/index.vue` |
| **T1 重要**<br>（单人评审） | 契约与类型边界，错一处会跨层静默失效 | `schemas/*`、`repositories/*`（除 material）、`models/*` | `types/*`、`api/index.ts`、`api/material.ts`、`pages.json`、`pages/review/index.vue` |
| **T2 一般**<br>（抽检） | 配置、文档、无业务逻辑 | `cli/`、`integrations/*` 的 fake 实现 | `utils/materialState.ts` 等纯函数 |

**T0 的"编译器管不到"三个具体风险点**（来自 `docs/团队分工.md` 第 4 节，非本文新造）：

1. 算法核错误 → 判分与掌握度**悄悄偏掉**，不报错；
2. 鉴权/用户隔离错误 → **越权访问他人学习资料**；
3. 错误契约（`core/errors.py`）→ 上游真实原因在接口层被丢掉（见 `docs/后续待解决问题.md` P0-2 附带发现）。

## 4 已知缺陷与偏离（评审的既有输入，不需重新发现）

| 编号 | 内容 | 级别 | 出处 |
| --- | --- | --- | --- |
| P0-1 | 解析流水线卡死且不可恢复 | 阻塞 | `docs/后续待解决问题.md` §一 |
| P0-2 | 思考模式模型上结构化输出不可用 | 阻塞 | 同上 |
| P1-3 | 出题链路没有反馈（`isConfigMode` 死代码） | 阻断体验 | 同上 |
| P1-4 | 个人页学习足迹统计口径漏算 | 数据错误 | 同上 |
| P1-5 | 举一反三高估覆盖率（会误导用户） | 误导 | 同上 §二 |
| P2-6 | 「没有数据」与「加载失败」不可区分 | 误导 | 同上 |
| P2-7 | 题库 Tab 重定义暂缓（R1–R6） | 未做 | 同上 |
| D-1 | 客观题是否改为交卷时同步判 | 待决策 | 同上 §四 |
| E-1 | 4 处墙钟微基准断言抖动 | 门禁噪音 | `AGENTS.md` + 同上 §五 |
| E-2 | 退出码与覆盖率都会骗人（排除清单） | 纪律 | `docs/开发过程文档.md` 4.6 / 6.x |

前端「已知偏离」（来自 `spec/frontend/quality-guidelines.md` 末章）：
3 个超标 `.vue` 未拆分、约 361 处裸 Hex（设计 token 未收敛）、19 行 Emoji（零表情包未落地）、
无组件挂载测试、`upload/index.vue` 为 32 行占位页。

## 5 门禁现状（准出标准的既有底盘）

`Taskfile.yml` 实读：

```
task verify-backend : ruff format --check . → ruff check . → mypy app → lint-imports
                      → pytest tests --cov=app --cov-branch --cov-fail-under=80
task verify-frontend: pnpm run lint → pnpm run type-check → pnpm run test:unit
task verify         : verify-backend + verify-frontend
```

| 事实 | 值 | 出处 |
| --- | --- | --- |
| 后端覆盖率门禁 | **全量** ≥ 80%（实际 91%+） | `Taskfile.yml` / `开发过程文档.md` 5.1 |
| 前端覆盖率门禁 | **不存在**（vitest 未配 coverage，`package.json` 无 coverage 依赖） | `miniprogram/vitest.config.ts` / `package.json` 实读 |
| 后端静态扫描 | ruff + mypy(strict) + import-linter（5 条架构契约） | `Taskfile.yml` |
| 安全扫描依赖 | `bandit` / `pip-audit` 已在 `dev` 依赖中但**未进门禁** | `backend/pyproject.toml` 29–36 行 |
| 算法核覆盖率 | 9 个纯函数模块，**分支覆盖率 100%** | `开发过程文档.md` 5.2 |
| CI | `.github/workflows/verify.yml`，push/PR 触发 | 同上 5.1 |
| 分支保护 | `master`：必需状态检查 + 禁直推 + 禁强推/删除；**不含必需评审**（单账号自锁） | 同上 6.1 |

## 6 对「准备与计划」的直接输入

1. **评审范围**不必从零扫：T0 名单 = churn Top20 ∩ 主链路 ∩ 编译器盲区。
2. **准出标准**必须补两件现有门禁没有的东西：① 前端覆盖率工具；② 增量覆盖率口径。
3. **单测计划**要正面处理 E-1 墙钟抖动，否则"通过率 100%"无法稳定取证。
4. **排期**按主链路 8 节点切片，使每个里程碑都能端到端验收，而不是按文件分堆。
5. **基线数字**（测试规模/覆盖率）必须先重新基线化再写进计划，避免又一次"文档抄数字"。
