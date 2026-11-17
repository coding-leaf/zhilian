# Backend Architecture & Redundancy Audit (`backend/**`)

> Audited on `chore/workspace-configs` (read-only static & AST inspection on 2026-11-17).
> Specs inspected: `.trellis/spec/backend/index.md`, `directory-structure.md`, `database-guidelines.md`, `error-handling.md`, `logging-guidelines.md`, `material-statistics.md`, `quality-guidelines.md`.

## Executive Summary

- **Codebase Scale**: `255` Python files / `87,388` LOC (`app/`: `135` files / `40,790` LOC; `migrations/`: `13` files / `1,536` LOC; `tests/`: `107` files / `45,062` LOC; no `backend/scripts/`).
- **Static Gates Snapshot** (`$env:PYTHONIOENCODING='utf-8'`, Windows host `pwsh`): `ruff format --check .` (pass, 256 files), `ruff check .` (pass), `mypy app` (pass, 135 files), `lint-imports` (pass, 5 contracts / 943 deps). However, `[tool.ruff.lint.mccabe] max-complexity = 28` masks extreme god-methods (up to **CC=73 / 417 LOC**).
- **Top Structural Bottlenecks**:
  1. **God Services** (`question.py` 1,901L, `material.py` 1,668L, `diagnosis.py` 1,495L, `practice.py` 1,372L, `grading.py` 1,051L, `knowledge.py` 834L) mix DTOs, LLM prompt/schema parsing, file/OOXML extraction, raw SQLAlchemy `select()` queries, ORM monkey-patching, and transaction commits.
  2. **Router & DI Leaks**: `api/v1/diagnosis.py`, `materials.py`, `practices.py`, `questions.py` execute multi-service orchestration, legacy-shape shims, and `app.integrations` imports; 7 `api/deps/*.py` files copy-paste 54-line boilerplate with an unclosed `session_factory()` fallback leak.
  3. **Inconsistent LLM & Retry Plumbing**: `KnowledgeService` double-invokes `run_structured_agent_workflow` on failure; `QuestionService` bypasses `LLMProtocol.generate_structured`; 5 integration adapters hand-roll identical exponential-backoff retry loops.
- **Dead / Duplicate Hotspots**: `pyproject.toml` puts runtime dependency `httpx` inside `[project.optional-dependencies].dev` while `cryptography` has 0 direct imports; 20+ repository alias/test-only methods, 7 zero-app-caller service methods, 3 unused error classes, 3 copy-pasted `_log_metric` implementations, and ~15 Schema `model_validator` bidirectional alias shims bloat the surface.
- **Recommended Refactoring Plan**:
  - **Phase A (Safe Hygiene)**: Fix `pyproject.toml` (`httpx` to runtime deps), delete zero-caller aliases/errors/methods, extract shared `api/deps/_factory.py` (fixing the unclosed session leak), shared `core/logging.py` metric helper, and shared `integrations/_http_retry.py`.
  - **Phase B (Layer Hardening)**: Move inline `select()`/`delete()` from `GradingService`/`PracticeService`/`MaterialService` into repositories; remove `api/v1/practices.py -> app.integrations` and `FolderService -> MaterialService.repo` Law-of-Demeter coupling; replace ORM attribute monkey-patching (`# type: ignore[attr-defined]` / `# noqa: B010`) with explicit Service DTOs.
  - **Phase C (God-Module Decomposition)**: Split `QuestionService`, `MaterialService`, `DiagnosisService` (`generate_diagnosis_report`), `PracticeService`, and `GradingService` into focused sub-modules (extractors, assemblers, LLM prompt/parser adapters); lower Ruff `max-complexity` from `28` to `<= 15`.

---

## 1. Complexity & Oversized Module Inventory

### 1.1 Oversized Source Modules (`backend/app/**` > 300 LOC)

