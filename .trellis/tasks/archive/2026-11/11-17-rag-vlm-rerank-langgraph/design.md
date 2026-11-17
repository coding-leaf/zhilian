# Technical Design: RAG P0–P2 & Adaptive Corrective LangGraph

## 1. Architecture & Layer Compliance (`import-linter` 6 Contracts)

```
app.api (sync def routes)
  └─ app.services (MaterialService, KnowledgeService, QuestionService)
       ├─ app.core (config, extractors [pymupdf+pypdf], algorithms [chunking, ocr_quality, search])
       ├─ app.repositories (MaterialRepository, KnowledgeRepository)
       └─ app.integrations
            ├─ llm (LLMMessage multimodal, OpenAICompatibleLLMAdapter, FakeLLMAdapter, coach_graph)
            ├─ embedding (OpenAICompatibleEmbeddingAdapter + siliconflow provider)
            ├─ search (PgvectorHybridSearchAdapter [allowed_snippet_ids + full-corpus keyword + neighbor], FakeSearchAdapter)
            └─ rerank [NEW] (RerankProtocol, SiliconFlowRerankAdapter, FakeRerankAdapter, factory)
```

---

## 2. Backend Design

### 2.1 Configuration (`backend/app/core/config.py`, `.env.example`, `container.py`)
- **`VLMSettings`**:
  - `enabled: bool = False`
  - `provider: Literal["fake", "openai", "siliconflow"] = "fake"`
  - `model: str = "Qwen/Qwen2.5-VL-7B-Instruct"`
  - `base_url: str | None = None` (default `"https://api.siliconflow.cn/v1"` when `provider == "siliconflow"`)
  - `api_key: SecretStr | None = None`
  - `timeout: float = 45.0`
  - `max_retries: int = 2`
  - `dpi: int = 150`
  - `max_concurrency: int = 3`
- **`RerankSettings`**:
  - `enabled: bool = False`
  - `provider: Literal["fake", "siliconflow", "openai"] = "fake"`
  - `model: str = "BAAI/bge-reranker-v2-m3"`
  - `base_url: str | None = None` (default `"https://api.siliconflow.cn/v1"` when `provider == "siliconflow"`)
  - `api_key: SecretStr | None = None`
  - `timeout: float = 15.0`
  - `max_retries: int = 2`
  - `top_n: int = 6`
  - `min_score: float = 0.25`
  - `rewrite_threshold: float = 0.45`
- **`EmbeddingSettings`**: add `"siliconflow"` to `provider: Literal["fake", "openai", "dashscope", "siliconflow"]` and default `base_url` in `integrations/embedding/factory.py`.
- **`ProviderRegistry`**:
  - Keep `validate()` enforcing the 7 mandatory protocols; add optional `rerank: RerankProtocol | None = None` and `vlm: LLMProtocol | None = None` (auto-defaulted to `FakeRerankAdapter()` / `None` in `ProviderRegistry.__post_init__` so existing `strict=True` tests never break).
  - `AppContainer.create_default()` builds `rerank` via `create_rerank_adapter(settings.rerank)` and `vlm` via `create_vlm_adapter(settings.vlm)` (when `vlm.enabled` is True and `vlm.provider != "fake"`), injecting them into `MaterialService` and `QuestionService`.

### 2.2 P0+P2 Ingestion: PyMuPDF + Dirty-Page VLM + Chunking + Contextual Embedding
1. **`app/core/extractors.py` (`pymupdf` + `pypdf` fallback)**:
   - Add `pymupdf>=1.25.0` to `backend/pyproject.toml`.
   - `extract_pdf_pages_with_diagnostics`: prefer `fitz.open(stream=content, filetype="pdf")` block/line extraction (`get_text("blocks")` sorted in reading order, preserving paragraph breaks `\n\n`), falling back to `pypdf` if `fitz` fails to open.
   - Add `render_pdf_page_png(pdf_bytes: bytes, page_number: int, dpi: int = 150) -> bytes` via `page.get_pixmap(dpi=dpi).tobytes("png")`.
2. **`app/core/algorithms/ocr_quality.py`**:
   - Enhance `detect_symbol_garble(text)` + add `detect_broken_math_layout(text)`:
     - Catch garbled Greek/Cyrillic clusters (e.g. Cyrillic `ђ` mixed with Latin/Greek, or repeated math-font corruption like `σpiupi` / `\b[α-ωΑ-Ω][a-z]{3,}\b` clusters) AND dense ultra-short formula-fragment pages (>= 6 non-empty lines where > 45% of lines are `<= 8` chars containing math symbols/digits/Greek letters).
