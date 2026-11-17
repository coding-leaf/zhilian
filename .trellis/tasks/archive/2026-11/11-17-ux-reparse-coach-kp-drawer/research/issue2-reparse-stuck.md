# Research: Issue 2 — Re-parsing Material Stuck at 60% (`第六章 - 降维算法.pdf`)

- **Query**: Investigate why re-parsing `第六章 - 降维算法.pdf` appeared stuck at `"正在提取知识点与原文切片，已完成 60%..."` and prevented viewing the new structured knowledge points ("新版知识点简介").
- **Scope**: Backend material parsing / re-parsing pipeline (`backend/app/api/v1/materials.py`, `backend/app/services/material.py`, `backend/app/services/_material_pipeline.py`, `backend/app/services/knowledge.py`, `backend/app/worker.py`, `backend/app/integrations/queue/`, `backend/app/integrations/llm/`), PostgreSQL & Redis/RQ runtime state (read-only), recent commits (`5c981b0`, `d422efe`, `b6cf493`), and frontend polling/UI (`miniprogram/src/stores/backgroundTask.ts`, `miniprogram/src/stores/material.ts`, `miniprogram/src/utils/poller.ts`, `miniprogram/src/utils/materialState.ts`, `miniprogram/src/subpackages/material/composables/useCourseDetail.ts`, `miniprogram/src/subpackages/material/pages/course/index.vue`, `miniprogram/src/components/BackgroundTaskBar.vue`).
- **Date**: 2026-11-17

---

## Executive Summary (Verified Root Cause)

The job for `第六章 - 降维算法.pdf` **did not crash or deadlock on the backend** — it took **7 minutes 3 seconds (423.15s)** in total, spending **6 minutes 38 seconds (398.3s)** inside `KnowledgeService.extract_and_build_knowledge_tree()` at `parse_status = extracting_knowledge` (**60%**).

Meanwhile, the frontend background poller (`useBackgroundTaskStore.ensurePolling` in `miniprogram/src/stores/backgroundTask.ts:213`) has a **hard 5-minute polling cap** (`maxAttempts = 120`, `intervalMs = 2500` = `300s`). At the 5-minute mark (`14:30:32Z`), `poller.run()` returned `{ status: 'timeout' }`, which `ensurePolling` **silently ignored** — leaving `material.status = 'parsing'` and `progress_percentage = 60` frozen forever in the UI (`"正在提取知识点与原文切片，已完成 60%..."`), with no error toast, no retry, and no refresh button. Thirty-four seconds before this investigation started (`14:32:36Z`), the backend worker cleanly finished writing **35 structured knowledge points** and set `status = 'ready'`.

In addition to this primary dual-cause (**frontend 5-minute silent polling timeout** + **backend 60% progress plateau during slow multi-batch sequential LLM extraction**), auditing the pipeline uncovered **4 critical latent bugs** in re-parsing & failure recovery (see Findings §4).

---

## Findings

### 1. Empirical Evidence from Runtime Environment (Read-Only Inspection)

- **Active environment (`backend/.env` via `get_settings()`)**: `db_dialect = postgresql+psycopg`, `queue_provider = redis` (`immediate_mode = False`), `storage_provider = minio`, `llm_provider = openai` (`model = deepseek-flash`, `timeout = 30.0`, `max_retries = 3`), `embedding_provider = openai` (`timeout = 20.0`), `search_provider = pgvector`.
  - Note: `backend/zhilian_dev.db` is an unused SQLite file from `2026-09-25` containing only two old `png` rows; live data resides in PostgreSQL (`zhilian-postgres`) and Redis (`zhilian-redis`) with worker container `deploy-worker-1`.