| File Path | LOC | Largest Class / Function (AST) | Entangled Responsibilities | Target Split |
| --- | ---: | --- | --- | --- |
| `app/services/question.py` | 1,901 | `QuestionService` (1,290L); `generate_questions` (323L, CC=45); `_normalize_item` (89L, CC=45) | LLM Pydantic schemas & normalizers + prompt builders + RAG retrieval + quality gating + multi-KP/folder orchestration + CRUD/audit + AI coach | Extract `schemas/question_llm.py`, `services/question_generation.py`, `services/question_coach.py` |
| `app/services/material.py` | 1,668 | `MaterialService` (1,316L); `parse_material_pipeline` (213L, CC=18); `retry_ocr_pages` (161L, CC=20) | Binary magic validation + PDF/DOCX/PPTX OOXML parsing + upload/storage + 7-commit pipeline orchestration + OCR page retake + ORM monkey-patching | Extract `core/extractors/ooxml.py` & `pdf.py`, `services/material_pipeline.py`, `services/material_ocr.py`, explicit DTO mapper |
| `app/services/diagnosis.py` | 1,495 | `DiagnosisService` (1,282L); `generate_diagnosis_report` (**417L, CC=73**) | Legacy `MasteryRecordList` dict/list shim + mapping helpers + metric logger + mastery calculation + giant report synthesizer + wrong-book CRUD | Split into `services/mastery.py`, `services/diagnosis_report.py` (break `generate_diagnosis_report` into 4 helpers), `services/wrong_book.py` |
| `app/services/practice.py` | 1,372 | `PracticeService` (1,212L); `_assemble_and_persist_practice` (231L, CC=41); `submit_practice` (212L, CC=13) | Direct factory instantiation + raw `select()` queries + assembly strategies + session lifecycle + idempotent submission + snippet monkey-patching | Extract `services/practice_assembler.py`, `services/practice_submission.py`; push `select()` to repos |
| `app/core/errors.py` | 1,316 | 44 `AppError` subclasses (~30L boilerplate each) | Per-class verbose `__init__` delegating `details`/`detail` and docstrings | Declarative class attributes (`default_code`, `default_status`, `default_message`) on `AppError` base |
| `app/services/grading.py` | 1,051 | `GradingService` (910L); `regrade_attempt` (189L, CC=25); `self_evaluate_attempt` (166L, CC=27); `grade_practice` (140L, CC=23) | 6 internal DTOs + raw `select(AttemptItem)` x3 + duplicated LLM subjective grading prompt/scoring in `_grade_with_llm` & `regrade_attempt` + arg-overload shims | Extract shared `_invoke_subjective_llm_grading()` + `GradingRepository.get_attempt_item_by_id()`; drop `*args` signature overload |
| `app/core/algorithms/grading.py` | 1,038 | `_handle_subjective_grading` (92L); `_grade_fill_blank` (51L, CC=17) | Objective matching, negation inversion, fill-blank, rubric matching, subjective heuristics | Split into `algorithms/grading_objective.py` & `algorithms/grading_subjective.py` |
| `app/repositories/material.py` | 959 | `MaterialRepository` (926L, 34 methods) | CRUD + statistics + folder filter + versions + snippets + OCR pages + 8 duplicate alias/bulk methods | Remove test-only alias wrappers; split into `MaterialRepo`, `MaterialVersionRepo`, `MaterialOCRRepo` if needed |
| `app/models/practice.py` | 956 | 6 `StrEnum` + 3 validators + 6 ORM models (`Practice` 170L, `GradingRecord` 122L, `WrongRecord` 111L) | Practice, Grading, Mastery, DiagnosisReport, WrongRecord models all in one file | Split `MasteryRecord`/`DiagnosisReport`/`WrongRecord` into `models/diagnosis.py` |
| `app/core/algorithms/question_quality.py` | 869 | `evaluate_single_question` (126L) | Heuristic scoring, similarity, rubric validation, quality gate | Cohesive pure module; extract rubric validation helpers |
| `app/api/v1/materials.py` | 836 | `list_materials` (82L), `upload_material` (50L), `move_material_folder` (48L) | Upload streaming guard + background task runner + alias `run_parse_material_background` + multi-service coordination + pagination math | Move pagination & DTO mapping to shared dependency/service; move background runner to `app/tasks/` |
| `app/services/knowledge.py` | 834 | `KnowledgeService` (528L); `extract_and_build_knowledge_tree` (216L, CC=24) | LLM schemas + pure tree/dedup algorithms (`compute_chapter_stats`, `deduplicate_candidate_points`, `build_knowledge_hierarchy`) + service | Move pure tree/dedup functions to `core/algorithms/knowledge_tree.py` |
| `app/repositories/question.py` | 819 | `QuestionRepository` (791L, 25 methods); `list_questions` (92L, CC=21) | Questions + batches + folder-scoped KPs + quality checks + audit logs + duplicated `_apply_folder_filter` | Share folder visibility query helper; split audit/quality check repo |
| `app/schemas/practice.py` | 768 | `PracticeItemDetailResponse.synchronize_item_fields` (91L, CC=32); `synchronize_detail_fields` (70L, CC=29) | Heavy `@model_validator` bidirectional alias syncing (`id`/`practice_id`/`attempt_item_id`, `duration_seconds`/`time_spent_seconds`, `total_count`/`question_count`) | Converge wire contract field names and eliminate legacy alias sync |
| `app/repositories/diagnosis.py` | 685 | `DiagnosisRepository` (656L, 21 methods) | Reports + mastery + attempt history + wrong records + duplicated filter in `list_wrong_records`/`count_wrong_records` | Extract shared `_build_wrong_record_stmt()`; separate wrong-book repo |
| `app/core/algorithms/knowledge_quality.py` | 660 | `check_quantity_range` (114L); `verify_knowledge_points` (70L, CC=16) | Pure quality checks | Keep pure; simplify `verify_knowledge_points` branches |
| `app/core/algorithms/diagnosis.py` | 606 | `synthesize_diagnosis_report` | Pure diagnosis synthesis | Acceptable pure module |
| `app/models/material.py` | 584 | 4 enums + 5 ORM models (`Material`, `MaterialFolder`, `MaterialVersion`, `MaterialSnippet`, `MaterialOCRPage`) | Acceptable model definitions | Keep or extract `MaterialFolder` |
| `app/schemas/diagnosis.py` | 579 | `UserMasteryOverviewResponse` (`_sync_fields` CC=26, `_sync_after` CC=25) | Triple/double alias syncing (`overall_score`/`overall_mastery_score`, `weak_points`/`weak_knowledge_points`/`points`, etc.) | Deprecate legacy field aliases |
| `app/api/v1/questions.py` | 558 | `generate_questions` (78L), `list_questions` (70L), `_build_generate_response` (42L) | Router-level source-snippet attachment & multi-branch generation dispatch | Move dispatch & snippet attachment into `QuestionService` |
| `app/cli/smoke.py` | 544 | `SmokeRunner` (424L) | 11-stage CLI smoke harness | Split stage helpers if expanded |
| `app/services/auth.py` | 521 | `AuthService` (431L) | Image magic detection + WeChat OAuth HTTP + JWT/profile/avatar + alias methods | Move `_detect_image_type` to shared magic-byte helper |
| `app/core/algorithms/mastery.py` | 520 | Pure mastery scoring | Pure algorithm | Cohesive |
| `app/api/v1/diagnosis.py` | 489 | `list_wrong_records` (96L, CC=15) | Multi-shape service fallback, 3 service calls per request, router-side DTO mutation | Move assembly into `DiagnosisService.list_wrong_records_page()` |
| `app/api/v1/practices.py` | 484 | `submit_practice` (80L) | Direct `app.integrations` import + redundant `try/except: raise` + duplicate call branch | Move idempotency-key validation to service/schema; remove dead try/except |
| `app/core/config.py` | 482 | `AppSettings` + 8 nested settings models | Typed config | Cohesive |
| `app/repositories/knowledge.py` | 462 | `KnowledgeRepository` (439L, 20 methods) | 4 duplicate alias methods + CRUD | Remove alias wrappers |
| `app/integrations/ocr/baidu.py` | 450 | `BaiduOCRAdapter` (418L); `_execute_with_retry` (114L, CC=22) | OAuth token cache + HTTP retry loop + response parser | Extract shared HTTP retry helper |
| `app/models/question.py` | 428 | `validate_question_payload` (45L, CC=24) | 3 models + payload validator | Acceptable |
| `app/repositories/folder.py` | 427 | `FolderRepository` (402L) | Folder CRUD + 5 batch group-count queries | Cohesive |
| `app/integrations/storage/s3.py` | 423 | `S3StorageAdapter` (393L) | Boto3 wrapper | Cohesive |
| `app/integrations/container.py` | 422 | `ProviderRegistry` (391L); `create_default` (116L) | 7-provider factory wiring + lifecycle | Cohesive |
| `app/repositories/practice.py` | 416 | `PracticeRepository` (390L) | Practice + AttemptItem CRUD + CAS transitions | Cohesive |
| `app/core/algorithms/material_chunking.py` | 387 | `split_material_into_snippets` (117L) | Pure text chunking | Cohesive |
| `app/schemas/question.py` | 383 | Request/response schemas | Acceptable | Acceptable |
| `app/services/folder.py` | 381 | `FolderService` (325L) | Folder CRUD + lazy purge + `MaterialService.repo` reach-through + inline `QuestionRepository` | Inject `MaterialRepository` & `QuestionRepository` directly |
| `app/integrations/llm/agent_graph.py` | 354 | LangGraph structured output state machine | Unused `RunnableConfig` params | Remove unused `RunnableConfig` import/args |
| `app/core/algorithms/ocr_quality.py` | 349 | `evaluate_page_quality` (87L) | Pure OCR quality scoring | Cohesive |
| `app/cli/commands/material.py` | 347 | CLI subcommands | Acceptable | Acceptable |
| `app/container.py` | 343 | `AppContainer` | 8 service factories + 9 `get_*_service` aliases + `self.registry` alias | Drop `get_*_service` & `registry` aliases |
| `app/cli/context.py` | 342 | `assert_real_providers` (123L) | CLI bootstrap & real-provider checks | Acceptable |
| `app/integrations/queue/redis.py` | 336 | Redis/RQ adapter | Hand-rolled retry loop | Share retry helper |
| `app/integrations/ocr/tencent.py` | 335 | `TencentOCRAdapter` (305L); `_parse_response` (82L, CC=31) | TC3-HMAC-SHA256 signer + HTTP retry loop + parser | Extract shared HTTP retry helper; simplify `_parse_response` |
| `app/integrations/storage/memory.py` | 333 | `MemoryStorageAdapter` (306L) | Test/dev adapter | Acceptable |
| `app/api/v1/folders.py` | 317 | `list_folder_knowledge_points` (41L) | Grouping logic in router (`L138-163`) | Move grouping assembly into `FolderService` or helper |
| `app/integrations/queue/memory.py` | 304 | `MemoryQueueAdapter` | Test/dev adapter | Acceptable |

