# Technical Design: UX, Reparse Reliability & Question Compose Drawer

## 1. Architecture Overview

本次改造横跨 `miniprogram` 与 `backend` 两端，按三个相互解耦的模块协同推进：
1. **视觉清晰度与 AI 助教对话体验（Frontend + Backend LLM）**
2. **资料解析全链路可观测性与异常恢复（Backend Worker/Pipeline + Frontend Poller/Course Header）**
3. **组卷考点抽屉化与按题量抽考策略（Frontend Compose UI/Composable + Backend/Test Alignment）**

---

## 2. Detailed Design

### 2.1 UI 清晰度与 AI 助教优化

#### Frontend (`miniprogram/src/`)
- **`App.vue`**：
  - 删除 `page { -webkit-font-smoothing: antialiased; }`（行 112），避免 Windows 微信开发者工具及 PC 端禁用 ClearType 导致文字边缘发虚。
- **`utils/richText.ts` & `components/RichContent.vue`**：
  - 保留 `RichContent.vue` 默认（`28rpx / 1.65`）用于大卡片题干/独立阅读，保持 `compact`（`24rpx / 1.55`）用于卡片内嵌与助教气泡。
  - 在 `richText.ts` 中微调 `HEADING_SIZES`（从 `1.18/1.12/1.06/1.02` 收紧为 `1.10/1.06/1.03/1.0`）并适度收紧 `STYLES.headingBase` / `paragraph` / `blockquote` / `codeBlockInner` 间距与字体比例，使 Markdown 在窄气泡内不显臃肿。
  - 检查 `richText.ts` 内联样式：在微信 `<rich-text>` 中保持稳定单位与清晰对比度。
- **`components/CoachMessageList.vue`**：
  - 行 27 改为 `<RichContent v-else :content="msg.content" compact />`。
  - `.msg-text`（用户气泡）从 `28rpx` 调至 `25rpx`，`.msg-bubble` 调整为 `max-width: 86%; padding: 16rpx 20rpx; line-height: 1.5;`。

#### Backend (`backend/app/`)
- **`integrations/llm/coach_graph.py`**：
  - `generate` 节点 Prompt 改造：保留「只根据给定资料回答；不足以回答时坦诚说明；`citation_ids` 只能选给定切片 ID，禁止编造」红线；增加表达规范：
    - 语气：像真人学长/助教一对一点拨，自然亲切，不生硬套用公文模板；
    - 结构：先用 1~2 句话直接给结论，再用 2~3 条简短要点说清条件或例子；
    - 篇幅：总回复控制在 150~260 字，禁止使用「一、二、三、」多级大纲和长篇照搬讲义原文；
    - `suggestions`：给出 2~3 条口语化短追问（每条 <= 15 字）。
  - `LLMOptions(temperature=0.45, max_tokens=900)`（为 `CoachDraft` JSON 留出充足空间防截断）。
- **`services/question.py::ask_coach`** & **`schemas/question.py`**：
  - 同步优化 `ask_coach` System Prompt：自然对话口吻、先给关键结论/错因再简明点拨、控制 150~250 字、禁长篇大纲；`LLMOptions(temperature=0.65, max_tokens=900)`。
  - 更新 `AskCoachResponse.reply` / `CoachDraft.reply` 描述，去掉诱发长文的“深度解析内容”措辞，改为“精炼口语化的助教答疑回复（约150-260字）”。

---

### 2.2 资料重解析 60% 假死修复与可靠性加固

