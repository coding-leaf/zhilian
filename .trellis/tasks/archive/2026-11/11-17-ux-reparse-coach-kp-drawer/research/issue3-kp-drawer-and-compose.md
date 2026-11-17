# Research: Issue 3 — 知识点抽屉收纳与出题/组卷方案优化

- **Query**: Investigate Issue 3: "请以抽屉方式,把过多知识点收起来,或者优化生题方案?" (Collapse excessive knowledge points using a drawer/collapsible UI, or optimize the question generation / composition scheme).
- **Scope**: `miniprogram/src/` (question compose page, composables, components, entry points, styles, tests) and `backend/app/` (`POST /questions/generate`, `POST /questions/jobs`, schemas, generation planning & practice creation limits).
- **Date**: 2026-11-17

---

## Findings

### 1. 现状 UI 与交互痛点（为什么出现「40 已选」铺满屏幕）

1. **进入页面默认全选全部考点**：
   - 在 `miniprogram/src/subpackages/material/composables/useComposeConfig.ts:42-60` 中，`setKnowledgePoints(list, preselectedKpId)` 在未传 `kp_id` 时执行 `selectedKpIds.value = deduped.map((point) => point.id)`（第 59 行）。
   - 经首页「课程全景刷题」（`miniprogram/src/pages/index/index.vue:257-263`）或讲义页「按知识点组卷出题」（`miniprogram/src/subpackages/material/pages/course/index.vue:167-173`）进入时都不带 `kp_id`，因此一进页即默认勾选全部资料/章节的所有知识点（如 40+ 个）。
2. **全部考点胶囊内联铺开，无折叠、无抽屉、无搜索**：
   - `miniprogram/src/subpackages/material/components/QuestionConfigPanel.vue:11-31` 直接对 `kpGroups` 和 `group.points` 双层 `v-for` 渲染全部 `.kp-chip`，没有抽屉弹窗、没有手风琴折叠、没有最大高度滚动限制、也没有已选摘要胶囊条。
   - 在课程维度（`folder_id`）下，每份 PDF 讲义是一个组（如 `第二章 - 广义线性回归.pdf`、`第二章 - 线性回归.pdf`），40+ 个考点胶囊占据多屏高度，将「2. 测验题型多选」「3. 题量与难度设置」及底部的「一键智能出题」按钮挤到首屏之外。
3. **单讲义场景会把 L1 章节头节点也当成可选考点**：
   - `miniprogram/src/subpackages/material/pages/questions/index.vue:157-175` 调用 `flattenTreeWithParents(tree?.nodes)` 扁平化知识树，并在 `miniprogram/src/subpackages/material/utils/composeHelpers.ts:133-137` 中把 `[root, ...descendants]` 全部放入 `points` 数组；而课程学习卡片组件 `KnowledgePointList.vue`（依赖 `courseStudy.ts:194-222`）仅把含子节点的 `level === 1` 节点当作 `chapterNode` 章节容器展示。这进一步膨胀了单讲义下的考点芯片数量，也会让粗粒度章节头参与出题。
   - `folder` 范围的 `GET /folders/{folder_id}/knowledge-points`（`backend/app/repositories/question.py:462-499`）同样返回表内全部层级的 `KnowledgePoint`。

### 2. 生题与组卷方案的深层契约冲突与 Bug

当用户面对 40 个（或更多）知识点时，当前出题流水线存在**前后端契约错配与多重阻塞缺陷**：

1. **「题目数量」滑块（1~15）在多考点下完全失效，`plannedCount` 强制拉高到 `selectedKpIds.length`**：
   - `QuestionConfigPanel.vue:60-68` 的滑块范围是 `min="1"`、`max="15"`（默认 `5`）。
   - 但 `useComposeConfig.ts:28-30` 计算 `plannedCount = Math.max(selectedKpIds.value.length, questionCount.value)`。当默认选中 40 个考点时，`plannedCount` 自动变为 **40**，滑块设置（如 10 题）被忽略，提示条（`QuestionConfigPanel.vue:86-90`）告知「预计题量将调整为 40 题以覆盖全部考点」。