> Note: `pyproject.toml:55` sets `[tool.ruff.lint.mccabe] max-complexity = 28`, hiding 30+ functions with CC >= 15 (including `generate_diagnosis_report` CC=73, `generate_questions` CC=45, `_normalize_item` CC=45, `_assemble_and_persist_practice` CC=41, `synchronize_item_fields` CC=32, `TencentOCRAdapter._parse_response` CC=31, `synchronize_detail_fields` CC=29).

---

## 2. Layering Violations & Structural Confusion

### P0 — Critical Layering & Lifecycle Issues

1. **Unclosed `session_factory()` Fallback Leak in 7 `api/deps/*.py` Modules**
   - **Evidence**:
     - `app/api/deps/diagnosis.py:45-48`, `folder.py:45-48`, `grading.py:45-48`, `knowledge.py:45-48`, `material.py:45-48`, `practice.py:45-48`, `question.py:45-48`:
       ```python
       actual_session = (
           session if isinstance(session, Session) else container.session_factory()
       )
       return container.create_<domain>_service(session=actual_session)
       ```
     - Contrast with `app/api/deps/user.py:48-51`, which properly wraps the fallback in `with container.get_session() as managed_session: yield ...`.
     - Furthermore, `app/api/deps/__init__.py:14` imports `get_db_session` from `app.api.deps.knowledge` instead of `app.api.deps.db`.
   - **Impact**: If `get_db_session` is not injected (e.g. direct dependency call or override edge case), `container.session_factory()` opens a raw SQLAlchemy `Session` that is never closed, leaking DB pool connections; additionally, 7 files duplicate the exact same 54-line file.
   - **Prescription**: Replace the 7 near-identical files with a single parameterized generator factory helper in `app/api/deps/_factory.py` using `with container.get_session()` on fallback, and fix `app/api/deps/__init__.py:14` to import `get_db_session` from `app.api.deps.db`.