#### Backend (`backend/app/`)
1. **进度推进（消除 60% 长期停滞）**：
   - 检查 `MaterialVersion` / `ParseStatus`（`queued=10`, `parsing_doc=30`, `ocr_processing=45`, `extracting_knowledge=60`, `auditing_knowledge=75`, `embedding_generation=85`, `ready=100`）与 `MaterialService._calculate_progress_percentage`。
   - 调整 `parse_material_pipeline` 阶段映射，或结合轻量进度存储（若支持在 `MaterialVersion` 或 Redis cache key 记录动态进度百分比 `progress_percentage`，优先级：动态进度 > 阶段映射；无迁移即可实现 30% -> 45% -> 60% -> 75% -> 88% -> 100% 平滑步进）：
     - 文件提取完成 -> `parsing_doc` (30%)；
     - 切片向量化 -> `embedding_generation`（若在知识抽取前，或使用独立进度阶段更新，注意 `ParseStatus` 语义）；更优方案：保持阶段枚举含义清晰，在 `parse_material_pipeline` 中让 `embedding` 阶段（`embedding_generation` 或细粒度 progress cache）和 `KnowledgeService._run_extraction_with_retries` 的 `on_progress(completed_batches, total_batches)` 回调把实时进度（如 `50% ~ 85%`）写入 Redis 进度缓存（TTL 1h，失败回退阶段默认映射），质量审核时写入 `auditing_knowledge` (88%)，落库完成置 `ready` (100%)。这样**零数据库迁移**即可让前端进度条平滑走动！
2. **孤儿任务与卡死恢复**：
   - `backend/app/worker.py::handle_job_terminal_failure`：补充 `parse_material_pipeline` 的终态失败兜底——从 `args`/`kwargs` 解析 `material_id`、`version_id`、`user_id`，若当前版本仍处于 active `parse_status`，调用 `mark_pipeline_failed` 置为 `FAILED`（`failed_stage="worker_terminated"`，`error_message` 含安全脱敏后的失败摘要）。
   - `MaterialService.trigger_parse`：当 `force=True` 且 `target_version.parse_status in active_statuses` 时，若该版本已超过卡死阈值（如 `updated_at` 超过 20 分钟无更新）或队列中已无活跃 job（通过队列检查/显式恢复），允许强制重置为 `QUEUED` 并重新入队，防止永久锁死；否则若仍在正常解析中（最近刚更新）继续拒绝重复提交。
   - `backend/app/schemas/material.py` & `api/v1/materials.py`：`MaterialDetailResponse` 和 `MaterialListItem` 增加可选字段 `error_message: str | None = None`、`failed_stage: str | None = None`（由最新 `MaterialVersion` 映射）。
3. **非破坏性重解析（Delay Destructive Replace）**：
   - `MaterialService.parse_material_pipeline` 在 `force=True` 时，**不在函数开头**调用 `delete_snippets_by_version` / `delete_knowledge_points_by_version` + `commit()`。
   - 先完成文件下载、OCR/PDF 文本修复、切分与 embedding 计算（纯内存/外部计算），待生成有效 `snippets` 后才进入替换（或先保留旧 KP，待 `extract_and_build_knowledge_tree` 产出合法候选列表后在同一事务内完成新旧替换——注意 `KnowledgeService.extract_and_build_knowledge_tree` 需支持接收内存切片或先写临时/新版本，需仔细核查 `KnowledgeService` 对 DB `MaterialSnippet` 的检索依赖，必要时用 `version_id` 隔离或事务内回滚！）。
   - 具体事务策略：
     - **方案**：在 `parse_material_pipeline` 中使用**新创建待激活版本**或**延迟到提取前最小窗口**？注意：若 `KnowledgeService` 依赖 `self.repo.list_snippets_by_version(version_id)` 与 `search.index_snippets`，则在单个 `MaterialVersion` 内，如果把 `force=True` 拆成：
       1. 先下载与解析文档文本 + 切分 + 计算 embeddings（最容易因文件/OCR/API 失败的步骤），**此时旧切片与旧 KP 仍完好**；
       2. 在提取知识树之前如果先写新切片，或者用 `new_version`？Wait：查看 `trigger_parse` 是否创建新 version 还是原地重用 `version_id`！若原地重用 `version_id`，把「旧 KP 删除」尽量推迟到 `extract_and_build_knowledge_tree` 成功生成候选节点之后（`extract_and_build_knowledge_tree` 先只读新切片做 LLM 抽取 + 质量门禁，全通过后再 delete 旧 KPs + insert 新 KPs + commit；如果 LLM 抽取抛异常，至少旧 KPs 没被删，或者新建一个 staging version 待 ready 后再切换 `current_version_id`！）。
       - **Staging Version 思路（最干净！）**：当 `force=True` 重解析已有 `ready` 资料时，或者直接检查 `MaterialService.trigger_parse` 现状再决定（`implement.md` 中先读 `material.py:349-530, 1138-1260` 确定最小安全改造：至少确保文件解析/切分/embedding 完成前不删旧数据，且把 KP 删除放到新 KP 校验通过后同一事务提交，保证 LLM 失败时不清空旧知识点和题目！）。

