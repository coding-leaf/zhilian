# Research 02: 初次生题后显示「题库」且界面杂乱的 UX 与状态流转排查

> **调查对象**：Issue #2 —「为什么初次生题后，会显示一次题库，挺杂乱的」
> **调查范围**：`miniprogram/src/`（工作台、讲义详情、出题配置与核对、后台任务条、练习会话、学情/题库 Tab）及 `.trellis/tasks/09-29-*` 历史演进记录、`backend/app/api/v1/questions.py`
> **状态**：只读调研完成

---

## 1. 核心结论（TL;DR）

用户感受到的「初次生题后会显示一次题库，挺杂乱的」，由**架构定位重叠 + 缺少直跳闭环 + 视觉元素堆叠**三重原因共同导致：

1. **缺少「生题完成 → 直接进练习」的闭环跳转**：
   在 `subpackages/material/pages/questions/index.vue` 中，无论同步完成（`handleGenerate`）还是后台任务完成（`watch(() => compose.activeJob.value?.status)`），都不会自动创建 `PracticeSession` 并跳转到 `subpackages/practice/pages/session/index`，而是统一把 `isConfigMode` 设为 `false`，停留在同一页面的 **`QuestionPreviewPanel`（「核对生成题目」视图）**（`questions/index.vue:120-125, 233-239`）。
2. **历史角色重叠，导致「核对视图」长成了一个「前置题库」**：
   - `09-29-fix-qgen-feedback` 当时在「我的题库」Tab 尚未存在时，将 `QuestionPreviewPanel` 作为题目落点页（展示题干、选项、答案、解析、切片、剔除/重生成）；
   - 随后 `09-29-question-bank-tab` 在 `pages/review/index.vue` 落地了真正的「我的题库」（`QuestionBankSection.vue`），并在 `QuestionPreviewPanel` 顶部新增了 `generatedBatchNotice`：**「本次生成批次：… 已归入『学情 - 我的题库』，可在那里按批次再练。」**（`useQuestionCompose.ts:201`）；
   - 结果导致用户点完「一键智能出题」后，先看到一个**明确提到「我的题库」、列出全部试题、带答案与切片查看/删改功能的审查列表**，心理预期（「立刻开始做题」）与页面形态（「题库管理/逐题审核」）严重冲突。
3. **同屏信息过载（生题中与生题后都很杂乱）**：
   - **生题进行中**：顶部 `<BackgroundTaskBar />` 与下方 `.job-progress-banner` **双进度条重复渲染**，底下还继续铺着完整的 `<QuestionConfigPanel />`（`questions/index.vue:3-56`）。
   - **生题完成后**：顶部最多同时堆叠 **3 条提示框**（黄色批次入库提示 + 黄色抽样/待审/缺口汇总提示 + 红色「补齐缺失考点」警告框），下方逐题卡片默认暴露「查看参考答案与解析」（作答前即可看答案）、完整「讲义依据切片」原文、「剔除本题」「重新生成」按钮（`QuestionPreviewPanel.vue:3-45`、`QuestionPreviewCard.vue:31-74`）。
4. **回访与闪屏缺陷放大了杂乱感**：
   - 从 `BackgroundTaskBar` 或讲义页通过 `?view=generated` 进入时，`isConfigMode` 初始为 `true`，`onLoad` 需先 `await` 拉完知识点列表后才拉取批次并把 `isConfigMode` 置为 `false`，导致页面**先渲染配置表单、再闪切到题目列表**（`questions/index.vue:111, 133-152`）；
   - 从讲义页点「继续核对已生成题目」进入时未传 `batch_id`，触发 `loadExistingQuestions` 拉取整份讲义的**全部历史题目**且未过滤 `status`，直接把整份资料的旧题库全部摊出来（`course/index.vue:182-188`、`useQuestionCompose.ts:413-429`）。

---

## 2. 完整用户旅程与状态流转（含精确 `file:line` 锚点）

### 2.1 所有「初次生题」入口路由