2. **Double LangGraph Invocation Bug & Inconsistent LLM Dispatch**
   - **Evidence**:
     - `app/integrations/llm/openai.py:254-275` (`OpenAICompatibleLLMAdapter.generate_structured`) and `app/integrations/llm/fake.py:197-242` (`FakeLLMAdapter.generate_structured`) ALREADY delegate to `run_structured_agent_workflow`.
     - `app/services/knowledge.py:373-388` (`KnowledgeService._extract_batch_points`): calls `run_structured_agent_workflow(...)` directly in a `try:` block, then on `except Exception:` calls `self.llm.generate_structured(...)` — which runs the exact same LangGraph workflow a **second time**, doubling latency/token burn on transient failures and masking the original traceback.
     - `app/services/question.py:876-881` (`QuestionService.generate_questions`): bypasses `self.llm.generate_structured(...)` and calls `run_structured_agent_workflow(adapter=self.llm, ...)` directly, while `QuestionService.ask_coach` (`question.py:1813`), `coach_graph.py:83`, and `GradingService` (`grading.py:510, 875`) call `llm.generate_structured(...)`.
   - **Prescription**: Standardize all services on `self.llm.generate_structured(...)` behind `LLMProtocol`; remove direct `run_structured_agent_workflow` imports from `app/services/knowledge.py:35` and `app/services/question.py:40`, and delete the self-defeating fallback block at `knowledge.py:381-388`.

3. **Raw SQLAlchemy Queries & ORM Mutations Inside Services (Bypassing Repositories)**
   - **Evidence**:
     - `app/services/grading.py:675-679` (`self_evaluate_attempt`), `822-826` (`regrade_attempt`), `985-989` (`get_attempt_grading_detail`): three identical inline `select(AttemptItem).where(AttemptItem.id == ..., AttemptItem.user_id == ...)` queries executed via `self.session.execute(stmt)`, even though `PracticeRepository.get_attempt_item_by_id` already exists (`app/repositories/practice.py:257`)!
     - `app/services/practice.py:534-544` (`_assemble_and_persist_practice`): directly imports `sqlalchemy.select` (`L22`) and queries `WrongRecord.question_id` and `MasteryRecord.knowledge_point_id` via `self.session.execute(...)` instead of calling `DiagnosisRepository`.
     - `app/services/material.py:642-643` (`parse_material_pipeline`): directly calls `self.session.delete(previous_page); self.session.flush()` instead of delegating to `MaterialRepository`.
   - **Prescription**: Move all `select()`/`delete()` queries out of `GradingService`, `PracticeService`, and `MaterialService` into the corresponding repositories.

### P1 — Layer Leakage, God-Methods & Service Coupling

4. **ORM Attribute Monkey-Patching for DTO Serialization**
   - **Evidence**:
     - `app/services/material.py:1201-1205` (`get_material_detail`) and `1274-1289` (`list_materials`) mutate SQLAlchemy ORM `Material` instances with unmapped attributes (`material.parse_status = ...  # type: ignore[attr-defined]`, `progress_percentage`, `key_points_count`, `page_count`).
     - `app/api/v1/materials.py:327-330` and `742-746` read those monkey-patched attributes back via `getattr(item, "parse_status", None)`.
     - `app/services/practice.py:768` (`_attach_source_snippets_to_items`) does `setattr(item, "source_snippet", snippet_dto)  # noqa: B010` on ORM `AttemptItem` instances, duplicating `_attach_source_snippets` (`practice.py:713-740`) which operates on `PracticeDetailResponse` DTOs.
   - **Prescription**: Return explicit Service DTOs/aggregates (like `FolderService` already does with `FolderAggregate` in `app/services/folder.py:36-51`) instead of mutating ORM objects with transient attributes.

