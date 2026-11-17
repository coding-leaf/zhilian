# Research: Integration & Schema Boundaries (`11-17-rag-vlm-rerank-langgraph`)

- **Query**: Inspect integration, configuration, dependency, `import-linter`, multimodal LLM, pgvector/snippet schema, `/coach/ask` contract, and `richText.ts` LaTeX/Markdown boundaries for RAG P0–P2 + SiliconFlow VLM/Rerank + Adaptive/Corrective LangGraph.
- **Scope**: `backend/` (`app/core/config.py`, `.env.example`, `app/container.py`, `app/integrations/**`, `app/models/material.py`, `app/repositories/**`, `app/services/question.py`, `app/services/material.py`, `app/api/v1/questions.py`, `app/schemas/question.py`, `pyproject.toml`) and `miniprogram/` (`src/composables/useCoachChat.ts`, `src/api/modules/questions.ts`, `src/types/**`, `src/utils/richText.ts`).
- **Date**: 2026-11-17

---

## 1. Configuration, Container Wiring, Dependencies & `import-linter`

### 1.1 `AppSettings` & Sub-Settings (`backend/app/core/config.py`, `backend/.env.example`)
- `AppSettings` (`config.py:376-443`) uses `pydantic_settings.BaseSettings` with:
  - `env_prefix="ZHILIAN_"`, `env_nested_delimiter="__"`, `env_file=".env"`, `extra="ignore"`.
  - Top-level fields: `env` (`development | test | production`, default `development`), `debug` (`bool`, default `False`), `secret_key` (`SecretStr`, default `DEVELOPMENT_SECRET_KEY`), `wechat_app_id`, `wechat_app_secret`.
  - Startup fail-fast: `validate_secret_key()` (`config.py:457-482`) raises `RuntimeError` if `env == "production"` and `uses_insecure_default_secret_key` is `True`.
- Relevant sub-settings:
  - `LLMSettings` (`config.py:261-296`): `provider: Literal["fake", "openai", "dashscope", "deepseek", "siliconflow"]` (default `"fake"`), `model` (default `"qwen-max"`), `base_url: str | None`, `api_key: SecretStr | None`, `timeout: float = 30.0`, `max_retries: int = 3`.
    - Note: `create_llm_adapter` (`integrations/llm/factory.py:61-62`) already maps `provider="siliconflow"` to default `base_url="https://api.siliconflow.cn/v1"`.
  - `OCRSettings` (`config.py:299-373`): `provider: Literal["fake", "tencent", "baidu"]` (default `"fake"`), `api_key`, `secret_id`, `secret_key`, `region` (`"ap-guangzhou"`), `endpoint` (`"ocr.tencentcloudapi.com"`), `timeout: float = 20.0`, `max_retries: int = 3`.
    - Validators: `_normalize_endpoint` auto-prepends `https://` unless `"ocr.tencentcloudapi.com"`; `_sync_credentials` mirrors `api_key` <-> `secret_id`; `effective_api_key` property returns `api_key or secret_id`.
    - No `model` field exists on `OCRSettings` yet (needed if adding a VLM-based OCR provider like SiliconFlow VLM).
  - `EmbeddingSettings` (`config.py:204-258`): `provider: Literal["fake", "openai", "dashscope"]` (default `"fake"`), `model` (`"text-embedding-v3"`), `dimension` (`1024`, aliased via `dimensions` property), `batch_size` (`16`), `api_key`, `base_url`, `timeout` (`20.0`), `max_retries` (`3`).
    - Note: `siliconflow` is NOT yet in `EmbeddingSettings.provider` `Literal` (though `openai` + `base_url=https://api.siliconflow.cn/v1` works in `OpenAICompatibleEmbeddingAdapter`, which intentionally omits `dimensions` from payload for fixed-dim models like `bge-large-zh-v1.5`, see `integrations/embedding/openai.py:156-161`).
  - `SearchSettings` (`config.py:135-155`): `provider: Literal["fake", "pgvector"]` (default `"fake"`), `vector_dimension: int = 1024`, `distance_strategy: Literal["cosine", "l2", "inner_product"] = "cosine"`.
    - Note: `vector_dimension` and `distance_strategy` are currently NOT forwarded in `ProviderRegistry.create_default` (`integrations/container.py:344-348`).
  - No `RerankSettings` or `CheckpointerSettings` / `VLMSettings` exists yet.
