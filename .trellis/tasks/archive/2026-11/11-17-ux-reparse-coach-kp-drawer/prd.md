# UX & Reparse Fix: AI Coach, Parse Stuck at 60%, Quiz KP Drawer

## Goal

全面解决用户在小程序端反馈的三类核心体验与可靠性问题：
1. **UI 清晰度与 AI 助教排版/表达优化**：消除 Windows/低 DPR 端文字发虚，收敛 AI 助教气泡字号层级，调整后端 Prompt 与参数使助教回复精炼、口语化、有温度。
2. **资料重解析 60% 假死与可靠性加固**：解除前端 5 分钟静默轮询截断、补齐后台进度推进与超时恢复能力、修补 worker 异常/重解析提前删库导致的死锁与数据丢失隐患，确保用户能顺利看到新版结构化知识点简介。
3. **出题页考点抽屉收纳与生题方案优化**：将铺满屏幕的考点标签收拢进可搜索/手风琴分组的底部抽屉，同时引入「按题量智能抽考」默认方案解决「选 40 个考点只想做 10 题」的冲突与 50 题截断死锁。

---

## Requirements

### R1: UI 清晰度与 AI 助教样式/文案优化
- **R1.1 消除发虚渲染**：移除 `miniprogram/src/App.vue` 中会导致 Windows Chromium / 非 Retina 屏 ClearType 失效的 `-webkit-font-smoothing: antialiased`，优化 `richText.ts` 内联样式尺寸与排版，确保重新编译输出最新无 `backdrop-filter` 产物。
- **R1.2 助教气泡字号与紧凑排版**：
  - `CoachMessageList.vue` 助手回复统一启用 `<RichContent compact />`（`24rpx` / `1.55`），用户消息字号收敛至与输入区/快捷提问协调的档位（`25rpx`），调整气泡 `max-width` 与内边距。
  - `richText.ts` 在紧凑档（或默认助教标题）下收敛标题缩放倍率与段落/列表间距，避免过大的 `h1~h4` 占满窄气泡。
- **R1.3 助教 Prompt 与参数去僵化**：
  - 优化 `backend/app/integrations/llm/coach_graph.py`（范围级助教 `POST /coach/ask`）和 `backend/app/services/question.py::ask_coach`（题目级助教 `POST /questions/{id}/ask-coach`）的系统提示词、温度与 `max_tokens`（留足 JSON 结构开销，避免截断）。
  - 保留「严格基于给定资料/题目、不编造 `citation_ids`」的事实约束，要求助教用亲切自然的对话口吻先用 1~2 句给核心结论，再补充 2~3 条简明要点（控制总长约 150~260 字），禁止机械输出「一、二、三、」教科书长篇大纲。

### R2: 重解析 60% 假死修复与解析可靠性加固
- **R2.1 前端长任务轮询与恢复 UX**：
  - `useBackgroundTaskStore.ensurePolling` 延长总轮询时长（支持分阶段退避，覆盖至 >= 15 分钟），且在达到上限后记录明确超时标记，不再静默停止而把界面留在虚假的 `60%`。
  - `MaterialCourseHeader.vue` 在解析中状态提供显式「刷新进度」操作与大讲义耗时提示；`course/index.vue` 的 `onShow` 在 `status !== 'ready'` 时主动同步一次资料详情与后台任务状态。
- **R2.2 后端进度推进与孤儿任务兜底**：
  - `parse_material_pipeline` 消除双写 `EXTRACTING_KNOWLEDGE (60%)` 的平台期，在切分/向量化、知识抽取（含批次回调或阶段推进）、质量审校之间真实推进进度阶段，避免长时间停在单一百分比。
  - `backend/app/worker.py::handle_job_terminal_failure` 不再跳过 `parse_material_pipeline`：worker 异常终止或超时时兜底将仍处于 active 状态的解析版本回写为 `FAILED`（含 `failed_stage` / `error_message`）。
  - `MaterialService.trigger_parse(..., force=True)` 针对长期僵死（或显式强刷恢复）且旧任务已不在活跃队列的卡死版本允许重置并重新入队；`MaterialDetailResponse` / `MaterialListItem` 向后兼容暴露 `error_message` 与 `failed_stage`。