5. **Router Layer Violating Thin-Controller Boundary & Cross-Layer Imports**
   - **Evidence**:
     - `app/api/v1/practices.py:26`: imports `app.integrations.idempotency.protocol.validate_idempotency_key` directly (violating `directory-structure.md:20`: integrations should only be wired in `services`). Also `L402-414` duplicates `practice_service.submit_practice(...)` calls in an `if confirm_unanswered:` branch, and `L432-437` / `L478-481` contain dead `except X: raise` re-raises.
     - `app/api/v1/diagnosis.py:19`: imports ORM `WrongRecord`; `L310-367` (`list_wrong_records`) handles 3 legacy return formats (`WrongRecordListResponse`, `tuple[list, int]`, legacy list with `.total`), issues **two extra Service/DB round-trips** (`get_wrong_record_scopes` at `L344`, `list_wrong_record_groups` at `L354`), and mutates `item.material_id, item.folder_id` in the router (`L351`).
     - `app/api/v1/questions.py:93-95, 267, 396`: router manually triggers `question_service.attach_source_snippets(...)` across 3 endpoints instead of receiving complete DTOs from `QuestionService`.
     - `app/api/v1/materials.py:52, 707, 723-728`: `move_material_folder` orchestrates two separate services (`FolderService` + `MaterialService`) in the router instead of returning the moved material/detail from one service boundary.
     - `app/api/v1/folders.py:138-163`: groups `(KnowledgePoint, material_id, material_title)` tuples into `FolderKnowledgePointGroup` inside the route handler.
     - Pagination parameter normalization (`page`, `page_size`, `limit`, `offset`) is re-implemented inconsistently in 4 routers (`diagnosis.py:307-308`, `materials.py:290-292`, `questions.py:376-377`, `practices.py:140-141`).
   - **Prescription**: Introduce a shared `PaginationParams` FastAPI dependency, unify Service return types (remove `isinstance(..., *Response)` & `getattr(..., ...)` test-mock hacks in routers), and move enrichment (`attach_source_snippets`, wrong-record scopes/groups, folder KP grouping) into services.

6. **Service Cross-Coupling, Concrete Factory Imports & Inline Repository Instantiation**
   - **Evidence**:
     - `app/services/folder.py:27, 63, 313, 322`: `FolderService` depends on `MaterialService` AND reaches into its internal `self.material_service.repo` (`move_material`, Law-of-Demeter violation); at `folder.py:351` it instantiates `QuestionRepository(self.session)` inline inside `list_folder_knowledge_points` instead of constructor DI.
     - `app/services/practice.py:35-41, 184-185`: `PracticeService` imports concrete `create_idempotency_adapter` and `create_queue_adapter` factories instead of relying solely on `Protocol` injection from `AppContainer`.
     - `app/services/material.py:24, 357`: `MaterialService` depends on `KnowledgeService` (cross-service dependency); `MaterialService.parse_material_pipeline` (`material.py:565-777`) executes **7 separate `self.session.commit()` calls** (`L604, 659, 681, 692, 724, 746, 774`) mixed with `self.knowledge_service.extract_and_build_knowledge_tree(...)` (which itself commits internally at `knowledge.py:573, 584`), creating partial-commit states on failure.
   - **Prescription**: Inject `MaterialRepository` & `QuestionRepository` into `FolderService`; inject `IdempotencyProtocol`/`QueueProtocol` cleanly in `PracticeService` (or default to pure fake in tests without factory imports); make transaction boundaries explicit per pipeline stage.

7. **Extreme God-Method: `DiagnosisService.generate_diagnosis_report` (417L, CC=73)**
   - **Evidence**: `app/services/diagnosis.py:420-836` combines practice validation, idempotency check, item scoring aggregation, mastery baseline query + update, confidence degradation check, mistake evidence extraction, pure report synthesis, wrong-book synchronization, JSON payload serialization, and `IntegrityError` race handling in a single 417-line method.
   - **Prescription**: Split into `_load_validated_items()`, `_collect_evaluation_inputs()`, `_sync_wrong_records()`, and `_persist_report_idempotent()`.

### P2 — Structural Hygiene Issues

8. **Pure Parsers & Algorithm Helpers Embedded in Service Modules**
   - `app/services/material.py:86-314`: `validate_file_magic`, `_extract_text_from_pdf`, `_extract_paragraphs_from_docx`, `_extract_paragraphs_from_pptx` (228 lines of XML/ZIP/PDF byte parsing) live in `services/material.py` instead of a dedicated `core/extractors/` module; meanwhile `app/services/auth.py:38-52` duplicates magic-byte detection (`_detect_image_type`).
   - `app/services/knowledge.py:54-288`: pure tree-building/dedup algorithms (`compute_chapter_stats`, `deduplicate_candidate_points`, `normalize_extracted_temp_ids`, `_has_cycle`, `build_knowledge_hierarchy`) live in `services/knowledge.py` instead of `app/core/algorithms/`.
   - `app/services/question.py:157-604`: 5 LLM Pydantic schemas with complex normalizers (`_normalize_rubric` CC=27, `_normalize_item` CC=45) + prompt builders live in `services/question.py`.