- `backend/.env.example` (`lines 1-51`): keeps all providers at `memory` / `fake` for zero-dependency test/dev startup (`ZHILIAN_DB__DB_URL` points to `postgresql+asyncpg://...` locally, while unit tests use SQLite/in-memory).

### 1.2 `AppContainer` & `ProviderRegistry` (`backend/app/container.py`, `backend/app/integrations/container.py`)
- `AppContainer` (`container.py:46-310`):
  - Holds `settings`, synchronous SQLAlchemy `engine`, `session_factory`, and `providers: ProviderRegistry`.
  - Service factory methods (`create_*_service(session)`):
    - `create_material_service` (`container.py:181-201`) injects `storage`, `ocr`, `embedding`, `queue`, `idempotency`, `knowledge_service`, `llm`, `bucket`.
    - `create_question_service` (`container.py:220-229`) injects `llm`, `embedding`, `search_adapter`, `queue`, `session_factory`.
  - Lifecycle: `startup()` checks `SELECT 1` and `storage.ensure_bucket_exists`; `shutdown()` awaits `providers.shutdown()` and `engine.dispose()`.
  - `check_health()` (`container.py:267-308`) reports `providers` dict (`llm`, `ocr`, `embedding`, `search`, `queue`).
- `ProviderRegistry` (`integrations/container.py:29-422`):
  - Hardcoded to **7 protocols**: `llm`, `ocr`, `storage`, `search`, `queue`, `idempotency`, `embedding`.
  - `validate()` (`integrations/container.py:235-248`) raises `ValueError` if any of those 7 is `None`; `create_default()` passes `strict=True`.
  - **Caveat**: Adding an 8th mandatory protocol (e.g., `rerank`) to `validate()` will break `ProviderRegistry(llm=..., ..., strict=True)` callers unless defaulted or kept optional (`FakeRerankAdapter` / optional property). Check `tests/unit/integrations/test_container.py`.
  - Also note `app/worker.py:81-90` creates an `AppContainer.create()` per job and calls `asyncio.run(container.shutdown())` in `finally`.

### 1.3 Dependencies (`backend/pyproject.toml` & `.venv`)
- Declared in `backend/pyproject.toml:7-25`: `fastapi>=0.115.0`, `pydantic>=2.8.0`, `pydantic-settings>=2.4.0`, `sqlalchemy[asyncio]>=2.0.30`, `psycopg[binary]>=3.1.0`, `alembic>=1.13.0`, `pgvector>=0.3.0`, `langgraph>=1.2.12`, `httpx>=0.27.0`, `pypdf>=4.0.0`, `redis>=5.0.0`, `rq>=2.0,<3.0`, `boto3>=1.34.0`.
- Installed in `backend/.venv` (verified via `uv run`):
  - `langgraph==1.2.12`, `langgraph-checkpoint==4.2.0`, `pgvector==0.5.0`, `psycopg==3.3.6`, `pypdf==6.19.0`.
  - **NOT installed / NOT declared**: `pymupdf` (`fitz`) and `langgraph-checkpoint-postgres` are **absent** from both `pyproject.toml` and `backend/.venv`. Adding either requires updating `pyproject.toml` + `uv.lock` (and Docker image for `deploy-worker-1` if used in parsing/worker).

### 1.4 `import-linter` & Static Constraints (`backend/pyproject.toml:46-144`)
- 6 active `import-linter` contracts (`pyproject.toml:71-138`):
  1. `layers`: `app.api` -> `app.services` -> `app.repositories`.
  2. `forbidden`: `app.repositories` MUST NOT import `fastapi`, `app.integrations`, `app.services`, `app.api`.
  3. `forbidden`: `app.core.algorithms` MUST NOT import `fastapi`, `sqlalchemy`, `httpx`, `redis`, `boto3`, `app.api`, `app.services`, `app.repositories`.
  4. `forbidden`: `app.integrations` MUST NOT import `app.services`, `app.api`.
  5. `forbidden`: `app.core` MUST NOT import `app.api`, `app.services`, `app.repositories`, `app.integrations`.
  6. `forbidden`: `app.api` MUST NOT directly import `app.integrations` (`allow_indirect_imports = true`).