- **R2.3 非破坏性重解析替换**：
  - `parse_material_pipeline` 在 `force=True` 重解析时，**不得**在下载/解析/LLM 知识抽取成功前提前删除并提交旧 `material_snippets` 与 `knowledge_points`；必须待新切片和知识树准备就绪后在同一事务中原子替换（失败则保留旧数据，且修正前端重解析确认提示文案使之准确）。

### R3: 出题页考点抽屉收纳与生题方案优化
- **R3.1 考点抽屉收纳与手风琴分组**：
  - `QuestionConfigPanel.vue` 中的「1. 考点范围」收拢为紧凑摘要卡片：展示已选数量/覆盖讲义数、最多预览前若干个已选标签、快捷操作（「调整考点」打开抽屉 + 一键全选/清空）。
  - 拆分独立 SFC `KnowledgePointPickerDrawer.vue`（遵守单文件 `<= 270/300` 行约束与 `component-guidelines.md`）：支持关键字搜索、按讲义/章节手风琴折叠（默认仅首组或搜索命中组展开，其余收起）、组内全选/取消、底部固定确认栏。
  - 单讲义出题分组过滤掉已有子节点的 L1 章节标题容器节点，避免章节头占用题量配额。
- **R3.2 优化生题方案（按题量抽考 + 全考点覆盖双模式 & 修复 50 题截断）**：
  - 新增并默认启用**「按题量智能抽考」**模式：当已选考点数 `N > questionCount` 时，滑块设定的题量（扩展支持 `1 ~ 20` 题）真实生效，系统从已选考点中跨讲义均匀抽取 `questionCount` 个代表性考点出题，覆盖率门禁按本次目标抽样考点核算，并清晰提示「将从已选 N 个考点中均匀抽取 K 个考点出 K 题」。
  - 保留**「全考点逐一覆盖」**模式切换：每选考点至少 1 题（`plannedCount = max(selectedKpIds.length, questionCount)`），当已选超过 `MAX_PRACTICE_QUESTIONS (50)` 时明确警告/阻断超限或引导切回抽考模式。
  - 修复 `useQuestionCompose.ts` 中 `fetchBatchQuestions` 硬编码 `page_size=50` 导致的超 50 题截断死锁（改用 `page_size=100` 或按 `total` 翻页拉全），并确保超过 20 题在全覆盖模式下按 `MAX_QUESTION_BATCH = 20` 正确分批/传参，不出现 `count=20` 与后端 `distribute_count` 静默扩增的语义撕裂。

---

## Acceptance Criteria

- [ ] **AC-1**：`App.vue` 无 `-webkit-font-smoothing: antialiased`，`CoachMessageList.vue` 助手消息启用紧凑富文本排版（`24rpx`），`richText.ts` 标题/间距比例收敛，且 `miniprogram` 构建产物无 `backdrop-filter`。
- [ ] **AC-2**：`ask_coach` 与 `coach_graph` 均带有精炼口语化约束与合理 `temperature` / `max_tokens`，既有后端助教单测与结构化输出校验全部通过。
- [ ] **AC-3**：前端 `backgroundTask` 轮询覆盖长解析周期（>= 15 分钟退避）且暴露超时状态，`MaterialCourseHeader.vue` 支持手动刷新进度，`course/index.vue` `onShow` 在非 `ready` 态也主动同步状态。
- [ ] **AC-4**：后端 `parse_material_pipeline` 在解析各阶段推进进度，重解析在提取成功前不提前破坏旧知识点/切片，`worker.py` 终态失败钩子可兜底回收卡死任务，`MaterialDetailResponse` 返回 `error_message` / `failed_stage`。
- [ ] **AC-5**：出题配置页将多余知识点收纳进 `KnowledgePointPickerDrawer.vue`（手风琴折叠 + 搜索 + 分组操作），`questions/index.vue` 与新组件均符合 `< 300` 行约束且无新增 Emoji/裸 Hex。
- [ ] **AC-6**：组卷支持「按题量智能抽考（默认）」与「全考点覆盖」双模式，40 个考点配 10 题滑块时可稳定生成 10 题并正常进入作答；`fetchBatchQuestions` 不再在 50 题处静默截断；同步更新单元测试与 `.trellis/spec/` 文档。
- [ ] **AC-7**：`task verify-backend` 与 `task verify-frontend`（及 `pnpm run build:mp-weixin`）全部通过（注明任何既有墙钟基准测试行为）。