9. **Unclosed `httpx.Client` Per-Call Allocation in OpenAI Adapters**
   - `app/integrations/llm/openai.py:81-85` and `app/integrations/embedding/openai.py:77-81`: `_get_client()` instantiates `httpx.Client(timeout=...)` on every `_send_request_with_retries()` call when `self._client is None`, without a `with` block or `close()` lifecycle (unlike `AppContainer.shutdown()`).

---

## 3. Dead Code, Duplication & Dependency Bloat

### P0 — Dependency Misclassification & Unused Packages (`backend/pyproject.toml`)

1. **`httpx` Declared Only in `[project.optional-dependencies].dev`, Imported in Production Code**
   - **Evidence**: `backend/pyproject.toml:36` puts `"httpx>=0.27.0"` under `dev`, NOT `[project].dependencies` (`L7-25`). Yet `httpx` is imported in 5 production modules: `app/services/auth.py:16`, `app/integrations/llm/openai.py:15`, `app/integrations/embedding/openai.py`, `app/integrations/ocr/baidu.py`, `app/integrations/ocr/tencent.py`. Installing the production wheel without `--extra dev` will crash with `ModuleNotFoundError: No module named 'httpx'`.
2. **Potentially Unused Dependencies in `pyproject.toml`**
   - `"cryptography>=43.0.0"` (`pyproject.toml:16`): **0** direct imports across all 255 `.py` files (`app/core/security.py:19` uses `HS256` symmetric HMAC via `pyjwt`, which does not require `cryptography`; verify if `psycopg`/runtime needs it or remove).
   - `"langchain-core>=1.6.4"` (`pyproject.toml:19`): imported **once** in `app/integrations/llm/agent_graph.py:15` (`from langchain_core.runnables import RunnableConfig`), where the `config: RunnableConfig | None = None` parameter is **never read** in any of the 4 node functions (`L58-245`). Also `langgraph` already pulls `langchain-core` transitively.
   - `"bandit>=1.7.0"` (`pyproject.toml:34`) and `"pip-audit>=2.7.0"` (`pyproject.toml:35`): **0** references in `Taskfile.yml` or `.github/workflows/verify.yml`.

### P1 — Zero-Caller Methods, Aliases & Unused Classes

All counts below were verified across `backend/app/**`, `backend/tests/**`, `backend/migrations/**`, and `Taskfile.yml`.

1. **Zero-App-Caller Service Methods & Legacy Shims**:
   - `app/services/auth.py:327` — `AuthService.revoke_user_tokens` (`app=0, test=0`, pure alias for `revoke_tokens`)
   - `app/services/auth.py:506` — `AuthService.delete_user_account` (`app=0, test=0`, pure alias for `delete_account`)
   - `app/services/auth.py:92, 105` — `user_repository` dual init param/attribute alias for `user_repo`
   - `app/services/knowledge.py:729` — `KnowledgeService.get_knowledge_point` (`app=0, test=0`)
   - `app/services/knowledge.py:757` — `KnowledgeService.get_snippets_by_point` (`app=0, test=0`)
   - `app/services/knowledge.py:781` — `KnowledgeService.get_points_by_snippet` (`app=0, test=0`)
   - `app/services/practice.py:952` — `PracticeService.timeout_practice` (`app=0, test=4` — feature never wired to any API route, CLI command, or worker job)
   - `app/services/diagnosis.py:92-131` — `MasteryRecordList` (`list` subclass overloading `__getitem__` with dict keys `"updated_records"`/`"records"`/`"items"` and `.as_dict()` at `L129` which has `app=0, test=1`)
   - `app/services/question.py:1400` — `get_question_detail = get_question` alias
   - `app/api/v1/materials.py:191` — `run_parse_material_background = run_material_pipeline_background` alias
   - `app/container.py:68, 247-281` — `self.registry = providers` and 9 `get_*_service` aliases delegating to `create_*_service`
   - `app/schemas/practice.py:413` — `AttemptItemDetailResponse = PracticeItemDetailResponse` alias