- Other gates: `ruff` (`max-complexity = 15` via `C901`, `S` bandit rules, `ASYNC`), `mypy` (`strict = true`), `pytest` (`--cov=app --cov-branch --cov-fail-under=80`).
- **Implication for new adapters**:
  - A new `app.integrations.rerank` package (with `protocol.py`, `fake.py`, `siliconflow.py`, `factory.py`) or extending `app.integrations.search` / `ocr` / `llm` complies cleanly with `import-linter` as long as it only imports `app.core` (`errors`, `config`, `algorithms`), `app.models`, and third-party HTTP/DB libs (`httpx`, `sqlalchemy`, `langgraph`).
  - `app.integrations.llm.coach_graph` lives in `app.integrations.llm`, so it CAN import `app.integrations.search.protocol` and `app.integrations.rerank.protocol` (and `langgraph`), and CANNOT import `app.services` or `app.repositories` (if kept strictly decoupled) — wait: `app.integrations` is NOT forbidden from importing `app.repositories`, though `directory-structure.md` reserves `app.repositories` for DB access invoked by `app.services` (while `PgvectorHybridSearchAdapter` already queries `MaterialSnippet` directly via `session_factory`).

---

## 2. Multimodal / VLM Support in `LLMMessage` & `OpenAICompatibleLLMAdapter`

- **Current status: NOT supported.**
  - `LLMMessage` (`integrations/llm/protocol.py:18-31`) defines `role: str` and `content: str`, and `__post_init__` explicitly runs `if not self.content.strip(): raise ValueError(...)`. Passing a `list[dict[str, Any]]` (OpenAI vision content parts) will fail both mypy (`strict=true`) and runtime `.strip()`.
  - `OpenAICompatibleLLMAdapter.generate` (`integrations/llm/openai.py:175-178`) builds:
    `"messages": [{"role": m.role, "content": m.content} for m in messages]`
    with no image/content-part serialization.
  - `FakeLLMAdapter` (`integrations/llm/fake.py:109, 114, 158`) also assumes `msg.content` is `str` (`fault_key in msg.content`, `last_content.encode("utf-8")`).
  - `agent_graph.py` (`integrations/llm/agent_graph.py:208-216`) constructs `LLMMessage` with `str` content during structured repair.
- **Note on current PDF/OCR repair flow**:
  - `app/core/extractors.py:153-193` uses `pypdf` to extract page text and embedded images (`_extract_page_embedded_images`), flagging pages with missing `/ToUnicode` symbol fonts or ASCII garble (`needs_repair`).
  - `app/services/_material_pipeline.py:297-404` (`_repair_pdf_page_text`) passes extracted text + optional `OCRProtocol` hint (from embedded images or `getattr(ocr, "recognize_pdf_page", None)`) to text-only `LLMProtocol.generate(...)`. It cannot render full PDF pages to images (no `pymupdf` yet) and cannot pass images to `LLMProtocol` yet.
- **Extension options**:
  - Add multimodal support to `LLMMessage` (e.g., optional `image_urls: tuple[str, ...] = ()` or `content: str | Sequence[dict[str, Any]]` with type-safe serialization in `OpenAICompatibleLLMAdapter` and text extraction in `FakeLLMAdapter`) OR introduce a dedicated VLM / `OCRProtocol` adapter (e.g. `SiliconFlowVLMOCRAdapter` or `VLMProtocol`). Note that `OCRProtocol` (`integrations/ocr/protocol.py:82-128`) already accepts `recognize_image(image_bytes: bytes, options)` and `recognize_url(image_url: str, options)`, and `BaiduOCRAdapter` exposes an extra duck-typed `recognize_pdf_page(pdf_bytes, page_number)`.

---

## 3. `MaterialSnippet` Schema, Indexes & Query Boundaries