| 入口页面 | 触发元素 | 跳转/调用目标 | 代码锚点 |
|---|---|---|---|
| 工作台 (`pages/index/index.vue`) | 讲义卡片「智能出题 ->」 | `navigateTo(/subpackages/material/pages/questions/index?material_id=...)` | `MaterialItemCard.vue:33`, `pages/index/index.vue:250-255` |
| 工作台 (`pages/index/index.vue`) | 课程卡片「课程全景刷题」 | `navigateTo(/subpackages/material/pages/questions/index?folder_id=...)` | `pages/index/index.vue:47-57, 257-263` |
| 讲义详情 (`course/index.vue`) | 底栏「按知识点组卷出题」 | `navigateTo(/subpackages/material/pages/questions/index?material_id=...)` | `course/index.vue:32-34, 174-180` |
| 讲义详情 (`course/index.vue`) | 考点卡 / 溯源弹窗「练此考点」 | `navigateTo(/subpackages/material/pages/questions/index?material_id=...&kp_id=...)` | `KnowledgePointList.vue:58`, `course/index.vue:47, 160-172` |
| 讲义详情 (`course/index.vue`) | 头部「继续核对已生成题目（N 道）」 | `navigateTo(/subpackages/material/pages/questions/index?material_id=...&view=generated)` | `MaterialCourseHeader.vue:65-71`, `course/index.vue:182-188` |
| 学情页 (`pages/review/index.vue`) | 考点列表「去突破」 | `navigateTo(/subpackages/material/pages/questions/index?material_id/folder_id=...&kp_id=...)` | `MasteryPointList.vue:54`, `useReviewCenter.ts:232-247` |
| 学情页 (`pages/review/index.vue`) | 总览卡「针对薄弱考点强化练习」（题库不足兜底） | 直接调 `backgroundTaskStore.startQuestionJob(...)`，完成后靠顶部 `BackgroundTaskBar` 跳转 | `MasteryOverviewCard.vue:55-61`, `useReviewCenter.ts:283-299` |

> 对比参考：**「错题巩固 / 错题靶向强化」**（`useReviewCenter.ts:304-319`、`useReportDetail.ts:157`）走的是同步 `regenerateFromWrongPoints` + **直接 `navigateTo(/subpackages/practice/pages/session/index?practice_id=...)`**，完全不经过「核对/题库」中间页。

---

### 2.2 状态机全景图（当前实现）

```
[工作台 / 讲义详情 / 学情页]
          │
          ▼  navigateTo questions/index?material_id=... (或 folder_id=...)
┌──────────────────────────────────────────────────────────┐
│ questions/index.vue  (初始 isConfigMode = true)           │
│ 渲染: BackgroundTaskBar + QuestionConfigPanel            │
└──────────────────────────────────────────────────────────┘
          │
          │ 用户点击「一键智能出题」 -> handleGenerate()
          │ POST /questions/jobs -> 返回 HTTP 202 (status='queued')
          ▼
┌──────────────────────────────────────────────────────────┐
│ 出题进行中 (isConfigMode === true && isJobInFlight === true)│
│ 同屏同时渲染 3 个区块:                                     │
│  1. <BackgroundTaskBar /> ("正在后台出题 X/Y 考点...")     │
│  2. .job-progress-banner ("正在后台生成题目... + 双导航按钮")│
│  3. <QuestionConfigPanel /> (完整表单 + 禁用按钮)          │
└──────────────────────────────────────────────────────────┘
     │                                    │
     │ 用户留在当前页等待                    │ 用户点「先去浏览讲义 / 返回工作台」
     │ poller 轮询至 status='completed'    │ 后台轮询完成 -> BackgroundTaskBar 显示「去查看」
     ▼                                    ▼
watch(activeJob.status)             navigateTo(questions/index?...&view=generated&batch_id=...)
 -> applyCompletedJob(job)           -> onLoad 先 await loadKp再 await loadBatchQuestions
 -> isConfigMode.value = false       -> isConfigMode.value = false (发生配置页->预览页闪切)
     │                                    │
     └──────────────┬─────────────────────┘
                    ▼
┌──────────────────────────────────────────────────────────┐
│ 中间滞留态: QuestionPreviewPanel (isConfigMode === false) │
│ 标题: 「核对生成题目」                                     │
│  - Notice 1: "本次生成批次：... 已归入「学情 - 我的题库」"  │
│  - Notice 2: generationNotice (抽样/待审/缺口)            │
│  - GapBox (红): "仍有 X 个考点未覆盖... [补齐缺失考点]"    │
│  - QuestionPreviewCard 列表 (每题含答案切换、切片、剔除、重生成)│
│  - 底栏: [重新调整]  [开始作答 (N 题)] (缺口>0时禁用!)      │
└──────────────────────────────────────────────────────────┘
                    │
                    │ 用户必须再次点击「开始作答」-> handleStartPractice()
                    │ POST /practices -> navigateTo session/index?practice_id=...
                    ▼
┌──────────────────────────────────────────────────────────┐
│ 真正练习页: subpackages/practice/pages/session/index.vue   │
└──────────────────────────────────────────────────────────┘
```