#### Frontend (`miniprogram/src/`)
- **`stores/backgroundTask.ts`**：
  - `ensurePolling` 改为支持长任务退避策略：前 48 次（2 分钟）每 `2500ms`，之后每 `5000ms` 最多再轮询 `156` 次（再覆盖 13 分钟，总计 **15 分钟**）。
  - 定义轮询超时状态（`timedOutTaskIds` / 任务上的 `timedOut?: boolean`），当 `poller.run` 返回 `status === 'timeout'` 时标记该任务为「进度同步已暂停（点击刷新）」而非静默丢弃。
  - 增加手动单次刷新动作 `refreshTask(materialId)`。
- **`subpackages/material/pages/course/index.vue` & `components/MaterialCourseHeader.vue` & `composables/useCourseDetail.ts`**：
  - `onShow` 在 `!isLoading` 且 `material.status !== 'ready'` 时也调用 `loadDetail()` + `backgroundTaskStore.refreshActiveTasks()`。
  - `MaterialCourseHeader.vue` 在 `isParsing` 分支下增加「刷新进度」按钮与慢任务提示文案；若 `timedOut` 为真提示「后台仍在处理中，点击刷新获取最新进度」。
  - 修正 `useCourseDetail.ts::confirmAndReparse` 弹窗提示，如实说明将重新提取切片与知识点并重置关联题库（已有作答历史记录保留）。

---

### 2.3 出题页考点抽屉与生题方案优化

#### Frontend (`miniprogram/src/subpackages/material/`)
1. **新建 `components/KnowledgePointPickerDrawer.vue`（<= 250 行）**：
   - Props：`visible: boolean`、`groups: ComposeKpGroup[]`、`selectedIds: string[]`、`isAllSelected: boolean`。
   - Emits：`update:visible`、`toggle-kp`、`toggle-group`、`toggle-select-all`、`confirm`。
   - 布局复用 `.sheet-overlay` / `.modal-backdrop` / `.sheet-panel`（`styles/modal.scss`）+ `virtualHost: true` + `<scroll-view scroll-y>`（遵循 `quality-guidelines.md` 铁律）：
     - 头部：「选择考察知识点」+ 已选计数 + 关闭按钮；
     - 搜索与工具栏：关键词输入框（实时过滤分组与考点）+ 「全部展开/收起」+ 「全选/清空」；
     - 分组手风琴列表：每组显示标题、`已选 X/Y`、组级「全选/取消」与展开/收起箭头（纯 CSS chevron，无 Emoji）；默认仅展开第 1 组（或当前含搜索命中项的组全展开）；
     - 底部固定 `.sheet-footer`：「已选 N 个考点」+ 「确认选择」主按钮。
2. **改造 `components/QuestionConfigPanel.vue`（保持 <= 200 行）**：
   - 「1. 考点范围」改为紧凑卡片：
     - 标题行：`1. 考点范围` + 右侧 `选择考点` 按钮（触发打开抽屉）。
     - 摘要行：`已选 N / M 个考点（覆盖 G 份讲义）`，下方最多展示前 5 个已选标签胶囊（只读预览，点击区域或 `+K 个，点击调整` 均可打开抽屉）；另提供「全选 / 清空」快捷文本按钮。
   - 「3. 题量与难度设置」优化：
     - 滑块上限从 `15` 扩展到 `20`（`min="1"`, `max="20"`），让用户能自由设置 1~20 题；
     - 增加**组卷策略切换**（两枚紧凑药丸开关）：
       - `smart_sample`（默认）：**按题量智能抽考**（「从已选考点中均匀抽取 K 个出 K 题」）
       - `full_coverage`：**全考点逐一覆盖**（「每个已选考点至少出 1 题」）
     - 当 `composeMode === 'smart_sample'` 且 `selectedKpIds.length > questionCount` 时，提示：「将从已选 {N} 个考点中均匀抽取 {K} 个考点生成 {K} 题」。
     - 当 `composeMode === 'full_coverage'` 且 `selectedKpIds.length > 50` 时，红色/醒目提示并禁用提交：「单次练习最多支持 50 题，当前全覆盖需 {N} 题，请改用按题量抽考或缩减至 50 个考点以内」。