### 3.1 `MaterialSnippet` Model (`backend/app/models/material.py:372-478`)
- Table: `material_snippets`
- Columns:
  - `id: UUID` (PK)
  - `user_id: UUID` (from `TenantModelMixin`, `FK users.id ON DELETE CASCADE`, NOT NULL, indexed)
  - `material_id: UUID` (`FK materials.id ON DELETE CASCADE`, NOT NULL, indexed)
  - `version_id: UUID` (`FK material_versions.id ON DELETE CASCADE`, NOT NULL, indexed)
  - `snippet_index: int` (NOT NULL, 0-based sequential index within a version)
  - `content: str` (`Text`, NOT NULL, docstring comment: `<=800` chars)
  - `char_length: int`, `start_offset: int`, `end_offset: int`
  - `chapter_title: str` (`String(255)`, default `""`)
  - `source_info: dict[str, Any]` (`JSON().with_variant(JSONB, "postgresql")`, default `dict`)
  - `embedding: Any` (`get_vector_type(1024)` -> `pgvector.sqlalchemy.Vector(1024)` on PostgreSQL, `JSON` on SQLite; `nullable=True`)
  - `created_at`, `updated_at` (`TimestampMixin`)
- **Critical schema observation**:
  - `MaterialSnippet` has **NO `page_number` or `page_index` column**. Page numbers are stored inside `source_info` JSONB (`{"source_ref": "第 N 页", "page_number": N}`, see `_material_pipeline.py:425-427`) and resolved via `source_snippets.py:17-34` (`resolve_snippet_page_index`). (Only `MaterialOCRPage` has a dedicated `page_number` column.)
  - Any query or migration adding a `page_number` column or PostgreSQL `tsvector`/GIN index must update `models/material.py` + add a symmetric `migrations/versions/0012_*.py` (current head is `0011_structured_kp_and_question_jobs.py`), because `tests/unit/models/test_migration_model_consistency.py` enforces `Base.metadata == Alembic head`.
- Indexes & Constraints on `material_snippets`:
  - `uq_material_snippets_version_index`: `UniqueConstraint("version_id", "snippet_index")`
  - `ix_material_snippets_user_mat_ver`: `Index("user_id", "material_id", "version_id")`
  - `ix_material_snippets_embedding_hnsw`: `Index("embedding", postgresql_using="hnsw", postgresql_with={"m": 16, "ef_construction": 200}, postgresql_ops={"embedding": "vector_cosine_ops"})`
  - Single-column indexes on `user_id`, `material_id`, `version_id`.

### 3.2 `PgvectorHybridSearchAdapter` & `KnowledgeRepository` / `MaterialRepository`
- `PgvectorHybridSearchAdapter.search` (`integrations/search/pgvector.py:57-231`):
  - Queries `MaterialSnippet` directly via `self._session_factory()`.
  - Filters: `user_id == user_id`, optional `material_id`, optional `version_id`.
  - **Does NOT accept `allowed_snippet_ids`** (nor `material_ids` list / `version_map`).
  - As a result, `coach_graph.py:48-63` loops over `material_ids` issuing one `search.search(..., options=SearchOptions(top_k=8, vector_top_k=20))` call per material and filters `allowed_snippet_ids` **in Python after Top-20 vector retrieval** — meaning if a knowledge point's snippets rank outside the global Top-20 for that material, zero candidates survive!
  - `SearchSnippetCandidate` (`integrations/search/protocol.py:16-30`) lacks `snippet_index` (has `snippet_id`, `material_id`, `version_id`, `content`, `chapter_title`, `source_info`, `vector_score`, `bm25_score`, `final_score`, `vector_rank`, `bm25_rank`).
  - `FakeSearchAdapter` (`integrations/search/fake.py:82-145`) implements `SearchProtocol.search` with `material_id` and `version_id` filtering only.