---

### 2.3 分步代码链路追踪

#### Step 1：进入组卷页与默认初始化
- `miniprogram/src/subpackages/material/pages/questions/index.vue:111`：`const isConfigMode = ref(true)`。
- `questions/index.vue:133-152`（`onLoad`）：根据 `folder_id` 或 `material_id` 调用 `loadKpFromFolder`（`:158-172`）或 `loadKpFromMaterial`（`:174-183`），再调用 `compose.setKnowledgePoints(list, preselectedKpId)`（`useComposeConfig.ts:82-109`）。
- 若入口未带 `kp_id`（工作台「智能出题」、讲义底栏「按知识点组卷出题」均不带 `kp_id`），`useComposeConfig.ts:108` 默认全选全部去重叶子考点：`selectedKpIds.value = deduped.map((point) => point.id)`。
- 默认 `composeMode = 'smart_sample'`、`questionCount = 5`（`useComposeConfig.ts:30-32`）。

#### Step 2：触发出题与「进行中」双进度条态
- 用户点击 `QuestionConfigPanel.vue:132-139` 的「一键智能出题」→ 触发 `questions/index.vue:233-239` `handleGenerate()` → `compose.generate()`（`useQuestionCompose.ts:330-375`）。
- `compose.generate()` 调用 `startBatchJob(batches[0])` → `taskStore.startQuestionJob(...)`（`stores/backgroundTask.ts:179-185`）→ `POST /questions/jobs`。
- 后端 `backend/app/api/v1/questions.py:206-218` 与 `backend/app/services/question.py:1015-1073` 始终返回 `202 Accepted` 且 `status = 'queued'`（同时在后台线程执行 `run_generation_job` 并生成 `batch_id = f"batch_{uuid.uuid4().hex[:12]}"`，见 `backend/app/services/question.py:1139`）。
- 因此前端 `compose.generate()` 在 `useQuestionCompose.ts:364-365` 命中非终态分支：设置 `activeJobId.value = job.id`，返回 `0`；`handleGenerate()`（`questions/index.vue:235`）不切换 `isConfigMode`。
- **此时页面同时渲染 3 块**：
  1. `questions/index.vue:3`：`<BackgroundTaskBar disable-auto-navigate @open-task="handleOpenBackgroundTask" />`，从 `taskStore.visibleTasks`（`stores/backgroundTask.ts:422-448`）渲染一条蓝色进度条 `"正在后台出题 X/Y 考点..."`。
  2. `questions/index.vue:14-31`：`<view v-if="compose.isJobInFlight.value" class="paper-card job-progress-banner">` 渲染**第二条**蓝色进度卡片（`"正在后台生成题目 (X / Y 考点)... 您可以留在当前页等待，或随时返回浏览讲义"` + 进度条 + `先去浏览讲义` / `返回工作台` 两个按钮）。
  3. `questions/index.vue:33-56`：`<QuestionConfigPanel v-if="isConfigMode" ... />` 仍在下方完整展示，底部按钮仅变成禁用文案 `"后台正在出题中..."`（`QuestionConfigPanel.vue:207`）。