- **PostgreSQL + RQ Timeline for `第六章 - 降维算法.pdf`** (`material_id = ea375e00-282f-43e8-acda-d0703b010793`, `version_id = 552f5114-d534-45d1-b8cd-f2ac5dcd6d03`, RQ job `f8b8abb5-59bf-4f48-8c4b-fbdb4a2f19c0`):
  - `14:25:32.833Z` (22:25:32+08:00): Re-parse enqueued (`force = 'true'`).
  - `14:25:32.875Z`: Worker `deploy-worker-1` started job.
  - `14:25:57.108Z` (+24.2s): `chunk_embed_and_replace_snippets` inserted **238 `material_snippets`**.
  - `14:25:57.658Z` (+24.8s): `material_versions.parse_status` updated to `extracting_knowledge` (**60%**).
  - `14:25:57Z → 14:30:32Z` (+5m00s): Frontend `ensurePolling` reached 120 attempts (300s) and **silently stopped polling** while backend was still in `extract_and_build_knowledge_tree`.
  - `14:32:35.961Z` (+7m03s): Worker inserted **35 `knowledge_points`** (all 35/35 have `structured_content` populated with `core_summary`, `key_takeaways`, `key_formulas`, `boundary_notes`).
  - `14:32:36.005Z`: `materials.status` updated to `ready`; `material_versions.parse_status = 'ready'`; RQ job finished in `0:07:03.145416`.
  - `14:33:10Z`: User report timestamp (34s after backend finished; user's UI was still frozen at 60% since `14:30:32Z`).

### 2. What "新版知识点" and "简介" Refer To (Recent Commits)

- **`5c981b0` (backend) & Alembic `0011_structured_kp_and_question_jobs`**:
  - Added `KnowledgePoint.structured_content` (`JSON/JSONB`: `core_summary`, `key_takeaways`, `key_formulas`, `boundary_notes`) and `sort_order` (`backend/app/models/knowledge.py:76-88`, `backend/migrations/versions/0011_structured_kp_and_question_jobs.py:27-44`).
  - Added `force: bool = False` on `POST /materials/{material_id}/parse` (`backend/app/api/v1/materials.py:465,480-488`) and PDF symbol-font/ASCII garble repair (`repair_garbled_pdf_pages` in `backend/app/services/_material_pipeline.py:236-265`).
  - Materials parsed on `2026-09-29` (e.g. `第二章 - 广义线性回归.pdf` has 23 KPs with `0` `structured_content`) lack the new structured fields.
- **`b6cf493` & `d422efe` (frontend)**:
  - `KnowledgePointList.vue:52-54` renders `formatKpSummaryPreview(node)` (`courseStudy.ts:131-136`) — reading `structured_content.core_summary` (falling back to `description`) as the card's 2-line brief ("简介").
  - `KnowledgeSnippetModal.vue:23-80` renders the 4 structured sections (`核心定义`, `关键结论`, `核心公式与符号`, `适用条件与易错边界`), and line 108 prompts users on garbled legacy snippets: `"检测到旧版讲义公式编码异常，点击右上角「重新解析」即可修复"`.

### 3. Why It Appeared Stuck at 60% (End-to-End Trace)

#### A. Backend: 60% Progress Plateau + Multi-Batch Sequential LLM Extraction
1. **Dispatch (`backend/app/api/v1/materials.py:454-496`, `backend/app/services/material.py:1138-1257`)**:
   - `MaterialService.trigger_parse(..., force=True)` transitions `version.parse_status` from `ready` → `queued` via `try_transition_version_status` (`repositories/material.py:594-640`), sets `material.status = 'parsing'`, commits, and calls `RQQueueAdapter.enqueue("parse_material_pipeline", ...)` (`rq_adapter.py:40-92`, `job_timeout=1800`, `retry=Retry(max=3)`).
2. **Progress Mapping Gap (`backend/app/services/material.py:458-485, 810-840`)**:
   - `_calculate_progress_percentage` defines: `queued=10`, `parsing_doc=30`, `extracting_knowledge=60`, `auditing_knowledge=75`, `embedding_generation=85`, `ready=100`.
   - However, `parse_material_pipeline`:
     - Line 459–461: Sets `current_stage = "embedding_generation"` (local variable only), then writes `ParseStatus.EXTRACTING_KNOWLEDGE.value` (**60%**) to DB before `chunk_embed_and_replace_snippets()`.
     - Line 476–479: Sets `current_stage = "knowledge_extraction"`, then writes `ParseStatus.EXTRACTING_KNOWLEDGE.value` (**60%**) to DB *again* before `knowledge_service.extract_and_build_knowledge_tree()`.
     - `AUDITING_KNOWLEDGE` (75%) and `EMBEDDING_GENERATION` (85%) are **never written** by the pipeline. Thus progress jumps `30% → 60% → 100%`.
3. **Why `extract_and_build_knowledge_tree` Took 6m38s (`backend/app/services/knowledge.py:191-328`)**:
   - `第六章 - 降维算法.pdf` produced **238 snippets**.
   - `_run_extraction_with_retries` (`knowledge.py:245-328`) iterates **synchronously and sequentially** over `batches` (`batch_size=40` → 6 LLM calls).
   - Each call invokes `run_structured_agent_workflow` (`backend/app/integrations/llm/agent_graph.py:282-331`) with `LLMOptions(temperature=0.3, timeout=60.0)` and `tool_choice="auto"` against `deepseek-flash` (noted in `agent_graph.py:81-84` as a thinking-mode model; slow per-call latency, plus up to 1 LangGraph schema-repair retry × 3 HTTP retries per call).
   - After all batches complete, it embeds all extracted KPs (`knowledge.py:291`), deduplicates, and runs `verify_knowledge_points` (`backend/app/core/algorithms/knowledge_quality.py:591-660`).
   - If the quality gate fails (quantity density `625~5000` chars/KP, hierarchy depth `2~5`, `level_2_ratio <= 0.60`, naming readability `2~30` chars, or chapter coverage `>= 80%`), it **re-runs the entire document** with `current_batch_size = 20` (**12 sequential LLM calls**) up to 2 retries (`re_extract_count <= 2`, max `6 + 12 + 12 = 30` sequential LLM calls) with **zero intermediate DB progress updates**.

#### B. Frontend: Silent 5-Minute Polling Timeout & Missing Recovery UX
1. **`startParse(true)` hides KPs (`miniprogram/src/subpackages/material/composables/useCourseDetail.ts:119-143`, `pages/course/index.vue:17`)**:
   - Optimistically sets `material.status = 'parsing'`, `parse_status = 'queued'`, `progress_percentage = 0`.
   - `course/index.vue:17` gates `<KnowledgePointList v-if="course.material.value?.status === 'ready'" />`, so existing KPs disappear immediately.
   - `parseProgressText` (`useCourseDetail.ts:32-37`) formats `progress_percentage = 60` as `"正在提取知识点与原文切片，已完成 60%..."`.
2. **Silent Polling Timeout at 5 Minutes (`miniprogram/src/stores/backgroundTask.ts:213-226`, `utils/poller.ts:71-101`)**:
   - `ensurePolling(intervalMs = 2500, maxAttempts = 120)` only polls for `120 × 2.5s = 300s (5 minutes)`.
   - `poller.run()` returns `{ status: 'timeout', lastValue }` on line 94, but `ensurePolling` **discards the return value** and sets `isPolling.value = false`.
   - The active task stays in `materialTasks` with `status: 'parsing'`, `progressPercentage: 60`, and `dismissible: false` (`backgroundTask.ts:310-325`).
   - Note: `useMaterialStore.pollMaterialStatus` (`stores/material.ts:51-68`) is even shorter (`maxAttempts = 20, interval = 1500` = 30s), though `useCourseDetail` goes through `backgroundTaskStore`.
3. **No Recovery Path in Course UI (`course/index.vue:89-98`, `MaterialCourseHeader.vue:30-33`)**:
   - `MaterialCourseHeader.vue:30-33` shows only the spinner and `parseProgressText` when `isParsing` — there is **no "刷新进度" button** and no timeout/slow-task hint.
   - `course/index.vue:89-93` `onShow` only calls `refreshMastery()` when `status === 'ready'`; if `status === 'parsing'`, navigating away and back does **not** re-fetch `loadDetail()`. Only `onPullDownRefresh` (`course/index.vue:95-98`) or clicking the `BackgroundTaskBar` strip (`handleOpenTask` at line 106, which only refreshes on tap) triggers `loadDetail()`.

---

### 4. Latent Failure & Deadlock Risks Found in the Re-parse Pipeline

1. **CRITICAL — Orphaned `parsing` Deadlock (Crash / OOM / `job_timeout=1800` Unrecoverable)**:
   - `backend/app/worker.py:170-220` (`handle_job_terminal_failure`) explicitly **skips** `parse_material_pipeline`:
     > `# 解析链路的失败回写由 MaterialService 内部负责，这里只保留运维日志` (lines 181-183, 218-220).
   - If the worker dies via `SIGKILL` / OOM / container restart or hits RQ's `job_timeout = 1800s` (or on Windows `SimpleWorker` blocks/crashes, `worker.py:100-107`), `parse_material_pipeline`'s `except Exception` (`material.py:514-524`) never runs.
   - Then `version.parse_status` remains `'extracting_knowledge'` (or `'parsing_doc'`/`'queued'`) and `material.status` remains `'parsing'` forever.
   - Worse, `MaterialService.trigger_parse` (`material.py:1198-1201`) blocks all requests when `target_version.parse_status in active_statuses` **even when `force=True`** (`force` only bypasses `READY`), and `retry_material_pipeline` (`material.py:556`) requires `parse_status == 'failed'`. Thus an orphaned `parsing` record has **no API recovery path**.
2. **HIGH — Destructive `force=True` Wipe Before Extraction + Cascade Deletion of Questions & Mastery**:
   - `MaterialService.parse_material_pipeline` (`material.py:396-401`) deletes all `knowledge_points` and `material_snippets` for `(material_id, version_id)` and calls `self.session.commit()` **before** fetching/parsing the file or extracting new KPs.
   - `Question.knowledge_point_id` (`backend/app/models/question.py:138`) and `MasteryRecord.knowledge_point_id` (`backend/app/models/practice.py:688`) both have `ForeignKey("knowledge_points.id", ondelete="CASCADE")`.
   - Therefore:
     - Re-parsing with `force=True` **cascade-deletes all generated `Question` rows and `MasteryRecord` rows** for that version (despite the frontend confirmation modal in `useCourseDetail.ts:153` claiming `"已有练习记录会保留"` — `AttemptItem` snapshots stay, but question bank & mastery records are wiped).
     - If re-extraction fails after line 401, the material is left with **0 snippets and 0 knowledge points**.
3. **MEDIUM — `MaterialDetailResponse` / `MaterialListItem` Omit `error_message` and `failed_stage`**:
   - `MaterialCourseHeader.vue:36` reads `material.error_message` when `status === 'failed'`, but `MaterialDetailResponse` and `MaterialListItem` (`backend/app/schemas/material.py:73-126`, `backend/app/api/v1/materials.py:308-324, 390-406`) do not expose `error_message` or `failed_stage`, so failures always fall back to the generic string `'文档内容异常或排队超时'`.
4. **LOW — Stale Historical Redis Key**:
   - Redis contains an orphaned `rq:job:a95803aa-5a57-4bb6-8b98-43d23a6fe6bf` (`status=queued`, created `2026-09-28T18:40:07Z`, not present in any `zhilian` / `zhilian_high` queue list).

---

## Files Found

| Path | Role |
| --- | --- |
| `backend/app/api/v1/materials.py` | `/materials/{id}/parse` (`trigger_material_parse`:454-496), `get_material_detail`:358-406, `retry_material_pipeline`:643-688 |
| `backend/app/services/material.py` | `parse_material_pipeline`:349-524, `_calculate_progress_percentage`:810-840, `trigger_parse`:1138-1224, `_enqueue_parse`:1225-1257 |
| `backend/app/services/_material_pipeline.py` | `repair_garbled_pdf_pages`:236-265, `chunk_embed_and_replace_snippets`:268-306, `mark_pipeline_failed`:309-338 |
| `backend/app/services/knowledge.py` | `KnowledgeService._extract_batch_points`:191-215, `_run_extraction_with_retries`:245-328, `extract_and_build_knowledge_tree`:330-455 |
| `backend/app/core/algorithms/knowledge_tree.py` | `ExtractedKnowledgeItem`, `build_structured_content`, `deduplicate_candidate_points`, `resolve_knowledge_hierarchy` |
| `backend/app/core/algorithms/knowledge_quality.py` | `verify_knowledge_points` quality gate & retry rules (max 2 re-extracts) |
| `backend/app/integrations/llm/agent_graph.py` | LangGraph structured output workflow (`tool_choice="auto"` for thinking models, single repair retry) |
| `backend/app/integrations/llm/openai.py` | `OpenAICompatibleLLMAdapter` HTTP client & exponential backoff retry (`max_retries=3`) |
| `backend/app/integrations/queue/rq_adapter.py` | `RQQueueAdapter` (`job_timeout=1800`, `Retry(max=3)`, `on_failure=handle_job_terminal_failure`) |
| `backend/app/worker.py` | RQ worker entry (`execute_registered_task`:81-90, `run_worker`:93-107, `handle_job_terminal_failure`:170-226) |
| `backend/app/models/material.py` | `Material`, `MaterialVersion`, `ParseStatus`, `MaterialSnippet` |
| `backend/app/models/knowledge.py` | `KnowledgePoint` (`structured_content`, `sort_order`), `KnowledgePointSnippet` |
| `backend/app/models/question.py` | `Question.knowledge_point_id` (`ondelete="CASCADE"`) |
| `backend/app/models/practice.py` | `MasteryRecord.knowledge_point_id` (`ondelete="CASCADE"`) |
| `backend/app/schemas/material.py` | `MaterialDetailResponse`, `MaterialListItem`, `MaterialParseRequest` (missing `error_message`/`failed_stage`) |
| `backend/migrations/versions/0011_structured_kp_and_question_jobs.py` | Migration adding `structured_content`, `sort_order`, and `question_generation_jobs` |
| `miniprogram/src/stores/backgroundTask.ts` | `useBackgroundTaskStore`: `ensurePolling` 5-min silent timeout (:213-226), `startMaterialParse` (:151-168) |
| `miniprogram/src/stores/material.ts` | `useMaterialStore`: `pollMaterialStatus` 30s default (:51-68), `triggerParse` (:35-37) |
| `miniprogram/src/utils/poller.ts` | `createPoller`: returns `{ status: 'timeout', lastValue }` on `maxAttempts` (:94) |
| `miniprogram/src/utils/materialState.ts` | `isMaterialParsing`, `canStartMaterialParse`, `materialStatusText` |
| `miniprogram/src/subpackages/material/composables/useCourseDetail.ts` | `parseProgressText` (:32-37), `startParse` (:119-143), `confirmAndReparse` (:145-159) |
| `miniprogram/src/subpackages/material/pages/course/index.vue` | `onShow` (:89-93), `onPullDownRefresh` (:95-98), `v-if="status === 'ready'"` (:17) |
| `miniprogram/src/subpackages/material/components/MaterialCourseHeader.vue` | Parsing status box without refresh/timeout fallback (:30-33), `error_message` usage (:36) |
| `miniprogram/src/subpackages/material/components/KnowledgePointList.vue` | Renders `core_summary` preview ("简介") |
| `miniprogram/src/subpackages/material/components/KnowledgeSnippetModal.vue` | Renders structured KP detail & `"重新解析"` prompt (:108) |
| `miniprogram/src/components/BackgroundTaskBar.vue` | Sticky task bar displaying `解析中 (60%)` |

---

## Relevant `.trellis/spec/` Files (Candidate List)

- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/logging-guidelines.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/spec/frontend/network-contract.md`
- `.trellis/spec/frontend/quality-guidelines.md`
- `.trellis/spec/frontend/type-safety.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`

---

## Caveats / Open Questions

1. **Already-resolved state in local DB**: `第六章 - 降维算法.pdf` is now `status = 'ready'` in PostgreSQL with 35 structured KPs; simply refreshing/re-entering its course page will display them. However, **any** large PDF (>~150–200 snippets) or quality-gate retry will still exceed 5 minutes and reproduce the exact same "stuck at 60%" UX bug.
2. **Existing Question/Mastery loss on `force=True`**: Because `第六章 - 降维算法.pdf` had `0` questions and `[]` practices in PostgreSQL, no questions were lost this time, but materials with existing questions/mastery records (`贝叶斯分类器.pdf` has 9 questions, `Maven基础讲义` has 21/11) **will** have their questions and mastery records cascade-deleted if re-parsed with `force=True`.
3. **Unknown whether quality gate retried inside `f8b8abb5`**: Worker stdout only logs RQ job start/end (`423.15s`), not per-batch LLM timing or `re_extract_count`, because `logger.info` inside `KnowledgeService` is emitted at app log level and not shown in `deploy-worker-1`'s RQ stdout tail.
