# 前端开发规范（miniprogram）

> 本项目小程序（UniApp + Vue 3 + Pinia）的开发规范索引。
> **事实源**：`miniprogram/src/**`、`miniprogram/package.json`、`miniprogram/.eslintrc.cjs`、`miniprogram/tsconfig.test.json`
> **最后核对**：2026-11-17
> **核对方式**：逐份文档对照 `miniprogram/src` 真实文件树与 `pnpm run lint` / `type-check` / `test:cov` / `build:mp-weixin` 结果核对。

---

## 概览

本项目采用 UniApp + Vue 3 (Vite + TypeScript) + Pinia 构建，整体视觉采用温润学术/纸质阅读风（`docs/DESIGN.md` 与 `App.vue` 全局 `--color-*` 变量一致）。
主包聚焦 3 个核心 Tab（工作台、学情、我的）+ 1 个登录页，业务拆分为 material（资料详情/出题，共 2 页）、practice（沉浸作答，1 页）、report（结果页与诊断报告，1 页）三个分包，合计 **8 个注册页面 + 25 个自定义 `.vue` 组件（全部单文件 `<= 300` 行）**。

工程现状（2026-11-17 核对值）：

- **零冗余第三方 UI 库**：已彻底清退未使用的 `wot-design-uni`、`unocss` 与 `prettier` 插件；全部页面与组件采用自定义 `.vue` SFC + `src/styles/{tokens,modal,common}.scss` 与 `App.vue` `--color-*` 设计 Token（业务 CSS 规则零裸 Hex、零 Emoji、固定底栏全量适配 `env(safe-area-inset-bottom)`）。
- **按域模块化类型与 API**：`src/types/` 与 `src/api/modules/` 按业务域（auth/folder/material/knowledge/question/practice/diagnosis/wrong）拆分，由 `src/types/index.ts` 与 `src/api/index.ts` 提供轻量 barrel 聚合导出。
- **跨页共享底座**：`src/components/` 包含 `AiCoachDrawer.vue`、`CoachMessageList.vue`（`virtualHost: true` + `compact` 紧凑排版 + 上下文隔离）、`RichContent.vue`（零外部依赖富文本/公式/表格 AST 渲染，支持 LaTeX 矩阵/分段环境与 GFM 管道表格）与 `BackgroundTaskBar.vue`（全局非阻塞后台任务条）。
- 全局状态为 **6 个 Pinia store**：`auth` / `material` / `folder` / `practice` / `diagnosis` / `backgroundTask`。
- **单元测试与类型全覆盖**：共 **28 个 spec 文件 / 239 个用例**（全部位于 `miniprogram/tests/`），且通过 `tsconfig.test.json` 纳入 `pnpm run type-check` 静态类型检查。

---

## 规范索引

| 模块 | 职责与规范覆盖 | 核心文件与事实源 | 最后核对 |
| --- | --- | --- | --- |
| 目录架构 | 3-Tab 主包 + 3 业务分包、别名与构建配置 | `src/pages.json`、`src/main.ts`、`vite.config.ts`、`tsconfig.json` | 2026-09-29 |
| 类型安全 | 单一类型文件 + `Wire*` / 适配器归一化边界 | `src/types/index.ts`、`src/api/adapters/*`、`tsconfig.json`、`.eslintrc.cjs` | 2026-09-29 |
| 组件规范 | 自定义 SFC 组件、props/emits 约定、共享 SCSS | `src/components/AiCoachDrawer.vue`、`src/subpackages/*/components/*`、`src/pages/review/components/*` | 2026-09-29 |
| 状态管理 | 5 个域 store 的职责与网络调用边界 | `src/stores/{auth,material,folder,practice,diagnosis}.ts` | 2026-09-29 |
| 组合式函数 | `useQuestionCompose` 的契约与命名约定 | `src/subpackages/material/composables/useQuestionCompose.ts` | 2026-09-29 |
| 网络与契约 | `uni.request` 封装、两档超时、结构化 `RequestError`、query 串由调用方拼装、`fail` 兜底 | `src/utils/request.ts`、`src/utils/requestError.ts`、`src/api/index.ts`、[network-contract.md](./network-contract.md) | 2026-09-29 |
| 请求体语义 | 写入类接口的字段语义陷阱（`POST /practices` 的 `question_ids`/`question_count` 等**静默**行为） | `backend/app/schemas/practice.py`、`backend/app/services/practice.py`、[api-payload-contracts.md](./api-payload-contracts.md) | 2026-09-29 |
| 个人页统计 | 用户级资料总量、未分类/归档口径、加载失败与页面刷新 | `src/pages/profile/`、`src/api/index.ts`、[个人页统计契约](../backend/material-statistics.md) | 2026-10-04 |
| 质量门禁 | ESLint（`any` 已关闭）+ vue-tsc + Vitest | `package.json`、`.eslintrc.cjs`、`vitest.config.ts`、`tests/*.spec.ts` | 2026-09-29 |
| 视觉设计系统 | 温润学术纸质色盘与 `page` 级 CSS 变量 | `src/App.vue`（`--color-*` 变量与 `.paper-card`）、`docs/DESIGN.md` | 2026-09-29 |
| 助教与智能交互 | 全局/局部 AI 助教抽屉，题目级与范围级两个端点 | `src/components/AiCoachDrawer.vue`、`src/api/index.ts` | 2026-09-29 |