#### Step 3：出题完成后的状态切换（不进练习，反而切进「核对/题库」视图）
- `stores/backgroundTask.ts:210-217` 的 `pollOnce()` 轮询 `GET /questions/jobs/{jobId}`，拿到 `status === 'completed'` 后更新 `questionJobs` Map。
- `questions/index.vue:115-131` 的 `watch(() => compose.activeJob.value?.status, ...)` 捕获 `'completed'`：
  1. 调用 `await compose.applyCompletedJob(job)`（`useQuestionCompose.ts:247-327`）：
     - 通过 `fetchBatchQuestions(job.batch_id)` 请求 `GET /questions?batch_id=...&page=1&page_size=100`（`useQuestionCompose.ts:151-171`），统计 `pending_review` 数量，过滤出 `available` 题目；
     - 调用 `taskStore.dismissTask('job:' + job.id)` 消掉任务条（`:254`）；
     - 若 `pendingBatches` 为空（单批完成），赋值 `questions.value = mergedAvailable`、`hasGenerated.value = true`（`:310-312`）；
     - 调用 `await loadGeneratedBatches(allBatchIds)`（`:315`），再发一次 `GET /questions/batches?page=1&page_size=50`（`:173-193`）组装批次描述文案。
  2. 返回 `questions/index.vue:122-125`：**把 `isConfigMode.value = false` 并弹出 `'已生成 N 道题目'`，停留在当前页，不创建练习也不跳转 `session/index`！**

#### Step 4：为何 `QuestionPreviewPanel` 看起来像「显示了一次杂乱的题库」
当 `isConfigMode` 变为 `false` 后，`questions/index.vue:5-12, 58-73` 渲染以下全部内容：
1. **顶部标题变更为审查态**（`questions/index.vue:6-10`）：`核对生成题目` / `已生成 N 道题目，核对答案与解析后开始作答`。
2. **提示框 #1（直接点名「我的题库」）**（`QuestionPreviewPanel.vue:3-5`、`useQuestionCompose.ts:199-204`）：
   黄色 `.notice-box` 展示：`本次生成批次：<日期 · 来源 · N 题>。已归入「学情 - 我的题库」，可在那里按批次再练。`
3. **提示框 #2（规则拼接长文案）**（`QuestionPreviewPanel.vue:7-9`、`useQuestionCompose.ts:113-135`）：
   第二块黄色 `.notice-box` 展示 `generationNotice`，当抽样/待审/缺口并存时拼成一长段分号文本（如 `已从所选 40 个考点中均匀抽取 5 个考点出题；另有 1 道题待审核，本次展示全部可作答题目；合格题未覆盖 1 个考点，需补齐后才能开始作答`）。
4. **提示框 #3（红色覆盖缺口阻塞框）**（`QuestionPreviewPanel.vue:11-18`）：
   只要 `coverage.missing.length > 0`（例如某考点质检未过落入 `pending_review` 或用户剔除了 1 题），就渲染红色 `.gap-box` + 「补齐缺失考点」按钮，并**锁死**底栏「开始作答」按钮（`useQuestionCompose.ts:109-111` `canStart`）。
5. **逐题卡片重度暴露答案与题库管理控件**（`QuestionPreviewCard.vue:2-75`）：
   每道题卡片同时包含：题号、考点绿标、题型+难度徽章、富文本题干、全部选项、`查看参考答案与解析` 折叠条（点开即在**作答前**查看参考答案/解析/采分点）、`讲义依据切片`（蓝边框引用块展示教材原文）、底部双按钮 `剔除本题` + `重新生成`。
6. **固定底栏**（`QuestionPreviewPanel.vue:35-45`）：`重新调整` + `开始作答 (N 题)`。

#### Step 5：如果用户先离开页面，之后从 `BackgroundTaskBar` / 讲义页 / 学情页跳转
1. **从 `BackgroundTaskBar` 点击「去查看」**：
   - `BackgroundTaskBar.vue:48-72` 与 `course/index.vue:111-139` 拼接 `view=generated`：
     - 有 `materialId` 或 `folderId` 时，跳 `/subpackages/material/pages/questions/index?...&view=generated&batch_id=...`，最终依然停在上面 Step 4 的 `QuestionPreviewPanel`。
     - 若任务既无 `materialId` 也无 `folderId`（兜底分支：`BackgroundTaskBar.vue:60-66`、`course/index.vue:127-133`），直接 `uni.switchTab({ url: '/pages/review/index' })`，跳转到「学情」Tab。