- `KnowledgeRepository` (`repositories/knowledge.py:286-313`) has `get_snippets_for_point(knowledge_point_id, user_id)` returning `list[MaterialSnippet]` ordered by `snippet_index.asc()`.
- `MaterialRepository` (`repositories/material.py:669-715`) has `get_snippets(version_id, user_id)` and `list_snippets_by_ids(snippet_ids, user_id)`.
- **Clean ways to support `allowed_snippet_ids` and neighbor lookup (`snippet_index ± 1`) without violating `import-linter`**:
  1. **`allowed_snippet_ids` pushdown**: Add `allowed_snippet_ids: Sequence[uuid.UUID] | None = None` to `SearchOptions` (or `SearchProtocol.search`), apply `.where(MaterialSnippet.id.in_(...))` in `PgvectorHybridSearchAdapter` before `ORDER BY ... LIMIT vector_top_k`, and mirror the filter in `FakeSearchAdapter` (and guard empty collection -> immediate empty `SearchResult` without querying DB).
  2. **Neighbor lookup (`snippet_index ± 1`)**:
     - Either add `snippet_index: int | None = None` to `SearchSnippetCandidate` and a helper on `SearchProtocol` / `PgvectorHybridSearchAdapter` (using `tuple_(MaterialSnippet.version_id, MaterialSnippet.snippet_index).in_(pairs)` with `MaterialSnippet.user_id == user_id`, backed by `uq_material_snippets_version_index`), OR
     - Add `list_neighbor_snippets(pairs, user_id)` to `MaterialRepository` (keeping DB reads in `repositories` and orchestration in `app/services`, e.g., passing neighbor-fetching callback or assembling expanded context in `QuestionService.ask_scoped_coach` / `coach_graph`). Remember: `app.repositories` MUST NOT import `app.integrations`, and `app.integrations` MUST NOT import `app.services` or `app.api`.

---

## 4. `/coach/ask` API Contract, Frontend Chat State & `richText.ts` Capabilities

### 4.1 Backend `/coach/ask` & `/questions/{id}/ask-coach` (`backend/app/api/v1/questions.py`, `backend/app/schemas/question.py`)
- **`POST /api/v1/coach/ask`** (`questions.py:370-388`):
  - **Sync `def` route** (per `directory-structure.md:80`: sync SQLAlchemy `Session` + sync `httpx.Client` must use `def`, never `async def`).
  - Request `ScopedCoachRequest` (`schemas/question.py:333-351`):
    - `folder_id: uuid.UUID | None = None`
    - `material_id: uuid.UUID | None = None`
    - `knowledge_point_id: uuid.UUID | None = None`
    - `user_prompt: str = Field(min_length=1, max_length=1000)`
    - Validator requires **exactly one** of `folder_id | material_id | knowledge_point_id`.
    - **No `session_id`, `thread_id`, or `history` fields exist.**
  - Response `ScopedCoachResponse(AskCoachResponse)` (`schemas/question.py:320-330, 354-360, 400-401`):
    - `reply: str`
    - `suggestions: list[str]`
    - `sources: list[CoachSourceResponse]` (`snippet_id`, `material_id`, `chapter_title`, `excerpt`, `source_info`)
  - Backend execution (`services/question.py:1641-1722` -> `integrations/llm/coach_graph.py:139-169`): completely stateless per request; `build_coach_graph(search, llm)` compiles a fresh `StateGraph` without a checkpointer.
- **`POST /api/v1/questions/{id}/ask-coach`** (`questions.py:335-367`):
  - Request `AskCoachRequest`: `user_prompt`, `user_answer`, `grading_points` (also no `session_id`/`thread_id`/`history`).
  - Response `AskCoachResponse`: `reply`, `suggestions`.

### 4.2 Frontend Chat & API Client (`miniprogram/src/composables/useCoachChat.ts`, `miniprogram/src/api/modules/questions.ts`, `miniprogram/src/types/`)
- `useCoachChat.ts` (`lines 27-33, 56-192`):
  - Maintains client-side `sessionHistories: Map<string, CoachMessage[]>` keyed by `buildCoachSessionKey(ctx)`: `q:<questionId>`, `kp:<knowledgePointId>`, `mat:<materialId>`, `folder:<folderId>`, or `'global'`.
  - **Does NOT send `session_id`, `thread_id`, or `history`** to either `/questions/{id}/ask-coach` or `/coach/ask`.
