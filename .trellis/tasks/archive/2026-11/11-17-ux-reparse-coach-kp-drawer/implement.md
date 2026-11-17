# Implementation Plan

## Execution Mode
To be confirmed with user before `task.py start`: **Native Swarm** (2 parallel workspace-isolated authors: `frontend-worker` in `share` workspace + `backend-worker` in `share` workspace, followed by `verifier` check) or sequential subagent waves (`trellis-implement` -> `trellis-check`).

---

## Workstreams

### Workstream A — Backend (`backend/`)
1. **AI Coach Prompt & Options (`coach_graph.py`, `question.py`, `schemas/question.py`)**
   - Update `coach_graph.py` system prompt (conversational, direct conclusion first, 2–3 short bullets, 150–260 chars, no rigid `一、二、三、` textbook outline) and `LLMOptions(temperature=0.45, max_tokens=900)`.
   - Update `QuestionService.ask_coach` system prompt + `LLMOptions(temperature=0.65, max_tokens=900)` + schema field descriptions in `schemas/question.py`.
2. **Material Reparse Reliability & Progress (`services/material.py`, `services/knowledge.py`, `worker.py`, `schemas/material.py`, `api/v1/materials.py`)**
   - Add fine-grained progress reporting across parsing stages (Redis/in-memory progress or stage progression + `on_progress` callback in `KnowledgeService._run_extraction_with_retries`) so progress advances smoothly past 60%.
   - Delay destructive deletion of `material_snippets` / `knowledge_points` in `parse_material_pipeline` until document text/chunks are ready and new knowledge points are validated (preventing empty-material wipe on LLM/download failure).
   - Update `worker.py::handle_job_terminal_failure` to recover orphaned `parse_material_pipeline` jobs by marking `FAILED` with `failed_stage="worker_terminated"`.
   - Allow `MaterialService.trigger_parse(..., force=True)` to recover stale/orphaned active parses (when job is no longer active or exceeds stale threshold) instead of deadlocking forever.
   - Expose `error_message` and `failed_stage` on `MaterialDetailResponse` / `MaterialListItem`.
3. **Backend Tests (`backend/tests/`)**
   - Add/update unit tests for:
     - `ask_coach` & `coach_graph` prompt/options & structured response
     - `parse_material_pipeline` failure preserves prior data / progress updates
     - `handle_job_terminal_failure` marks orphaned material parse `FAILED`
     - `trigger_parse(force=True)` stale recovery & `error_message`/`failed_stage` exposure.

### Workstream B — Frontend (`miniprogram/`)
1. **UI Clarity & AI Coach Styling (`App.vue`, `utils/richText.ts`, `components/CoachMessageList.vue`)**
   - Remove `-webkit-font-smoothing: antialiased` from `App.vue`.
   - Pass `compact` to `<RichContent>` for assistant messages in `CoachMessageList.vue`, tune `.msg-text` (`25rpx`), `.msg-bubble` (`max-width: 86%; padding: 16rpx 20rpx; line-height: 1.5;`).
   - Tighten `HEADING_SIZES` and spacing in `utils/richText.ts`.
2. **Background Polling & Reparse UX (`stores/backgroundTask.ts`, `pages/course/index.vue`, `components/MaterialCourseHeader.vue`, `composables/useCourseDetail.ts`)**
   - Extend `ensurePolling` with staged backoff covering >= 15 minutes, surface `timedOut` state on tasks instead of silent drop, add `refreshTask(materialId)`.
   - Refresh detail + active tasks in `course/index.vue::onShow` when `status !== 'ready'`.
   - Add explicit "刷新进度" button & slow-task notice in `MaterialCourseHeader.vue`; clarify reparse confirmation modal copy in `useCourseDetail.ts`.
3. **Quiz KP Drawer & Smart Compose Strategy (`components/KnowledgePointPickerDrawer.vue`, `components/QuestionConfigPanel.vue`, `composables/useComposeConfig.ts`, `composables/useQuestionCompose.ts`, `utils/composeHelpers.ts`, `pages/questions/index.vue`, `questions.scss`)**
   - Extract `KnowledgePointPickerDrawer.vue` (search, accordion groups collapsed by default except first/matched, group select-all, sticky footer, <= 250 lines, zero Emoji, CSS vars only).
   - Collapse `QuestionConfigPanel.vue` section 1 into compact summary card with preview chips + trigger button + mode selector (`按题量智能抽考` vs `全考点逐一覆盖`), extend count slider max to `20`.
   - Implement `sampleKnowledgePointIds` & leaf-node filtering in `composeHelpers.ts`; wire `composeMode`, `effectiveKpIds`, `plannedCount` in `useComposeConfig.ts`; fix `fetchBatchQuestions` pagination (`page_size=100` + multi-page loop) and `activeTargetKpIds` coverage in `useQuestionCompose.ts`.
4. **Frontend Tests & Build (`miniprogram/tests/`)**
   - Update `tests/diagnosisAndCompose.spec.ts` and add tests for `sampleKnowledgePointIds`, leaf KP filtering, `composeMode` (`smart_sample` vs `full_coverage`), `backgroundTask` timeout/backoff, and `CoachMessageList`/`richText`.
   - Run `pnpm run lint`, `pnpm run type-check`, `pnpm run test:unit`, and `pnpm run build:mp-weixin`.

### Workstream C — Spec Updates & Quality Gates
- Update `.trellis/spec/frontend/hook-guidelines.md`, `.trellis/spec/frontend/quality-guidelines.md`, `.trellis/spec/frontend/index.md`, and `.trellis/spec/backend/quality-guidelines.md` (if contracts changed) via `trellis-update-spec` or verified doc edits.
- Run `task verify-backend` and `task verify-frontend`.