2. **「学情 / 我的题库」Tab 本身的复杂度**（`pages/review/index.vue:1-145`）：
   - `pages.json:42-43` 中该 Tab 仍叫 `学情`，页面顶部先放了课程筛选 pills + 巨大的 `MasteryOverviewCard`（`学情总览` 4 个指标 + 进度条 + 4 色档位 pill + 「针对薄弱考点强化练习」按钮），中间再放 4 个 segment Tab（`考点掌握` / `错题本` / `练习记录` / `我的题库`），默认落在 `mastery`（`useReviewCenter.ts:44`）。
   - 该部分的历史遗留已记录在 `.trellis/tasks/09-29-question-bank-tab/prd.md:266-285`（R1–R6 暂缓未做）。

#### Step 6：真正进入答题页的路径
- 只有当用户在 `QuestionPreviewPanel` 再点一次「开始作答」→ `handleStartPractice()`（`questions/index.vue:251-287`）：
  1. 校验 `compose.canStart.value`；
  2. 切片前 50 题 `questionIds`；
  3. 调 `practiceStore.initPractice(undefined, { ..., question_ids: questionIds, question_count: questionIds.length })` → `POST /practices`（`stores/practice.ts:89-105`）；
  4. `uni.navigateTo('/subpackages/practice/pages/session/index?practice_id=...')`，由 `session/index.vue:136-152` 加载试卷开始作答。

---

## 3. 竞态、生命周期 Hook 与额外 UX 缺陷清单

除核心流程「缺少直跳练习、停留在前置题库」外，代码级排查还发现以下具体缺陷：

| # | 现象 / 缺陷 | 根因与精确代码位置 |
|---|---|---|
| D1 | **进入 `view=generated` 时先闪现完整出题配置页，再突变到题目列表** | `questions/index.vue:111` 将 `isConfigMode` 硬初始化为 `true`。`onLoad`（`:133-152`）先串行 `await loadKpFromFolder/Material`（`:135-141`），再 `await loadGeneratedBatch/Questions`（`:142-147`），最后才在 `:191` 或 `:209` 把 `isConfigMode.value = false`。在两段串行网络请求返回前，用户会明显看到一次配置表单闪现。 |
| D2 | **出题中双进度条 + 完整配置表单同屏叠放** | `questions/index.vue:3` 的 `<BackgroundTaskBar />` 与 `:14-31` 的 `.job-progress-banner` 消费同一个 `taskStore.questionJobs` 状态，造成出题中页面顶部连续两条进度条；且 `:33` 的 `v-if="isConfigMode"` 未排除 `isJobInFlight`，导致表单仍在下方占屏。 |
| D3 | **离开页面期间任务已完成，再返回 `questions/index` 无法自动衔接** | `questions/index.vue:154-156` 的 `onShow` 调用 `compose.attachActiveJobForScope()`，但 `useQuestionCompose.ts:380` 过滤 `if (!isQuestionJobActive(job)) continue`，只认 `queued/running` 任务。若任务在用户切走期间已完成，返回 `questions/index` 时页内 `watch` 不触发，只能靠顶部 `BackgroundTaskBar` 手动点「去查看」。 |
| D4 | **从讲义页「继续核对已生成题目」进入时无 `batch_id`，混入全量历史题且不过滤状态** | `course/index.vue:182-188` 跳 `questions/index?material_id=...&view=generated`（无 `batch_id`），触发 `loadExistingQuestions(materialId)`（`useQuestionCompose.ts:413-429`）。它调用 `apiGetQuestionsByMaterial`（`api/modules/questions.ts:61-69`）：无分页参数（受限于后端默认 `page_size`）、**不过滤 `pending_review`**、把多次生成的历史题目混在一起，且未设置 `generatedBatches`（提示条逻辑与批次视图割裂）。 |
| D5 | **单批质检不通过 / 剔除任意 1 题即锁死「开始作答」** | `useQuestionCompose.ts:109-111` 要求 `coverage.missing.length === 0` 才允许点「开始作答」。哪怕系统已成功生成 4 道合格题，只要有 1 个考点落入 `pending_review` 或用户剔除 1 题，用户就被卡在杂乱的预览页无法开练，必须先点「补齐缺失考点」再等一轮 LLM 生题。 |
| D6 | **在生题后页做「试卷预览」却先给参考答案与解析** | `QuestionPreviewCard.vue:31-59` 为每道待练题目提供「查看参考答案与解析」和「采分点」，以及「讲义依据切片」（`:61-67`）。对「初次生题准备测验」的用户来说，这既视觉冗余又破坏测验独立思考体验。 |