- `apiAskScopedCoach` (`miniprogram/src/api/modules/questions.ts:146-154`):
  - Sends `ScopedCoachParams` (`{ folder_id?, material_id?, knowledge_point_id?, user_prompt }`, defined in `miniprogram/src/types/question.ts:89-94`) with `LONG_REQUEST_TIMEOUT_MS`.
  - Returns `AskCoachResponse` (`miniprogram/src/types/diagnosis.ts:76-87`: `{ reply, suggestions, sources?: CoachSource[] }`). Note frontend `CoachSource` omits `source_info` (though `CoachMessageList.vue:52-60` only renders `chapter_title` and `excerpt`).
- Adding optional `session_id` / `thread_id` / `history` to `ScopedCoachRequest` (backend) and `ScopedCoachParams` / `useCoachChat.ts` (frontend) is backward-compatible if defaulted to `None` / optional.

### 4.3 `miniprogram/src/utils/richText.ts` (Markdown + LaTeX AST Parser)
- Targets WeChat Mini Program `<rich-text :nodes>` (`RichContent.vue:3`), using inline `style` attributes with `rgb(...)` (CSS variables are unsupported inside `<rich-text>`).
- **Currently supported**:
  - **Delimiters**:
    - Block math: `$$...$$`, `\[...\]` (single-line or multi-line at block level, rendered in `<div class="rt-math-block">`).
    - Inline math: `$$...$$` (single-line), `$...$` (guarded against currency like `$5 和` by `isLikelyInlineDollarMath`), `\(...\)`, plus unfenced `\command` in supported set and unfenced `_` / `^` scripts (`tryConsumeUnfencedScript`).
  - **Symbols (`LATEX_SYMBOL_MAP`, `lines 47-136`)**:
    - Lowercase Greek (`\alpha`..`\omega`, `\sigma` -> `σ`, variants `\varepsilon`, `\vartheta`, `\varpi`, `\varrho`, `\varsigma`, `\varphi`).
    - Uppercase Greek (`\Gamma`, `\Delta`, `\Theta`, `\Lambda`, `\Xi`, `\Pi`, `\Sigma` -> `Σ`, `\Phi`, `\Psi`, `\Omega`).
    - Big operators / calculus: `\sum` (`∑`), `\prod` (`∏`), `\int` (`∫`), `\partial`, `\nabla`, `\infty`, `\propto`.
    - Relations, sets, logic, arrows: `\le/\leq`, `\ge/\geq`, `\ne/\neq`, `\approx`, `\equiv`, `\sim`, `\simeq`, `\cong`, `\in`, `\notin`, `\subset`, `\subseteq`, `\supset`, `\supseteq`, `\cup`, `\cap`, `\emptyset`, `\times`, `\cdot`, `\div`, `\pm`, `\mp`, `\circ`, `\to/\rightarrow`, `\leftarrow`, `\leftrightarrow`, `\Rightarrow`, `\Leftrightarrow`, `\forall`, `\exists`, `\neg`, `\land`, `\lor`, `\therefore`, `\because`, `\ldots/\cdots/\dots`.
  - **Fractions**: `\frac{a}{b}`, `\dfrac{a}{b}`, `\tfrac{a}{b}` -> flattened inline `(a)/(b)` (`lines 226-242`), **not** stacked HTML/CSS fractions.
  - **Roots**: `\sqrt{x}` -> `√(x)` (`lines 244-253`; optional `[n]` root degree like `\sqrt[3]{x}` is not handled).
  - **Scripts**: `_{...}`, `^{...}`, single token `_x` / `^x` -> `<sub>` and `<sup>` (`lines 286-299, 337-406`).
  - **Wrappers & layout**: strips `\text`, `\mathrm`, `\mathbf`, `\mathit`, `\mathcal`, `\operatorname`, `\boldsymbol`; ignores `\left`, `\right`, `\limits`, `\nolimits`, `\quad`, `\qquad`.
  - **Markdown blocks**: `#..####` headings, `>` blockquotes, `-`/`*`/`•` and `1.`/`1)` lists (non-nested), ```` ``` ```` fenced code blocks, paragraphs, inline `` `code` ``, `**bold**`, `__bold__`, `*italic*`.
- **Unsupported / Gaps**:
  - **Matrices / LaTeX environments**: No `\begin{...}...\end{...}` (`pmatrix`, `bmatrix`, `vmatrix`, `cases`, `align`, `array`) and no `\\` row-break handling inside math. `\begin{pmatrix}` degrades to literal `"beginpmatrix..."` with `&` and `\\` left raw.
  - **Markdown Tables**: No GFM pipe table (`| a | b |`) parser in `parseRichContent` or `isBlockStarter`; table lines render as plain `<p>` text with `|` characters.
  - **Other LaTeX commands**: Unlisted commands (e.g. `\hat`, `\bar`, `\vec`, `\overline`, `\binom`, `\mathbb`, `\lim`, `\log`, `\sin`, `\cos`, `\det`) fall through to `pushText(out, cmd)`, stripping `\` and leaving the bare command name.

---

## Files Found

| Path | Role |
| --- | --- |
| `backend/app/core/config.py` | `AppSettings` and 9 domain `*Settings` models (`ZHILIAN_` + `__`), `validate_secret_key` |
| `backend/.env.example` | Zero-dependency default env template (`fake`/`memory` providers) |
| `backend/app/container.py` | `AppContainer` (SQLAlchemy engine/sessionmaker, `ProviderRegistry`, 8 service factories, health/lifecycle) |
| `backend/app/integrations/container.py` | `ProviderRegistry` (strict 7-protocol registry + `create_default` + `shutdown`) |
| `backend/pyproject.toml` | Dependencies, `ruff` (`max-complexity=15`), `mypy` (`strict=true`), `pytest`, 6 `import-linter` contracts |
| `backend/app/integrations/llm/protocol.py` | `LLMMessage` (`content: str`), `LLMOptions`, `LLMResponse`, `LLMProtocol` |
| `backend/app/integrations/llm/openai.py` | `OpenAICompatibleLLMAdapter` (text-only `/chat/completions`, retry via `_http_retry.py`, LangGraph structured repair) |
| `backend/app/integrations/llm/fake.py` | `FakeLLMAdapter` (assumes `msg.content` is `str`) |
| `backend/app/integrations/llm/agent_graph.py` | Existing LangGraph `StateGraph` for structured JSON/tool-call self-healing |
| `backend/app/integrations/llm/coach_graph.py` | Existing LangGraph `StateGraph` for `/coach/ask` (`retrieve -> generate -> validate`, stateless) |
| `backend/app/integrations/ocr/protocol.py` | `OCRProtocol` (`recognize_image`, `recognize_url`), `OCRResult`, `OCROptions` |
| `backend/app/integrations/search/protocol.py` | `SearchProtocol`, `SearchOptions`, `SearchResult`, `SearchSnippetCandidate` |
| `backend/app/integrations/search/pgvector.py` | `PgvectorHybridSearchAdapter` (pgvector cosine + BM25 + RRF/weighted fusion, tenant-isolated) |
| `backend/app/integrations/search/fake.py` | `FakeSearchAdapter` |
| `backend/app/models/material.py` | `Material`, `MaterialVersion`, `MaterialSnippet` (no `page_number` col; has `source_info` JSONB, `uq_material_snippets_version_index`, HNSW index), `MaterialOCRPage` |
| `backend/app/repositories/knowledge.py` | `KnowledgeRepository` (`get_snippets_for_point`, etc.) |
| `backend/app/repositories/material.py` | `MaterialRepository` (`get_snippets`, `list_snippets_by_ids`, etc.) |
| `backend/app/core/extractors.py` | `pypdf` extraction + missing-ToUnicode symbol font diagnostics |
| `backend/app/services/_material_pipeline.py` | PDF garble repair (`_repair_pdf_page_text`) + snippet chunking/embedding preparation |
| `backend/app/services/source_snippets.py` | Shared `SourceSnippetDTO` builder (`resolve_snippet_page_index` reads `source_info`) |
| `backend/app/api/v1/questions.py` | Sync `def` `/coach/ask` & `/questions/{id}/ask-coach` routes |
| `backend/app/schemas/question.py` | `ScopedCoachRequest`, `ScopedCoachResponse`, `CoachSourceResponse`, `AskCoachRequest/Response` |
| `backend/app/services/question.py` | `QuestionService.ask_coach` & `ask_scoped_coach` |
| `miniprogram/src/composables/useCoachChat.ts` | Client-side `sessionHistories` Map; sends stateless single-turn payloads |
| `miniprogram/src/api/modules/questions.ts` | `apiAskScopedCoach`, `apiAskQuestionCoach` |
| `miniprogram/src/types/question.ts` & `diagnosis.ts` | `ScopedCoachParams`, `AskCoachResponse`, `CoachSource` |
| `miniprogram/src/utils/richText.ts` | Zero-dep Markdown + LaTeX AST compiler for `<rich-text :nodes>` |

---

## Relevant `.trellis/spec/` Files

- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/directory-structure.md` (6 `import-linter` contracts, sync `def` route rule, worker rebuild rule)
- `.trellis/spec/backend/database-guidelines.md` (SQLAlchemy 2.0 sync Session, Alembic head consistency gate, `batch_alter_table`, `CursorResult` pattern)
- `.trellis/spec/backend/error-handling.md` (5-digit `AppError` hierarchy)
- `.trellis/spec/backend/quality-guidelines.md` (`ruff`, `mypy strict`, `lint-imports`, `pytest` caveats)
- `.trellis/spec/backend/logging-guidelines.md` (8-field sanitized logging; never log snippet/prompt contents or secrets)
- `.trellis/spec/frontend/index.md`
- `.trellis/spec/frontend/network-contract.md`
- `.trellis/spec/frontend/api-payload-contracts.md`
- `.trellis/spec/frontend/quality-guidelines.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`
- `.trellis/spec/guides/code-reuse-thinking-guide.md`