2. **前后端批次上限与 `count` 语义错配（`MAX_QUESTION_BATCH = 20` 已被异步任务绕开）**：
   - 后端 `QuestionGenerateRequest.count`（`backend/app/schemas/question.py:60`）与 `GenerateQuestionsOptions.count`（`backend/app/services/_question_generation.py:42`）均限制 `1 <= count <= 20`。
   - 前端旧的同步方案中有 `planGenerationBatches`（`miniprogram/src/api/adapters/questionPlanning.ts:14-36`，`MAX_QUESTION_BATCH = 20`）拆批，但当前 `useQuestionCompose.ts:222-229` 切换为异步任务 `POST /questions/jobs` 后**不再调用 `planGenerationBatches`**（仅错题再生题 `regenerateWrongPractice` 还在用 `generateQuestionsInBatches`）。
   - 取而代之的是 `useQuestionCompose.ts:227` 直接把所有 `selectedKpIds`（40+ 个）一次性传给 `POST /questions/jobs`，并把 `count` 静默截断为 `Math.min(20, Math.max(1, plannedCount.value))`（即 **20**）。
   - 后端 `QuestionService._resolve_generation_plan`（`backend/app/services/question.py:939-997`）调用 `distribute_count(total, n)`（`backend/app/services/_question_generation.py:109-118`）：当 `total < n`（如 `count=20 < n=40`）时，**强制 `return [1] * n`**，即实际忽略 `count=20`、为 40 个考点逐一各生成 1 题（总计 40 题，单次 job 内触发 40 次主 LLM 调用 + 最多 80 次质检重抽）。
3. **超过 50 考点时的硬截断与死锁风险**：
   - `useQuestionCompose.ts:107-110` 的 `fetchBatchQuestions` 硬编码分页参数 `&page=1&page_size=50`。若一个课程包含 >50 个考点（如 55 个），一次 job 虽生成 55 题，前端拉取结果时**静默丢失第 51~55 题**。
   - 核对页门禁 `compose.canStart`（`useQuestionCompose.ts:67-73`）要求 `remainingQuestions.value.length > 0 && coverage.value.missing.length === 0`。一旦超过 50 考点被截断、或任一考点质检未过落入 `pending_review`（`fetchBatchQuestions` 第 113 行过滤掉 `pending_review`）、或用户手动剔除任意一题，**「开始作答」按钮立即禁用**（`QuestionPreviewPanel.vue:40`）。
   - 补齐按钮 `fillCoverageGap`（`useQuestionCompose.ts:340-369`）同样把 `count` clamp 到 `20` 后整批提交。
   - 练习创建上限 `MAX_PRACTICE_QUESTIONS = 50`（`miniprogram/src/types/practice.ts:6` 与 `backend/app/schemas/practice.py:73` `le=50`），`handleStartPractice`（`questions/index.vue:258`）会在进入练习前 `.slice(0, 50)`。超过 50 题既放不进单次练习，也会在移动端核对/作答体验上过重。
4. **未区分「目标覆盖模式」与「指定题量抽考模式」**：
   - 当前架构把「选中考点范围」与「每个选中考点必出 >=1 题」强绑定。如果用户勾选一门课（或全章 40 个考点）只是想做一套 10~15 题的综合小测，当前系统**不支持**「在所选 40 个考点范围内按权重/抽样出 10 题」，而是强迫出 40 题并按 40/40 覆盖率门禁卡死「开始作答」。

### 3. 现有可复用抽屉 / 折叠组件与工程约束

1. **底部抽屉（Bottom Sheet）现有模式**：
   - `miniprogram/src/styles/modal.scss:17-63` 已沉淀通用 `.sheet-overlay`、`.modal-backdrop`（独立关闭热区，规避小程序端 `@tap.self` 失效）、`.sheet-panel`。
   - `miniprogram/src/subpackages/material/components/KnowledgeSnippetModal.vue:1-134`（205 行）与 `miniprogram/src/components/AiCoachDrawer.vue:1-63`（179 行）提供完整可滚动底部抽屉参考：`.sheet-grabber` + 固定头部 + `.sheet-scroll-wrap`（`flex: 1; height: 0; min-height: 0` + `<scroll-view scroll-y class="sheet-body">`）+ 固定 `.sheet-footer`。