---

## 4. UX 与状态流转收敛方案对比

### 方案 A（推荐）：「极简组卷 → 专注等待态 → 直接进入作答」，题库职责彻底收归「学情 - 我的题库」

**核心思路**：将「初次生题并立即刷题」与「题库管理/逐题审查」彻底解耦。`questions/index.vue` 回归为**组卷与进度页**，出题完成默认**自动创建练习并 `redirectTo` 进入 `session/index`**；事后复盘或挑题再练统一走「学情 - 我的题库」。

- **关键改动点**：
  1. **生题进行中去重瘦身**：在 `questions/index.vue` 当 `compose.isJobInFlight` 为真时，隐藏或折叠 `QuestionConfigPanel`（只保留摘要+取消/返回浏览入口），并移除页面顶部的重复 `<BackgroundTaskBar />`（或隐藏当前作用域正在页内展示的任务，避免双进度条）。
  2. **完成即直接开练（Direct Launch）**：在 `questions/index.vue` 的 `watch(activeJob.status === 'completed')` 与 `handleGenerate()` 中，拿到可用 `questionIds` 后直接调用 `practiceStore.initPractice(...)` 并 `uni.redirectTo('/subpackages/practice/pages/session/index?practice_id=...')`（用户按返回直接回到讲义/工作台，不再回退到配置页或中间预览页）。
  3. **缺口处理改为非阻塞**：若部分考点落入 `pending_review` 导致实际生成题数少于目标数，只要 `available.length > 0` 即允许并直接带可用题进入练习（仅用轻 Toast 提示「已生成 X 题，正在进入作答」，不再用红色 `.gap-box` 拦路）。仅当 `available.length === 0` 时留在本页并提示调整配置重试。
  4. **后台任务条「去查看」直达开练或题库**：若用户切走后从 `BackgroundTaskBar` 点击已完成的 `question_job`，可直接拉取该 `batch_id` 的 `available` 题目创建练习进入作答（或弹窗询问「立即作答 / 去题库查看」）。
  5. **退役/简化 `QuestionPreviewPanel`**：讲义详情页的「继续核对已生成题目」按钮改为引导到对应资料/批次的题库入口或直接「再练一次」，不再维护两套外观相似的「题库列表」。
- **优点**：
  - 彻底消除「初次生题后跳出一次杂乱题库」的问题，路径从 `配置 → 出题 → 核对(题库) → 作答` 缩短为 `配置 → 出题 → 作答`（与错题强化路径完全一致）。
  - 消除了作答前剧透答案/解析/切片的体验矛盾，也消除了 `QuestionPreviewPanel` 与 `QuestionBankSection` 的概念重复。
- **缺点 / 风险**：
  - 若用户在生题后确实想先「剔除不满意的题 / 单独重生成某题」再进考场，在方案 A 下需改在「我的题库」或「交卷后的诊断报告」中做筛选；
  - 需同步调整 `miniprogram/tests/studyAndComposeFlow.spec.ts` 中对 `QuestionPreviewPanel` 自动切换的断言。

---

### 方案 B：保留中间确认，但改为「极简试卷就绪卡」（不直接铺题库列表）

**核心思路**：不直接强制跳转 `session/index`（防止用户离开后突然被拉走，或保留开练前确认题量/题型的机会），但把 `QuestionPreviewPanel` 彻底精简为一个**轻量的「试卷已就绪」过渡态**，默认**不展开**题目详情、答案、切片与单题操作。