2. **Duplicate / Alias Repository Methods (0 App Callers, Kept Only by Unit Tests)**:
   - `app/repositories/knowledge.py`:
     - `L112`: `create_knowledge_points` (`app=0, test=2`) vs `batch_create_knowledge_points`
     - `L379`: `create_knowledge_point_snippets` (`app=0, test=2`, 1-line alias to `create_material_relations`)
     - `L416`: `get_snippets_by_knowledge_point` (`app=0, test=2`, 1-line alias to `get_snippets_for_point`)
     - `L453`: `get_knowledge_points_by_snippet` (`app=0, test=2`, 1-line alias to `get_points_for_snippet`)
     - Plus `create_knowledge_point` (`L39`, `app=0, test=14`), `list_by_user_id` (`L172`, `app=0, test=2`), `update_knowledge_point` (`L247`, `app=0, test=2`), `delete_by_id` (`L274`, `app=0, test=4`), `soft_delete_by_material_id` (`L297`, `app=0, test=4`)
   - `app/repositories/material.py`:
     - `L548`: `get_latest_version_by_hash` (`app=0, test=2`) vs `find_version_by_hash`
     - `L667`: `bulk_create_snippets` (`app=0, test=2`) vs `create_snippets`
     - `L725`: `list_snippets_by_version` (`app=0, test=2`, 1-line alias to `get_snippets`)
     - `L796`: `bulk_create_ocr_pages` (`app=0, test=2`) vs `create_ocr_pages`
     - `L854`: `list_ocr_pages_by_version` (`app=0, test=2`, 1-line alias to `get_ocr_pages`)
     - `L932`: `update_ocr_page_result` (`app=0, test=3`, 1-line alias to `update_ocr_page`)
   - `app/repositories/diagnosis.py:478`: `update_wrong_record_status` (`app=0, test=4`) vs `mark_wrong_record_mastered`
   - `app/repositories/grading.py`: `batch_create_records` (`L52`, `app=0, test=6`), `get_record_by_id` (`L76`, `app=0, test=3`)
   - `app/repositories/practice.py:370`: `count_answered_items` (`app=0, test=4`)
   - `app/repositories/question.py`: `create_question` (`L47`, `app=0, test=11`), `list_questions_by_material` (`L171`, `app=0, test=2`), `soft_delete_by_material` (`L660`, `app=0, test=3`), `list_quality_checks_by_batch` (`L720`, `app=0, test=2`)

3. **Unused Error Classes in `app/core/errors.py` (`app=0`)**:
   - `MaterialParseError` (`app/core/errors.py:717`, `app=0, test=2`)
   - `KnowledgePointQualityError` (`app/core/errors.py:785`, `app=0, test=3`)
   - `QuestionQualityCheckError` (`app/core/errors.py:889`, `app=0, test=3`)

### P2 — Cross-Module Logic Duplication

1. **Triplicated `_log_metric` Implementation**:
   - `app/services/grading.py:162-191`, `app/services/diagnosis.py:243-275`, `app/services/practice.py:187-216` copy-paste the same 8-element payload construction (`timestamp`, `level`, `logger_name`, `request_id`, `user_ref`, `target_id`, `duration_ms`, `error_code`, `action`) — with `GradingService` emitting `METRIC <json>` while `DiagnosisService` and `PracticeService` emit Python dict reprs.
2. **Duplicated Subjective LLM Grading Pipeline Inside `GradingService`**:
   - `app/services/grading.py:472-555` (`_grade_with_llm`) and `app/services/grading.py:849-918` (`regrade_attempt`) duplicate system/user prompt formatting, `LLMOptions(timeout=20.0, temperature=0.2)`, `generate_structured`, score clamping/half-up rounding, `set_records_non_final_by_attempt_id`, and `GradingRecord` instantiation.
3. **5 Hand-Rolled Exponential-Backoff Retry Loops in `app/integrations/`**:
   - `app/integrations/llm/openai.py:115-175`, `app/integrations/embedding/openai.py:106-158`, `app/integrations/ocr/baidu.py:191-295`, `app/integrations/ocr/tencent.py:171-212`, `app/integrations/queue/redis.py:106-155` each implement their own `for attempt in range(max_retries + 1)` + `time.sleep(base * (2 ** attempt))` loop.
4. **Duplicated Folder-Visibility & Wrong-Record Filter Logic in Repositories**:
   - `app/repositories/diagnosis.py:530-555` (`list_wrong_records`) and `587-612` (`count_wrong_records`) copy-paste the exact same 25-line `KnowledgePoint`/`Material` join & filter chain.
   - `app/repositories/material.py:197-240` (`_visible_folder_condition` / `_apply_folder_filter`) and `app/repositories/question.py:304-322` (`_apply_folder_filter`) separately maintain folder visibility rules.
5. **19 Bidirectional Alias `@model_validator` Shims Across `app/schemas/`**:
   - `app/schemas/diagnosis.py` (6 models, notably `UserMasteryOverviewResponse` syncing 6 overlapping field pairs twice in `_sync_fields` & `_sync_after` at `L313-385`) and `app/schemas/practice.py` (10 models, notably `PracticeItemDetailResponse` CC=32 & `PracticeDetailResponse` CC=29).

---

## 4. Test Suite & Spec Drift Findings

### 4.1 Test Suite Findings (`backend/tests/**`)