3. **优化 `utils/composeHelpers.ts` & `composables/useComposeConfig.ts` & `composables/useQuestionCompose.ts`**：
   - **`composeHelpers.ts`**：
     - 新增 `selectLeafComposePoints` / 过滤单讲义知识树中的非叶子章节容器节点（`level === 1` 且存在 `parent_id === node.id` 的子节点时剔除该容器节点，与 `KnowledgePointList.vue` 一致）。
     - 新增纯函数 `sampleKnowledgePointIds(groups, selectedIds, targetCount): string[]`：跨分组（轮询/分层均匀）从已选考点中确定性抽取 `targetCount` 个考点，确保每个章节/讲义都有代表性题目。
   - **`useComposeConfig.ts`**：
     - 新增 `composeMode = ref<'smart_sample' | 'full_coverage'>('smart_sample')` 与 `setComposeMode`。
     - `effectiveKpIds` computed：
       - 若 `composeMode === 'smart_sample'` 且 `selectedKpIds.length > questionCount` -> 返回 `sampleKnowledgePointIds(...)`（长度等于 `questionCount`）；
       - 否则返回 `selectedKpIds`。
     - `plannedCount` computed：
       - `smart_sample` 模式下等于 `questionCount`（当 `selectedKpIds.length > 0`）；
       - `full_coverage` 模式下等于 `Math.max(selectedKpIds.length, questionCount)`。
   - **`useQuestionCompose.ts`**：
     - `generate()` 使用 `config.effectiveKpIds.value`（而非全量 `selectedKpIds`）去生成，并在 `activeTargetKpIds`（本次出题目标考点集）上计算 `coverage` 和 `canStart`！
     - 若 `activeTargetKpIds.length > MAX_QUESTION_BATCH (20)`（即 `full_coverage` 选中 21~50 个考点时），使用 `planGenerationBatches` 拆批或在单一作业前合理拆分/提示；同时修复 `fetchBatchQuestions` 的 `page_size=50` 截断为循环分页（`page_size=100` 且当 `total > items.length` 继续拉下一页），彻底消除静默丢题。
     - 将 `useQuestionCompose.ts` 保持精简（提取纯辅助函数进 `composeHelpers.ts`），确保 `questions/index.vue` <= 290 行。

---

## 3. Risks & Mitigations
- **既有单测对齐**：`miniprogram/tests/diagnosisAndCompose.spec.ts` 原先断言默认 `plannedCount` 抬升到 `selectedKpIds.length`，改造后需覆盖 `smart_sample`（默认，保持用户设定题量并均匀抽样）与 `full_coverage`（抬升到已选考点数）两种模式，并同步更新 `.trellis/spec/frontend/hook-guidelines.md` 与 `quality-guidelines.md`。
- **后端 `Question` / `MasteryRecord` 外键级联**：推迟到知识抽取成功后再删除旧数据时，若已有 `Question` 关联到旧 KP，仍应向用户明确告知重解析会重建题库与考点掌握度（保留历史练习答卷快照）。
- **LLM `max_tokens` 截断风险**：`ask_coach` 与 `coach_graph` 设置 `max_tokens=900` 远高于 150~260 字回复 + 3 条短建议 + 最多 8 个 UUID 所需 token（约 350~500 tokens），可避免 JSON 解析失败。