- **关键改动点**：
  1. 去除顶部多条黄/红 Banner 叠放，合并为一张简洁摘要卡片：`"已为你准备好 5 道测验题（覆盖 5 个考点）"`，如有缺口/待审用一行次要灰色说明替代红框阻塞；
  2. 移除「查看参考答案与解析」与「讲义依据切片」等考前剧透和重度卡片元素；题目清单改为可选折叠抽屉（「预览题目清单」，默认收起），主行动区只有醒目的「立即开始作答（5 题）」和次要「重新配置」。
  3. 同步修复 `view=generated` 闪屏（在 `onLoad` 解析出 `options.view === 'generated'` 时立即置 `isConfigMode = false` 并展示 loading 骨架屏，而不是先渲染配置表单）及去重双进度条。
- **优点**：
  - 保留用户自主点击「开始作答」的掌控感（尤其当用户在其他页面通过 `BackgroundTaskBar` 触发跳转时不会突兀直接进考场）；
  - 视觉复杂度大幅下降，不再像「杂乱题库」，改动风险和现有单测改动量小于方案 A。
- **缺点 / 风险**：
  - 仍然多一次点击（「生成完 → 点开始作答」），相比方案 A 少了一步极致的顺滑感；
  - 「预览题目清单」与「学情 - 我的题库」在功能上仍有轻微重叠。

---

### 方案 C：组卷页显式提供模式分流（「立即开练（默认）」 vs 「先核对题目」）

**核心思路**：在 `QuestionConfigPanel` 底部主按钮旁提供轻量开关或次按钮（例如主按钮为「出题并立即作答」，次要文字链为「仅生成并核对题目」），或者默认走方案 A 直跳 `session/index`，仅在讲义回访/我的题库保留核对能力。

- **优点**：兼顾「想直接刷题的多数场景」和「教师/精细自查需先审题的场景」。
- **缺点 / 风险**：在配置页增加一个决策维度，若文案不够直观反而增加新手理解成本；仍需重构 `QuestionPreviewPanel` 的多 Banner 叠放与双进度条问题。

---

### 推荐建议（供 PRD 收敛拍板）

- **首选推荐方案 A**（或在用户担心后台切回突兀时采用 **A + B 混合策略**：用户在 `questions/index` 原地等完时 **直接创建练习并 `redirectTo` 进 `session/index`**；若用户切走后再点 `BackgroundTaskBar` 通知，则直接用该 `batch_id` 开练或进入极简「试卷就绪卡」一键开练）。
- **必须顺带清理的工程共性项（无论选 A/B/C）**：
  1. 消除 `questions/index.vue` 中 `<BackgroundTaskBar />` 与 `.job-progress-banner` 的**双进度条冲突**，且出题中收起 `QuestionConfigPanel`；
  2. 修复 `view=generated` 时 `onLoad` 先渲染配置页再闪烁切换的时序问题；
  3. 明确「出题页 = 组卷与开练」与「学情 Tab = 我的题库（批次管理/审题/错题标记/跨批再练）」的职责边界，并按 `.trellis/tasks/09-29-question-bank-tab/prd.md` 后续决定是否清理 `pages/review/index.vue` 的 tabBar 文案与信息架构。

---

## 5. 已检索的相关 `.trellis/spec/` 规范清单

供后续 `implement.jsonl` / `check.jsonl` 编排引用：

- `.trellis/spec/frontend/index.md` — 前端目录结构、单文件 `<= 270/300` 行门禁、零第三方 UI 库与学习闭环契约
- `.trellis/spec/frontend/component-guidelines.md` — SFC `defineProps`/`defineEmits`/`v-model:visible`/设计 Token/无 Emoji/防递归规范
- `.trellis/spec/frontend/hook-guidelines.md` — `useQuestionCompose` 既有契约与方法命名规范
- `.trellis/spec/frontend/state-management.md` — Pinia stores (`practice`, `backgroundTask`, `material`) 状态与网络边界
- `.trellis/spec/frontend/api-payload-contracts.md` — `POST /practices` 的 `question_ids` + `question_count` 截断契约及 `POST /questions/jobs` 异步作业契约
- `.trellis/spec/frontend/network-contract.md` — `request.ts` 两档超时、`RequestError` 与 `fail` 回调兜底规范
- `.trellis/spec/guides/cross-layer-thinking-guide.md` — 前后端契约对齐检查清单