2. **分组手风琴折叠现有模式**：
   - `miniprogram/src/subpackages/material/components/KnowledgePointList.vue:18-63,91-131`（180 行）已实现按组（章节）展开/收起（`expandedIds`、`toggleChapter`、`toggleAllChapters`、「全部展开/全部收起」）。
3. **SFC 规范与行数门禁**：
   - `.trellis/spec/frontend/index.md:13,55` 要求 `.vue` 单文件控制在 `<= 270` 行（`docs/DESIGN.md` 硬上限 `<= 300` 行）。
   - 当前 `questions/index.vue` 已达 **290 行**，`QuestionConfigPanel.vue` 为 **185 行**；若新增抽屉交互，**必须拆分为独立子组件**（如 `miniprogram/src/subpackages/material/components/KnowledgePointPickerDrawer.vue`），不可继续往 `questions/index.vue` 或 `QuestionConfigPanel.vue` 内联堆砌模板与样式。
   - 组件写法须遵守 `.trellis/spec/frontend/component-guidelines.md`：内联 `defineProps<{...}>()`、调用签名 `defineEmits`、`v-model:visible`、不使用 `withDefaults`/`defineExpose`、不使用递归组件、全部颜色走 `var(--color-*)`、零 Unicode Emoji。

### 4. 可行方案对比与数据流影响（供方案收敛参考）

- **前端 UI 收纳（抽屉 + 摘要卡片）**：
  - 将 `QuestionConfigPanel.vue` 中的「1. 考点范围」收拢为紧凑摘要卡片：显示「已选 N / M 个考点」、按资料/章节统计的简明摘要或前若干个已选标签预览 +「选择/调整考点」按钮（打开 `KnowledgePointPickerDrawer.vue` 底部抽屉）+ 快捷预设（如「仅薄弱/未练」「智能抽样」或「全选/清空」）。
  - 在 `KnowledgePointPickerDrawer.vue` 内按资料/章节手风琴默认收起（或仅首组展开）+ 关键字筛选 + 分组全选/单选 + 底部「确认选择 (N 个考点)」按钮。
- **生题与组卷方案优化（解决 40+ 考点冲突）**：
  - **方向 A（推荐：双模式或按题量抽样 + 调整默认选中策略）**：
    1. 区分两种组卷模式或提供智能策略：
       - **「按题量综合测验（默认/推荐）」**：用户在滑块选定题量 $K$（如 5~15 题，最高可开放到 20 或 50），若选中考点 $N > K$，前端（或后端）从选中考点中优先/均匀抽样 $K$ 个考点（如优先薄弱/未练/均匀跨资料采样）送去出题，或允许按采样出的子集核算覆盖率，不再强迫把 10 题膨胀成 40 题。
       - **「全考点逐一覆盖」**：显式提示「将至少生成 $N$ 题（每考点 1 题）」，且当 $N > 50$ 时给出超出单次练习上限（50 题）的提示/限制，或只覆盖前 50 题；同时修复 `fetchBatchQuestions` 的 `page_size=50` 分页截断（改为按实际 `total` 或较大 `page_size=100` 拉取，并同步优化 `canStart` 在部分待审时的提示/剔除处理）。
    2. **默认选中优化**：进入组卷页（无 `kp_id`）时，避免盲目默认「全选 40+ 考点并锁定覆盖门禁」，可结合抽屉+推荐策略（如默认展示已选范围并支持一键选薄弱/按章选，或保留范围全选但不再把「范围全选」强绑定成「每考点必出 1 题」）。
    3. **单讲义知识树过滤**：在 `loadKpFromMaterial` 或 `groupComposeKps` 中确认是否过滤掉已有子节点的 L1 章节容器节点（与 `KnowledgePointList.vue` 一致），避免章节标题占用出题配额。
  - **方向 B（若仍保留「每选必出 1 题」语义）**：
    - 则必须修复：1) `fetchBatchQuestions` 支持 `page_size=100` 或分页拉完，避免 >50 题截断；2) 若 `selectedKpIds.length > MAX_PRACTICE_QUESTIONS (50)`，前端禁用或警示无法单次进入练习；3) 前端滑块禁用/提示文案与 `plannedCount` 对齐，且不要把 `count` 硬 clamp 成 20 后与后端 `distribute_count` 隐式展开成 40 产生语义割裂。

---

## Files Found