1. **Wall-Clock Timing Assertions (Confirmed Flaky Under Suite Contention)**:
   - `tests/unit/core/algorithms/test_diagnosis.py:628-633` (`duration_ms < 200.0`)
   - `tests/unit/core/algorithms/test_grading.py:972-981` (`duration_ms < 100.0`) and `L993-1002` (`duration_ms < 50.0`)
   - `tests/unit/core/algorithms/test_mastery.py:697-704` (`elapsed_seconds < 0.02`, i.e., 20ms)
   - `tests/unit/core/algorithms/test_material_chunking.py:273-277` (`elapsed_time <= 2.0`)
   - `tests/unit/core/algorithms/test_ocr_quality.py:329-336` (`elapsed_ms <= 100.0`)
   - **Also outside `algorithms/`**: `tests/unit/integrations/storage/test_storage.py:302-313` asserts `elapsed >= 0.045` on simulated latency and `elapsed2 < 0.04` on zero-latency put/get, which is equally vulnerable to Windows scheduler jitter.
2. **Test-Driven Dead-Code Lock-In & Fragmented Test Files**:
   - At least **23 repository methods** (`app=0`), **3 error classes** (`app=0`), and **`PracticeService.timeout_practice`** (`app=0, test=4`) remain in production code solely because unit tests exercise them directly (e.g., `test_material_repo.py`, `test_knowledge_repo.py`, `test_errors.py`, `test_practice_service.py`).
   - Service/router tests are fragmented across overlapping files (`test_diagnosis_service.py` 1,274L + `test_diagnosis_service_facade.py` 255L + `test_diagnosis_manual_wrong.py` 297L; `test_question_service.py` 1,829L + `test_question_multi_kp.py` 354L + `test_question_folder_generation.py` 457L; `test_practice_service.py` 1,423L + `test_practice_folder_scope.py` 290L; `test_practice_router.py` 1,029L + `test_grading_router.py` 586L + `test_practice_grading_flow.py` 782L).
   - `tests/unit/core/algorithms/test_material_chunking.py` leaves 3 internal helpers (`clean_text_and_count_removals`, `find_best_split_point`, `merge_isolated_short_snippets`) only indirectly covered via `split_material_into_snippets`.

### 4.2 Spec Drift vs `.trellis/spec/backend/*.md`

| Spec File & Claim | Actual Code Reality | Severity |
| --- | --- | --- |
| `directory-structure.md:13` claims Python 3.12 (`requires-python = ">=3.12"`) | `backend/.venv`, `AGENTS.md`, and `.github/workflows/verify.yml:47` standardize on **Python 3.13** | P2 |
| `directory-structure.md:20` claims `app.integrations` is wired only by `services` | `app/api/v1/practices.py:26` directly imports `app.integrations.idempotency.protocol.validate_idempotency_key`; `import-linter` has no `api -> integrations` forbidden contract | P1 |
| `directory-structure.md:79` forbids router logic/model coupling beyond HTTP parsing & service call | `app/api/v1/diagnosis.py:19,310-367` imports ORM `WrongRecord`, calls 3 service methods, mutates DTOs; `materials.py:723-728` coordinates 2 services; `folders.py:138-163` builds groupings | P1 |
| `directory-structure.md:80` claims Services only access DB via `app.repositories` | `GradingService` (`grading.py:675,822,985`), `PracticeService` (`practice.py:534,540`), and `MaterialService` (`material.py:642`) execute raw `select()` / `session.delete()` directly | P0 |
| `logging-guidelines.md:39-40` claims `DiagnosisService` uses `logger.info(msg, extra={...})` and `GradingService._log_metric` uses `METRIC <json>` | `DiagnosisService._log_metric` (`diagnosis.py:273`) & `PracticeService._log_metric` (`practice.py:214`) use `logger.info("... %s", log_payload)` (no `extra=`, no `METRIC <json>`); `materials.py:186` logs unbounded `str(exc)` instead of `[:200]` | P1 |
| `error-handling.md:31-32` lists `MaterialParseError`, `KnowledgePointQualityError`, `QuestionQualityCheckError` as active 40xxx errors and labels `50xxx` generic `AppError` default `40000/400` | Those 3 error classes have **0 callers** in `app/**` (`app/core/errors.py:717,785,889`) | P2 |
| `quality-guidelines.md:160-170` (`LangGraph Schema-as-Tool Calling Pipeline`) assumes structured calls go through `LLMProtocol.generate_structured` | `KnowledgeService._extract_batch_points` (`knowledge.py:374-388`) calls `run_structured_agent_workflow` and falls back to `generate_structured` (double execution); `QuestionService` (`question.py:876`) bypasses `generate_structured` | P0 |

### 4.3 Discovered `.trellis/spec/backend/` Paths (for `implement.jsonl` / `check.jsonl`)

- `d:/code/Workspace/zhilian/.trellis/spec/backend/index.md`
- `d:/code/Workspace/zhilian/.trellis/spec/backend/directory-structure.md`
- `d:/code/Workspace/zhilian/.trellis/spec/backend/database-guidelines.md`
- `d:/code/Workspace/zhilian/.trellis/spec/backend/error-handling.md`
- `d:/code/Workspace/zhilian/.trellis/spec/backend/logging-guidelines.md`
- `d:/code/Workspace/zhilian/.trellis/spec/backend/material-statistics.md`
- `d:/code/Workspace/zhilian/.trellis/spec/backend/quality-guidelines.md`
