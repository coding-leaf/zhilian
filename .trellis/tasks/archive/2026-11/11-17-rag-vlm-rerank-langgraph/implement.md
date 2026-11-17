# Implementation Plan

## Execution Mode
**Native Swarm** using `model: "claude-sonnet-5-5-high"` (per user confirmation; 100% quota) with disjoint `workspace: "share"` workers:
- **Worker 1 (`backend-rag`)**: owns `backend/**` — P0+P1+P2 ingestion/search/rerank/VLM + Adaptive/Corrective LangGraph + tests + backend quality gates.
- **Worker 2 (`frontend-latex`)**: owns `miniprogram/**` — `richText.ts` LaTeX environments & Markdown tables, `thread_id` chat wiring, tests + frontend quality gates.
- **`monitor`**: swarm stall monitor.

---

## Workstreams

### Workstream A — Backend (`backend/**`)
1. **Dependencies & Config (`pyproject.toml`, `core/config.py`, `.env.example`, `integrations/container.py`, `container.py`)**
   - Add `pymupdf>=1.25.0` to `pyproject.toml`, update lock/venv (`uv sync` / `uv add` or `uv lock`).
   - Add `VLMSettings`, `RerankSettings`, extend `EmbeddingSettings.provider` with `"siliconflow"`.
   - Wire `rerank` & `vlm` into `ProviderRegistry` (preserving backward-compatible `validate()` for existing 7-protocol tests) and `AppContainer`.
2. **P0+P2 Ingestion & Chunking (`core/extractors.py`, `core/algorithms/ocr_quality.py`, `core/algorithms/material_chunking.py`, `integrations/llm/{protocol,openai,fake}.py`, `services/_material_pipeline.py`, `services/material.py`)**
   - `PyMuPDF` coordinate-aware extraction + `render_pdf_page_png` + `pypdf` fallback.
   - Enhanced math/Greek/Cyrillic & fragmented-page garble detection.
   - Multimodal `LLMMessage.image_urls` + `OpenAICompatibleLLMAdapter` vision serialization.
   - Dirty-page VLM concurrent transcription with verbatim LaTeX prompt & per-page fallback.
   - Iterative short-snippet merging (`>= 120` chars, page/chapter boundaries, target grouping), `.` sentence splitting (decimal-safe), `$$...$$`/table protection, Contextual `[章节·页码]` embedding prefix.
3. **P0+P1 Search, Rerank & Excerpts (`core/algorithms/search.py`, `integrations/search/`, `integrations/rerank/`, `services/source_snippets.py`, `services/question.py`)**
   - Update `tokenize_text` (preserve Greek/LaTeX/Chinese bigrams) & BM25 length floor.
   - Push `allowed_snippet_ids` into `SearchOptions` + `PgvectorHybridSearchAdapter` SQL + `FakeSearchAdapter`, add full-corpus keyword recall branch + `snippet_index ± 1` neighbor expansion.
   - Implement `app/integrations/rerank/` (`RerankProtocol`, `FakeRerankAdapter`, `SiliconFlowRerankAdapter`, `factory.py`).
   - Clean sentence/formula-boundary excerpt trimming in `ask_scoped_coach` & `aggregate_snippet_context`.
4. **Adaptive + Corrective LangGraph & Memory (`integrations/llm/coach_graph.py`, `schemas/question.py`, `services/question.py`)**
   - Implement 6-node Adaptive + Corrective graph (`route_intent` -> `retrieve_and_rerank` -> `check_evidence` / `rewrite_query` -> `generate_grounded` -> deterministic `verify_citations`).
   - Add `thread_id` to `ScopedCoachRequest` + Redis/Memory sliding-window conversation store + `MemorySaver`.
5. **Backend Tests & Quality Gates**
   - Comprehensive offline unit tests for all P0–P2 modules, rerank, VLM multimodal serialization, adaptive/corrective graph branches, memory, and `import-linter` / `mypy` / `ruff` / `pytest`.

### Workstream B — Frontend (`miniprogram/**`)
1. **`miniprogram/src/utils/richText.ts`**
   - Add GFM pipe table parsing & HTML `<table>` inline-styled rendering.
   - Add `\begin{pmatrix|bmatrix|vmatrix|cases|aligned}` environment rendering + extra LaTeX symbols/operators (`\hat`, `\bar`, `\vec`, `\det`, `\lim`, `\log`, `\sin`, `\cos`, `\binom`, `\mathbb`, `\sqrt[n]{x}`).
2. **Thread ID Continuity (`types/question.ts`, `api/modules/questions.ts`, `composables/useCoachChat.ts`)**
   - Add optional `thread_id?: string` on `ScopedCoachParams` and send `thread_id: targetKey` in `useCoachChat.ts`.
3. **Frontend Tests & Gates**
   - Expand `tests/richText.spec.ts` and `tests/useCoachChat.spec.ts`.
   - Run `pnpm run lint`, `pnpm run type-check`, `pnpm run test:unit`, `pnpm run build:mp-weixin`.
