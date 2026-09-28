# 前端开发规范（miniprogram）

> 本项目小程序（UniApp + Vue 3 + Pinia）的开发规范索引。
> **事实源**：`miniprogram/src/**`、`miniprogram/package.json`、`miniprogram/.eslintrc.cjs`
> **最后核对**：2026-09-29
> **核对方式**：逐份文档对照 `miniprogram/src` 真实文件树与 `pnpm run lint` / `type-check` / `test:unit` 结果核对。

---

## 概览

本项目采用 UniApp + Vue 3 (Vite + TypeScript) + Pinia 构建，整体视觉采用温润学术/纸质阅读风。
主包聚焦 3 个核心 Tab（工作台、学情、我的）+ 1 个登录页，业务拆分为 material（资料导入/解析/出题）、practice（作答与草稿）、report（结果页与诊断报告）三个分包。

工程现状（核对值，非愿景）：

- **依赖里保留 `wot-design-uni`，但业务代码当前零引用**：`pages.json` 的 `easycom` 仍声明 `^wd-(.*)` 规则，实测 `src/**` 中不存在任何 `wd-*` 组件使用点。所有卡片/按钮/抽屉均为自定义 `.vue` + `App.vue` 全局 CSS 类（`.paper-card` / `.paper-btn-primary`）。
- 全局状态为 **5 个 Pinia store**：`auth` / `material` / `folder` / `practice` / `diagnosis`（无 `stores/index.ts` 聚合入口）。
- 组合式函数只有 **1 个**：`subpackages/material/composables/useQuestionCompose.ts`。
- 单元测试 **9 个 spec 文件 / 62 个用例**，全部位于 `miniprogram/tests/`（无 `tests/unit/` 子目录层级）。

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
| 质量门禁 | ESLint（`any` 已关闭）+ vue-tsc + Vitest | `package.json`、`.eslintrc.cjs`、`vitest.config.ts`、`tests/*.spec.ts` | 2026-09-29 |
| 视觉设计系统 | 温润学术纸质色盘与 `page` 级 CSS 变量 | `src/App.vue`（`--color-*` 变量与 `.paper-card`）、`docs/DESIGN.md` | 2026-09-29 |
| 助教与智能交互 | 全局/局部 AI 助教抽屉，题目级与范围级两个端点 | `src/components/AiCoachDrawer.vue`、`src/api/index.ts` | 2026-09-29 |

---

## 学习闭环流转契约（当前实现）

1. **资料导入与解析**：`pages/index/index` 支持课程文件夹管理与筛选；上传经 `materialStore.upload` → `apiUploadMaterial` → `uploadFile`，成功后跳 `subpackages/material/pages/course/index?id=<materialId>`。在讲义卡片或 course 页手动触发 `POST /materials/{id}/parse`（门禁见 `src/utils/materialState.ts::canStartMaterialParse`），随后由 `materialStore.pollMaterialStatus` 轮询到终态（`ready` / `failed` / `retake_required`），就绪后展示扁平化的知识点列表与原文切片溯源（切片经 `GET /knowledge/{id}/snippets` 拉取）。
2. **多考点多题型出题**：`course/index` 或 `questions/index` 支持按考点多选并勾选题型。`src/types/index.ts` 的 `QuestionType` 联合为 **7 种**：`single_choice` / `multiple_choice` / `true_false` / `fill_in_blank` / `term_explanation` / `short_answer` / `case_analysis`（主观题集合由 `SUBJECTIVE_QUESTION_TYPES` 标注）。组卷经 `useQuestionCompose` → `planGenerationBatches` 分批调用 `POST /questions/generate`（单批上限 `MAX_QUESTION_BATCH = 20`），并按「题目快照实际携带的考点」核算覆盖率，未覆盖考点必须先补齐才能开始作答（`compose.canStart`）。
3. **沉浸练习与作答草稿**：`questions/index` 的「开始作答」经 `practiceStore.initPractice(undefined, params)` → `POST /practices` 后跳 `subpackages/practice/pages/session/index?practice_id=<id>`。作答写入走 `practiceStore.recordAnswer`：先写内存 + `uni.setStorageSync('practice_draft_<userId>_<practiceId>')`，再入 `src/utils/draftQueue.ts` 的串行队列异步写后台。队列语义为**同题串行、快速输入只保留最后值、失败进入 `draftFailures` 且页面顶部给出可见重试入口、交卷前必须 `flush()` 成功**。
4. **交卷 → 判题中 → 正式诊断**：点击交卷调用 `practiceStore.submit()`（先 flush 全部在途草稿，失败则抛错不提交；成功后复用同一 `Idempotency-Key` 调用 `POST /practices/{id}/submit`），随后 `uni.redirectTo` 到 `subpackages/report/pages/detail/index?practice_id=<id>`。结果页**不直接展示诊断报告**：它先渲染逐题判题进度，仅当 `session.completed_at` 非空且 `status === 'completed'`（`summarizeProgress().fullyGraded`）时才由 `diagnosisStore.loadReport` 调用 `POST /practices/{id}/diagnosis` 触发/取回正式报告。**未判定题目不得显示为零分或答错**：`buildAttemptResults` 把未判项标为 `grading` / `pending_regrade` 且 `score`/`isCorrect` 保持 `null`，`resolveResultBadge` 渲染为「判题中 / 待重判」。`partially_graded` 提供 `POST /practices/{id}/regrade` 主动重试判题；主观题的复查/自评分别走 `POST /grading/regrade` 与 `POST /grading/self-evaluate`；错题知识点可经 `practiceStore.regenerateFromWrongPoints` 一键再生题（范围必须且只能落在单一课程或单一未分类资料）。
5. **AI 助教答疑**：`src/components/AiCoachDrawer.vue` 提供两种调用形态——带 `questionId` 时走 `POST /questions/{id}/ask-coach`（可携带 `user_answer` / `grading_points`），否则需至少提供 `folderId` / `materialId` / `knowledgePointId` 之一并走 `POST /coach/ask`（范围级答疑，返回 `sources` 引用切片，可跳转来源讲义）。挂载点：`pages/index/index`（课程随身助教）、`subpackages/material/pages/course/index`（讲义/考点助教）、`subpackages/report/pages/detail/index`（逐题助教）。

---

## 已知偏离（如实记录）

- 单 `.vue` 文件 **≤ 300 行** 是 `docs/DESIGN.md` 第 6 节的硬性约定，当前有 **5 个 `.vue` 超标**（多数在 `5d7a2f3` 之前就已超标）：`pages/index/index.vue` 865 行、`subpackages/material/pages/course/index.vue` 728 行、`pages/profile/index.vue` 440 行、`components/AiCoachDrawer.vue` 392 行、`subpackages/report/pages/detail/index.vue` 343 行；另有 3 个 `.ts` 文件同属单文件过大问题（`types/index.ts` 441、`api/index.ts` 437、`stores/practice.ts` 302）。详见 `quality-guidelines.md`。
- `docs/DESIGN.md` 第 1 节的**零表情包原则**与现状不符：多个页面/组件内联了 Unicode Emoji（详见 `component-guidelines.md`）。
- `docs/DESIGN.md` 第 2 节「禁止裸 Hex」与现状不符：`src/**` 内联 Hex 字面量约 361 处，而 `var(--color-*)` 仅 5 处（全部在 `App.vue`）。
- `src/subpackages/material/pages/upload/index.vue` 目前是 32 行的占位页（无脚本逻辑），`pages.json` 已注册但工作台的上传入口直接走 `pages/index/index.vue`。