| Path | Role |
| --- | --- |
| `miniprogram/src/subpackages/material/pages/questions/index.vue` | 出题配置与核对主页面（290 行，已接近 300 行上限）；负责路由参数解析、加载资料/课程考点、发起/监听后台作业与创建练习 |
| `miniprogram/src/subpackages/material/components/QuestionConfigPanel.vue` | 出题配置表单组件（185 行）；当前将全部分组与全部 `.kp-chip` 内联展开，导致长列表挤压题型/题量/提交区 |
| `miniprogram/src/subpackages/material/components/QuestionPreviewPanel.vue` | 核对出题结果组件（75 行）；受 `canStart` 门禁控制，任一选中考点缺题即禁用「开始作答」 |
| `miniprogram/src/subpackages/material/components/QuestionPreviewCard.vue` | 单题预览卡片（122 行）；支持单题剔除（`remove`）与重生成（`regenerate`） |
| `miniprogram/src/subpackages/material/composables/useComposeConfig.ts` | 组卷配置状态（137 行）；定义 `plannedCount = max(selectedKpIds.length, questionCount)`，无 `kp_id` 时默认全选全部考点 |
| `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts` | 出题/核对编排 composable（399 行）；发起 `POST /questions/jobs`（`count` 被 clamp 到 20）、拉取结果（`page_size=50`）、计算 `coverage` 与 `canStart` |
| `miniprogram/src/subpackages/material/utils/composeHelpers.ts` | 考点去重（`dedupeKnowledgePointOptions`）与分组（`groupComposeKps`）；单讲义分组把 L1 章节节点也放入可选 `points` |
| `miniprogram/src/subpackages/material/utils/courseStudy.ts` | 知识树扁平化（`flattenTreeWithParents`）与按章分组（`groupKnowledgePointsByChapter`）；讲义页把 L1 章节节点作为容器而非叶子 |
| `miniprogram/src/subpackages/material/questions.scss` | 出题页与配置/核对组件共享样式表（128 行） |
| `miniprogram/src/subpackages/material/components/KnowledgePointList.vue` | 讲义页按章折叠组件（180 行）；可复用其手风琴展开/收起交互逻辑 |
| `miniprogram/src/subpackages/material/components/KnowledgeSnippetModal.vue` | 考点详情底部抽屉（205 行）；标准 `.sheet-overlay` + `<scroll-view>` + `.sheet-footer` 模板参考 |
| `miniprogram/src/components/AiCoachDrawer.vue` | 全局 AI 助教底部抽屉（179 行）；标准 `v-model:visible` 抽屉交互参考 |
| `miniprogram/src/styles/modal.scss` | 共享弹窗与底部抽屉基础样式（`.sheet-overlay`、`.modal-backdrop`、`.sheet-panel`） |
| `miniprogram/src/api/adapters/questionPlanning.ts` | `MAX_QUESTION_BATCH = 20`、`planGenerationBatches`、`computeKnowledgeCoverage`；目前 `useQuestionCompose` 已不再调用 `planGenerationBatches` |
| `miniprogram/src/utils/questionGeneration.ts` | `generateQuestionsInBatches`（同步 `/questions/generate` 批处理循环，当前仅错题再生题消费） |
| `miniprogram/src/pages/index/index.vue` | 入口页（275 行）：`goToQuestions`（单资料）与 `goToCourseGenerate`（课程全景 `folder_id`） |
| `miniprogram/src/subpackages/material/pages/course/index.vue` | 讲义详情页（187 行）：`goToQuestionConfig`、`goToPracticePoint`、`goToGeneratedQuestions`、`handleOpenTask` |
| `miniprogram/src/pages/review/composables/useReviewCenter.ts` | 学情页薄弱点突破入口 `handleBreakthroughPoint`（携带 `kp_id`） |
| `miniprogram/src/types/practice.ts` | 定义 `MAX_PRACTICE_QUESTIONS = 50` |
| `backend/app/schemas/question.py` | `QuestionGenerateRequest`（`count: ge=1, le=20`）与 `QuestionGenerationJobResponse` |
| `backend/app/api/v1/questions.py` | `POST /questions/generate` 与 `POST /questions/jobs` 路由入口 |
| `backend/app/services/_question_generation.py` | `GenerateQuestionsOptions`（`count` 1~20）与 `distribute_count`（`total < n` 时强制返回 `[1] * n`） |
| `backend/app/services/question.py` | `QuestionService`（`generate_questions_for_knowledge_points`、`generate_questions_for_folder`、`_resolve_generation_plan`、`run_generation_job`） |
| `backend/app/repositories/question.py` | `list_knowledge_points_for_folder` 与 `list_folder_knowledge_points_with_material` |
| `backend/app/schemas/practice.py` | `PracticeCreateRequest`（`question_count: ge=1, le=50`） |
| `miniprogram/tests/diagnosisAndCompose.spec.ts` | 覆盖 `plannedCount`、`canStart`、异步任务流与覆盖率门禁的单测 |
| `miniprogram/tests/studyAndComposeFlow.spec.ts` | 覆盖 `QuestionsPage` 挂载、去重、预选 `kp_id` 与结果核对视图的组件测试 |