3. **Multimodal `LLMMessage` & Dirty-Page VLM Routing (`integrations/llm/`, `services/_material_pipeline.py`)**:
   - Extend `LLMMessage` with `image_urls: tuple[str, ...] = ()` (data URI or HTTPS URL). In `OpenAICompatibleLLMAdapter.generate`, when `m.image_urls` is non-empty, serialize `"content": [{"type": "text", "text": m.content}, *[{"type": "image_url", "image_url": {"url": u}} for u in m.image_urls]]`; otherwise keep plain string `"content": m.content`.
   - In `_material_pipeline.py::repair_garbled_pdf_pages`:
     - Clean pages (`not page.needs_repair`) skip VLM completely (zero API cost).
     - Dirty pages: if `vlm` is configured (`vlm_adapter` or `ocr_hint`), render 150 DPI PNG -> base64 data URI -> call `vlm.generate(...)` concurrently via `ThreadPoolExecutor(max_workers=max_concurrency)` with strict verbatim Markdown+LaTeX transcription prompt (`$...$` / `$$...$$`, no summarizing/inventing). On single-page failure, fall back to text repair / sanitized `PyMuPDF` text.
     - Paragraph splitting: split repaired Markdown into structural blocks while **preserving** `$$...$$` display math blocks and Markdown tables as intact blocks instead of splitting on every single `\n`.
4. **`app/core/algorithms/material_chunking.py`**:
   - Add `.` to `PRIMARY_PUNCTUATION_CHARS` (with decimal/version guard `(?<!\d)\.(?!\d)` in split-point/overlap alignment).
   - Add block protection for `$$...$$`, `$...$`, and Markdown pipe tables so `find_best_split_point` and `align_overlap_sentence_boundary` never cut inside a formula or table, nor start overlap right after `,`/`;`.
   - Fix `merge_isolated_short_snippets(..., min_chars=120, target_chars=500, max_chars=800)`:
     - Loop while accumulated short snippet `< min_chars` (do NOT stop after 1 pairwise merge!).
     - Also group consecutive same-page, same-chapter paragraphs/bullets up to `target_chars` (`<= max_chars`) when individual lines are short/medium, **strictly respecting `page_number` and `chapter_title` boundaries** (never merge across pages or chapters).
5. **Contextual Retrieval Prefix (`_material_pipeline.py`, `knowledge.py`)**:
   - Add `build_contextual_snippet_text(snippet)` returning `f"[{chapter} · {source_ref}]\n{content}"` (when metadata exists) exclusively for `embedding.embed_documents(...)`; keep `MaterialSnippet.content` pure for UI display.

### 2.3 P0+P1 Retrieval, Rerank & Clean Excerpts
1. **`app/core/algorithms/search.py`**:
   - Update `tokenize_text()`: match `[\u4e00-\u9fa5]+|[a-z0-9_]+|[α-ωΑ-ΩσΣλπΔθμ]|\\[a-zA-Z]+`, emitting Chinese unigrams + bigrams (without dropping single-char precision) and preserving Greek/LaTeX command tokens.
   - Smooth BM25 length norm (`b = 0.45` or clamp `actual_doc_length` floor to `min_doc_len = 25`) so 2-token fragments don't artificially outscore rich paragraphs.
2. **`app/integrations/search/` (`protocol.py`, `pgvector.py`, `fake.py`)**:
   - Add `allowed_snippet_ids: tuple[uuid.UUID, ...] | None = None` to `SearchOptions` and `snippet_index: int | None = None` to `SearchSnippetCandidate`.
   - In `PgvectorHybridSearchAdapter`:
     - Push `MaterialSnippet.id.in_(options.allowed_snippet_ids)` directly into SQL queries (early return empty if `allowed_snippet_ids == ()`).
     - Add independent full-corpus keyword candidate query (`ILIKE` over top extracted query tokens within the authorized scope, limit `vector_top_k`), union with HNSW vector candidates before computing BM25 + RRF fusion.
   - Add `fetch_neighbor_snippets(candidates, *, user_id, window=1)` helper (or repository-backed lookup in `QuestionService` / `PgvectorHybridSearchAdapter`) to expand `snippet_index ± 1` within the same `version_id` and same `page_number` (from `source_info`), merging adjacent text cleanly without duplicating overlap.
3. **`app/integrations/rerank/` (`protocol.py`, `fake.py`, `siliconflow.py`, `factory.py`)**:
   - `RerankProtocol.rerank(query: str, documents: Sequence[str], *, top_n: int | None = None) -> list[RerankItem]` (`index`, `relevance_score`).
   - `SiliconFlowRerankAdapter`: sync `httpx.Client` calling `POST {base_url}/rerank` with `{"model": ..., "query": ..., "documents": [...], "top_n": ...}` and shared retry helper; graceful fallback to original order if disabled/error (with warning log).
   - `FakeRerankAdapter`: deterministic lexical + overlap scorer for zero-network unit tests.