---

## 学习闭环流转契约（当前实现）

1. **资料导入与解析**：`pages/index/index` 支持课程文件夹管理与筛选；上传经 `materialStore.upload` → `apiUploadMaterial` → `uploadFile`，成功后跳 `subpackages/material/pages/course/index?id=<materialId>`。在讲义卡片或 course 页手动触发 `POST /materials/{id}/parse`（门禁见 `src/utils/materialState.ts::canStartMaterialParse`），由 `useBackgroundTaskStore` 经分阶段退避轮询（覆盖 `>= 15` 分钟，超时可点「刷新进度」续查，`onShow` 非 `ready` 态主动同步）追踪到终态（`ready` / `failed` / `retake_required`），就绪后展示扁平化的知识点列表与原文切片溯源（切片经 `GET /knowledge/{id}/snippets` 拉取）。
2. **多考点多题型出题**：`course/index` 或 `questions/index` 支持通过 `KnowledgePointPickerDrawer` 手风琴抽屉多选考点并勾选题型。`src/types/index.ts` 的 `QuestionType` 联合为 **7 种**：`single_choice` / `multiple_choice` / `true_false` / `fill_in_blank` / `term_explanation` / `short_answer` / `case_analysis`（主观题集合由 `SUBJECTIVE_QUESTION_TYPES` 标注）。组卷默认走「按题量智能抽考」（`smart_sample`：跨讲义均匀抽取 `questionCount` 个代表性考点出题，覆盖率按目标抽样考点核算），也支持切到「全考点逐一覆盖」（`full_coverage`：超出 `MAX_QUESTION_BATCH = 20` 时按 `planGenerationBatches` 拆批调 `POST /questions/jobs`，且翻页拉全避免 50 题截断），未覆盖目标考点必须先补齐才能开始作答（`compose.canStart`）。
3. **沉浸练习与作答草稿**：`questions/index` 的「开始作答」经 `practiceStore.initPractice(undefined, params)` → `POST /practices` 后跳 `subpackages/practice/pages/session/index?practice_id=<id>`。作答写入走 `practiceStore.recordAnswer`：先写内存 + `uni.setStorageSync('practice_draft_<userId>_<practiceId>')`，再入 `src/utils/draftQueue.ts` 的串行队列异步写后台。队列语义为**同题串行、快速输入只保留最后值、失败进入 `draftFailures` 且页面顶部给出可见重试入口、交卷前必须 `flush()` 成功**。
4. **交卷 → 判题中 → 正式诊断**：点击交卷调用 `practiceStore.submit()`（先 flush 全部在途草稿，失败则抛错不提交；成功后复用同一 `Idempotency-Key` 调用 `POST /practices/{id}/submit`），随后 `uni.redirectTo` 到 `subpackages/report/pages/detail/index?practice_id=<id>`。结果页**不直接展示诊断报告**：它先渲染逐题判题进度，仅当 `session.completed_at` 非空且 `status === 'completed'`（`summarizeProgress().fullyGraded`）时才由 `diagnosisStore.loadReport` 调用 `POST /practices/{id}/diagnosis` 触发/取回正式报告。**未判定题目不得显示为零分或答错**：`buildAttemptResults` 把未判项标为 `grading` / `pending_regrade` 且 `score`/`isCorrect` 保持 `null`，`resolveResultBadge` 渲染为「判题中 / 待重判」。`partially_graded` 提供 `POST /practices/{id}/regrade` 主动重试判题；主观题的复查/自评分别走 `POST /grading/regrade` 与 `POST /grading/self-evaluate`；错题知识点可经 `practiceStore.regenerateFromWrongPoints` 一键再生题（范围必须且只能落在单一课程或单一未分类资料）。
5. **AI 助教答疑**：`src/components/AiCoachDrawer.vue` 提供两种调用形态——带 `questionId` 时走 `POST /questions/{id}/ask-coach`（可携带 `user_answer` / `grading_points`），否则需至少提供 `folderId` / `materialId` / `knowledgePointId` 之一并走 `POST /coach/ask`（范围级答疑，返回 `sources` 引用切片，可跳转来源讲义）。挂载点：`pages/index/index`（课程随身助教）、`subpackages/material/pages/course/index`（讲义/考点助教）、`subpackages/report/pages/detail/index`（逐题助教）。

---

## 历史偏离清零记录（2026-11-17 重构已全部消除）

- **单文件行数门禁**：全仓 32 个 `.vue` 文件已全部收敛至 **`<= 270` 行**（符合 `docs/DESIGN.md` `<= 300` 行硬性约定）；`src/api/` 与 `src/types/` 已按域拆分（最大 `.ts`/`.scss` 单文件 `<= 235` 行）。
- **零表情包与设计 Token 一致性**：`src/**/*.vue` 已清零全部 Unicode Emoji；业务 CSS 规则已清零裸 Hex 字面量（全仓 387 处统一走 `var(--color-*)`）；全部固定底栏已补齐 `env(safe-area-inset-bottom)` 安全区适配。
- **死资产清退**：`src/subpackages/material/pages/upload/index.vue` 死占位页与 7 个无用 npm 包已彻底移除。