---

## Relevant `.trellis/spec/` Files

- `.trellis/spec/frontend/index.md` — 前端架构索引、270/300 行单文件限制、零第三方 UI 库及出题/作答流转契约
- `.trellis/spec/frontend/component-guidelines.md` — Vue 3 SFC props/emits/`v-model:visible`/样式/无 Emoji/防递归规范
- `.trellis/spec/frontend/hook-guidelines.md` — `useQuestionCompose` 既有契约与方法命名规范
- `.trellis/spec/frontend/api-payload-contracts.md` — `POST /practices` 的 `question_ids` + `question_count` 静默截断契约及 `POST /questions/jobs` 异步作业契约
- `.trellis/spec/frontend/network-contract.md` — 请求超时与 `RequestError` 处理规范
- `.trellis/spec/backend/quality-guidelines.md` — 后端 schema/service 分层与校验规范（若方案涉及调整后端 `QuestionGenerateRequest` 或 `distribute_count`）

---

## Caveats / Open Questions

1. **产品语义决策点（关键）**：当用户在课程下选中 40 个知识点、且「题目数量」滑块为 10 题时，期望行为是：
   - **A（推荐）**：允许「按题量抽考」（从已选 40 个考点范围中智能/均匀抽取 10 个考点出 10 题，覆盖率按本次目标抽样考点核算），并提供「全考点逐一覆盖」可选开关（当 `<= 50` 考点时可用）；
   - **B**：坚持「每选考点必出 1 题」，但通过抽屉+不默认全选（如默认不选/仅选薄弱点/按讲义折叠勾选）来控制用户勾选数？
   - 注意：`miniprogram/tests/diagnosisAndCompose.spec.ts:100-115` 当前明确断言了 `plannedCount` 会自动拉高到 `selectedKpIds.length`（7 个考点 + `questionCount=1` -> `plannedCount=7`），若改为方案 A（默认按题量抽样或双模式），需同步更新该单测与 `hook-guidelines.md` / `frontend/index.md` 中的组卷契约描述。
2. **异步 Job 大批量耗时与进度粒度**：`QuestionService.run_generation_job`（`backend/app/services/question.py:1150-1157`）内部使用 `max_workers=3` 并发执行各 KP 的 LLM+Embedding+QC 循环，40 个 KP 仍需约 14 轮串行等待时间，且一旦任一 KP 抛出 `MissingSourceSnippetError`（`backend/app/services/question.py:300-308`）会触发整个 `run_generation_job` 异常回滚整批任务。控制单次出题题量（抽样/上限提示）能显著降低超时与连带失败率。
3. **文件行数预算**：`miniprogram/src/subpackages/material/pages/questions/index.vue` 当前已 **290 行**（超过 `.trellis/spec/frontend/index.md` 提到的 `270` 行现状，逼近 `300` 行红线）；新增知识点选择抽屉必须作为独立组件放在 `miniprogram/src/subpackages/material/components/` 下。
4. **`fetchBatchQuestions` 分页截断**：`useQuestionCompose.ts:108` 的 `page_size=50` 在单批超过 50 题（51+ 考点全选）时会静默丢题并锁死 `canStart`，若允许生成 >50 题或为了健壮性，应检查并放宽/翻页拉取（后端 `GET /questions` 允许 `page_size <= 100`，见 `backend/app/api/v1/questions.py` / `QuestionListQuery`）。