4. **Clean Excerpt Trimming (`source_snippets.py` / `question.py`)**:
   - Replace `item.content[:320]` in `ask_scoped_coach` with `trim_excerpt_cleanly(item.content, max_chars=480)` respecting sentence boundaries (`。！？.!?`) and unclosed `$...$`/`$$...$$` blocks.

### 2.4 Adaptive + Corrective LangGraph & Multi-Turn Memory (`coach_graph.py`, `schemas/question.py`, `services/question.py`)
- **Schema & API (`schemas/question.py`, `api/v1/questions.py`, `services/question.py`)**:
  - `ScopedCoachRequest`: add optional `thread_id: str | None = Field(default=None, max_length=128)` (backward compatible).
  - `QuestionService.ask_scoped_coach`: pass `thread_id` (defaulting to deterministic `f"{user_id}:{scope_key}"` if provided/derived) + optional `kp_overview_context` (from `KnowledgePoint.structured_content` / chapter KPs when `folder_id`/`material_id`/`knowledge_point_id` is scoped) + `reranker` + `memory_store` into `answer_with_course_evidence(...)`.
- **LangGraph `StateGraph(CoachGraphState)` (`coach_graph.py`)**:
  1. `route_intent`: deterministic Chinese/English intent classifier (`chitchat` vs `overview` vs `detail_qa`):
     - `chitchat` (e.g. `"你好呀"`, `"谢谢"`, `"你是谁"`) -> `conversational_reply` (warm, concise greeting & 2–3 study suggestions, **0 search calls**).
     - `overview` (e.g. `"梳理框架"`, `"核心考点有哪些"`, `"总结这章重点"`) + `structured_overview` available -> `generate_overview` (uses structured KPs + top snippets directly).
     - `detail_qa` -> `retrieve_and_rerank`.
  2. `retrieve_and_rerank`: pushes `allowed_snippet_ids` into `SearchOptions`, runs hybrid search (`vector_top_k=30, top_k=16`), expands neighbors (`snippet_index ± 1`), runs `reranker.rerank(query, docs, top_n=6)` (when `reranker` enabled) and computes `top_relevance_score`.
  3. Conditional `check_evidence`:
     - If `candidates` empty or `top_relevance_score < rewrite_threshold` AND `rewrite_count == 0` -> `rewrite_query` (uses recent conversation turns + scope title/KP name to rewrite colloquial query into precise search terms, increments `rewrite_count=1`, loops back to `retrieve_and_rerank`).
     - If still empty / `< min_score` after rewrite -> `honest_fallback` (states gap honestly + suggests 2–3 answerable topics from scope).
     - Otherwise -> `generate_grounded`.
  4. `generate_grounded`: receives recent conversation history (up to 6 turns) + expanded evidence -> calls `llm.generate_structured` -> passes to **deterministic Python `verify_citations`** (filters hallucinated IDs and backfills top candidate IDs if empty, **eliminating the extra LLM retry round-trip**).
  5. **Memory (`CoachSessionMemory` + LangGraph `MemorySaver`)**:
     - Compile graph with `MemorySaver()` checkpointer and also persist recent `(user, assistant)` turns (last 6 turns, 24h TTL) in Redis when available (via existing Redis client resolution pattern) with in-memory LRU fallback, so multi-turn follow-ups ("那不满足这个条件会怎样？") work seamlessly across reloads without Alembic migration.

---

## 3. Frontend Design (`miniprogram/`)

1. **`miniprogram/src/utils/richText.ts`**:
   - **GFM Pipe Tables**: detect contiguous `| ... |` header + `| --- | --- |` separator + data rows in `parseRichContent`; render styled HTML `<table><thead><tr><th>...</th></tr></thead><tbody><tr><td>...</td></tr></tbody></table>` with inline CSS compatible with WeChat `<rich-text>` (wrapping in scrollable `overflow-x: auto` container).
   - **LaTeX Environments & Commands**:
     - Parse `\begin{pmatrix|bmatrix|vmatrix|cases|aligned} ... \end{pmatrix|...}` in math blocks/inline math, formatting rows (`\\`) and columns (`&`) cleanly into readable multi-line / bracketed mathematical layout inside `<rich-text>` instead of leaking `beginpmatrix`.
     - Expand `LATEX_SYMBOL_MAP` / command handlers for `\hat`, `\bar`, `\vec`, `\tilde`, `\det`, `\lim`, `\log`, `\ln`, `\exp`, `\sin`, `\cos`, `\tan`, `\max`, `\min`, `\arg`, `\binom`, `\mathbb`, `\sqrt[n]{x}`.
2. **`miniprogram/src/types/question.ts`, `src/api/modules/questions.ts`, `src/composables/useCoachChat.ts`**:
   - Add optional `thread_id?: string` to `ScopedCoachParams` and pass `thread_id: targetKey` from `useCoachChat.ts::sendMessage`.
   - Keep `buildCoachSessionKey` & single-scope precedence intact.