---

## Caveats / Open Questions

1. **Missing PyPI dependencies**: Neither `pymupdf` (`fitz`) nor `langgraph-checkpoint-postgres` is in `backend/pyproject.toml` or `backend/.venv` (only `langgraph==1.2.12`, `langgraph-checkpoint==4.2.0`, `pypdf==6.19.0`, `psycopg==3.3.6` are installed). Note also the sync vs async driver nuance: `AppSettings.db.db_url` in `.env.example` uses `postgresql+asyncpg://...`, whereas `AppContainer` uses sync `Session` and `migrations/env.py` normalizes `asyncpg` -> `psycopg` — any `PostgresSaver` checkpointer must handle DSN normalization (`postgresql+asyncpg://` -> `postgresql://`) and Windows/SQLite fallback (`MemorySaver` or no-op when `db_url` is `sqlite`).
2. **Sync route concurrency rule**: `directory-structure.md:80` strictly requires FastAPI routes using sync `Session` / sync `httpx.Client` to remain `def` (not `async def`). Any new LangGraph/rerank/VLM calls on the request path must stay synchronous (`httpx.Client`, sync `graph.invoke`), unless refactored end-to-end.
3. **`ProviderRegistry.validate()` strict 7-protocol check**: Adding a new protocol (e.g., `rerank`) directly into `ProviderRegistry.validate()` will break any tests constructing `ProviderRegistry(..., strict=True)` without it unless a default `FakeRerankAdapter` is provided or `rerank` is optional.
4. **No `page_number` column on `MaterialSnippet`**: Page numbers currently live inside `source_info` JSONB (`source_info["page_number"]`), not as a dedicated indexed column.
5. **Pre-existing `allowed_snippet_ids` recall gap**: `coach_graph.py` currently filters `allowed_snippet_ids` in Python *after* `vector_top_k=20` per material; pushing `allowed_snippet_ids` down to SQL in `PgvectorHybridSearchAdapter` fixes this cleanly.
6. **`richText.ts` gaps**: Inline fractions (`(a)/(b)`) work, and Greek/operators (`\sigma`, `\sum`, etc.) work, but **LaTeX matrices/environments** (`\begin{pmatrix}...\end{pmatrix}`, `\\`) and **Markdown tables** (`| ... |`) are completely unsupported today.
