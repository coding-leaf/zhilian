# Research: RAG & PDF Knowledge-Base Pipeline — Snippet Fragmentation & Broken Math Formulas

- **Query**: Diagnose why retrieved/displayed snippets in the RAG & knowledge-base pipeline look fragmented (tiny 2-line snippets like `σi\n2`, mid-sentence cuts) and contain broken math formulas (`rank σi=1\nk σpiupi ђvpi`).
- **Scope**: `backend/app/core/extractors.py`, `backend/app/core/algorithms/ocr_quality.py`, `backend/app/core/algorithms/material_chunking.py`, `backend/app/core/algorithms/search.py`, `backend/app/core/config.py`, `backend/app/services/_material_pipeline.py`, `backend/app/services/material.py`, `backend/app/services/knowledge.py`, `backend/app/services/question.py`, `backend/app/services/_question_generation.py`, `backend/app/services/source_snippets.py`, `backend/app/integrations/ocr/`, `backend/app/integrations/search/`, `backend/app/integrations/embedding/`, `backend/app/integrations/llm/coach_graph.py`, `backend/app/repositories/knowledge.py`, `backend/app/models/material.py`, `backend/pyproject.toml`.
- **Date**: 2026-11-17

---

## Executive Summary of Root Causes

The observed symptoms come from **four compounding bottlenecks** across extraction, chunking, retrieval, and response assembly:

1. **Broken Math Formulas (`σi\n2`, `rank σi=1\nk σpiupi ђvpi`)**:
   - PDF extraction uses `pypdf.PdfReader.pages[i].extract_text()` (`pypdf>=4.0.0`, no `pymupdf`/`fitz`, no layout/math parser). Subscripts/superscripts/summation bounds are emitted as separate physical lines, and subset math/symbol fonts map glyphs to wrong Greek/Cyrillic/Latin characters (`ђ`, `σpiupi`).
   - `detect_symbol_garble()` only checks ASCII symbol clusters (`!\"#$%&'*=?@^~`), and `_inspect_page_symbol_fonts_missing_tounicode()` only triggers on 7 hardcoded font-name substrings lacking `/ToUnicode`. Thus pages with `σ`/`ђ`/`σpiupi` have `needs_repair == False` and bypass repair completely.
   - Even when repair triggers, `OCRProtocol` has no PDF page rendering/formula OCR (`TencentOCRAdapter` has no `recognize_pdf_page`, `BaiduOCRAdapter.recognize_pdf_page` calls general text OCR, and `_extract_page_embedded_images` finds nothing on vector text/formula PDFs).

2. **Tiny 2-Line Snippets (`σi\n2`)**:
   - `repair_garbled_pdf_pages()` splits a page on `\n\n` (or **every single `\n`** if no `\n\n` exists on the page) into separate `ParagraphInput` items.
   - `merge_isolated_short_snippets()` (`DEFAULT_MIN_CHARS = 80`) only merges **one** `pending_short` (`< 80` chars) with the next snippet and immediately emits the merged result **without checking if the merged result is still `< 80` chars** (`material_chunking.py:216-238`). Two short lines (`"σi"` + `"2"`) merge into a 4-char `"σi\n2"` snippet and stop merging.
   - Normal paragraphs `>= 80` chars are never grouped together, and short-snippet merging ignores `page_number` and `chapter_title` boundaries.

3. **Mid-Sentence Cuts**:
   - `PRIMARY_PUNCTUATION_CHARS = "。！？!?\n"` (`material_chunking.py:33`) and `SECONDARY_PUNCTUATION_CHARS = "，；、,;"` (`:36`) **omit the ASCII period `.`**, and `align_overlap_sentence_boundary()` (`:120`) splits/aligns on `,` and `;` as well as `\n`.
   - `aggregate_snippet_context()` (`_question_generation.py:140`) hard-slices `body[:remaining] + "..."` at `max_chars=2400`.
   - `QuestionService.ask_scoped_coach()` (`question.py:1717`) hard-slices `excerpt=item.content[:320]` mid-sentence/mid-formula.

4. **Retrieval & Context Bottlenecks**:
   - `PgvectorHybridSearchAdapter` pre-filters to `vector_top_k = 20` **before** running in-memory BM25 (no full-corpus BM25/GIN FTS channel; no reranker).
   - `tokenize_text()` (`search.py:16`) uses `r"[\u4e00-\u9fa5]|[a-z0-9]+"`, stripping all Greek/math/LaTeX symbols (`σ` dropped, `"σi=1"` → `["i", "1"]`) and splitting Chinese into unigrams.
   - BM25 (`b=0.75`) rewards tiny fragmented snippets on partial token hits.
   - No neighboring chunk expansion (`snippet_index ± 1`) exists anywhere at query or display time, and `coach_graph.py` filters `allowed_snippet_ids` *after* material-wide `top_k=8` search.

---

## Findings

### 1. PDF Extraction, OCR & Formula / Garble Handling

- **Dependencies (`backend/pyproject.toml:24`)**: Only `pypdf>=4.0.0` is declared; `pymupdf` (`fitz`), `pdfplumber`, `nougat`, `pix2tex`, etc. are absent.
- **PDF Diagnostic Extractor (`backend/app/core/extractors.py:72-193`)**:
  - `extract_pdf_pages_with_diagnostics()` (`:153-193`) iterates `reader.pages` and calls `(page.extract_text() or "").strip()` (`:159`).
  - `_SYMBOL_FONT_MARKERS` (`:72-80`): `("symbol", "mt-extra", "mtex", "wingding", "webding", "math", "zapfdingbats")`.
  - `_inspect_page_symbol_fonts_missing_tounicode()` (`:111-132`): returns `True` only when `/Resources/Font` contains a font whose `/BaseFont` matches `_SYMBOL_FONT_MARKERS` **and** `"/ToUnicode" not in font_dict` (`:128-131`). PDFs with subset fonts (`CMMI`, `CMSY`, `F1`, `TT0`) or corrupt/shifted `/ToUnicode` tables return `False`.
  - `_extract_page_embedded_images()` (`:135-150`): only reads `page.images` (embedded raster bitmaps, capped at 3 per page `:146`). Vector math glyphs and PowerPoint-exported PDFs usually have 0 embedded images for formulas.
  - `PdfPageExtraction.needs_repair` (`:95-97`) is `self.lacks_tounicode_symbol_font or self.has_symbol_garble`.
- **Garble Detector (`backend/app/core/algorithms/ocr_quality.py:49-58, 245-298`)**:
  - `detect_symbol_garble()` (`:245-284`) only looks for clusters of `_GARBLE_SYMBOL_CHARS = frozenset("!\"#$%&'*=?@^~")` (`:49`).
  - Broken math extractions like `σi\n2` and `rank σi=1\nk σpiupi ђvpi` consist of Greek/Cyrillic/Latin/digits (`σ`, `ђ`, `piupi`), so `detect_symbol_garble()` returns `(False, 0.0, ())` — **false negative**.
  - Meanwhile, `calculate_gibberish_ratio()` (`:167-184`, used only for image OCR quality gate, not PDFs) uses `VALID_PRINTABLE_CHAR_PATTERN` (`:44-46`), which rejects `σ` and `ђ`, yet is never invoked on PDF pages.
- **PDF Repair & Line Splitting (`backend/app/services/_material_pipeline.py:283-404`)**:
  - `_try_ocr_pdf_page()` (`:297-325`): tries `ocr.recognize_image()` on up to 2 embedded images (`:306`), then checks `getattr(ocr, "recognize_pdf_page", None)` (`:316`).
  - `_repair_pdf_page_text()` (`:328-373`): when `not page.needs_repair and page.text.strip()` (`:335`), returns raw `page.text` untouched. When repair *does* run without `ocr_hint`, LLM receives only the garbled `pypdf` text (`:349-368`, `LLMOptions(temperature=0.1)`), and fallback calls `sanitize_symbol_garble()` (`:372`).
  - `repair_garbled_pdf_pages()` (`:375-404`): splits each page via:
    ```python
    chunks = repaired_text.split("\n\n") if "\n\n" in repaired_text else repaired_text.split("\n")
    ```
    (`:390-392`) — creating `ParagraphInput(text=stripped, source_ref=f"第 {page.page_number} 页", doc_type="pdf", page_number=page.page_number)` (`:396-402`). Notice `is_title` is never set.
- **OCR Adapters (`backend/app/integrations/ocr/`)**:
  - `OCRProtocol` (`protocol.py:82-129`): defines only `recognize_image` and `recognize_url` (no `recognize_pdf_page`, no formula OCR option).
  - `BaiduOCRAdapter` (`baidu.py:179-182, 398-420`): hits `/rest/2.0/ocr/v1/accurate` or `accurate_basic`; implements `recognize_pdf_page()` (`:398`) using `pdf_file` + `pdf_file_num`. Does not use Baidu's formula recognition endpoint.
  - `TencentOCRAdapter` (`tencent.py:116, 286-310`): uses `GeneralBasicOCRRequest`; has **no** `recognize_pdf_page()` method.
  - `OCRSettings` (`config.py:313-336`): defaults to `provider="fake"`, `endpoint="ocr.tencentcloudapi.com"`.

---

### 2. Material Chunking Algorithm (`backend/app/core/algorithms/material_chunking.py`)

- **Current Parameters**:
  - `DEFAULT_MAX_CHARS = 800` (`:14`) — also noted as a storage comment in `MaterialSnippet.content` (`models/material.py:408`: `硬性约束 <=800 字符`).
  - `DEFAULT_OVERLAP_CHARS = 120` (`:17`).
  - `DEFAULT_MIN_CHARS = 80` (`:21`).
  - `DEFAULT_MAX_SNIPPETS = 3000` (`:24`).
  - `PRIMARY_PUNCTUATION_CHARS = "。！？!?\n"` (`:33`).
  - `SECONDARY_PUNCTUATION_CHARS = "，；、,;"` (`:36`).
- **Concrete Bottlenecks**:
  1. **Single-pair short-snippet merge bug (`merge_isolated_short_snippets`, `:196-294`)**:
     - When `pending_short` (`char_count < 80`) is combined with the next `snippet` (`:216-238`), it appends `merged_snippet` directly to `merged` and resets `pending_short = None` (`:236-237`), **even if `len(new_content) < min_chars` (e.g. `"σi\n2"` = 4 chars)**. Thus 3+ consecutive short lines (common in PPT slides and stacked formulas) collapse only pairwise into tiny 2-line snippets.
     - Similarly, tail merge (`:250-276`) only merges the last pending snippet backward once.
  2. **Cross-page & cross-chapter merging (`:215-248`)**:
     - `merge_isolated_short_snippets` never checks `pending_short.page_number == snippet.page_number` or `pending_short.chapter_title == snippet.chapter_title`, merging end-of-page fragments into the next slide/page (`:227-234`).
  3. **No paragraph accumulation up to target chunk size (`:347-391`)**:
     - `split_material_into_snippets` processes each `ParagraphInput` one-by-one (`:373`). Any line/paragraph `>= 80` chars becomes its own standalone snippet rather than grouping related bullets/lines on the same slide/section toward `max_chars` (e.g., 400–800 chars).
  4. **Missing ASCII `.` in punctuation lists & mid-sentence overlap (`:33, :36, :120, :126-150`)**:
     - `PRIMARY_PUNCTUATION_CHARS` (`"。！？!?\n"`) does **not** include ASCII `.` (nor `SECONDARY_PUNCTUATION_CHARS = "，；、,;"`). English sentences or mixed Chinese-English technical text without `\n` or `。` skip `.` and split at `,` or hard-cut at `target_end_index` (`:150`).
     - `align_overlap_sentence_boundary()` (`:120`) matches `[。！？!?\n，；、,;]` and slices `candidate[match.end():]` — starting overlapped chunks mid-sentence right after a comma `,` or semicolon `;`, and lacking `.` or `$...$` awareness.
  5. **Zero heading / formula / slide-page boundary awareness**:
     - `is_title` (`:52, :368-370`) is never populated by PDF (`_material_pipeline.py:396-402`) or DOCX/PPTX/MD/TXT (`extractors.py:318-344`) extractors, leaving `chapter_title == ""`.
     - No protection for LaTeX/math delimiters (`$$...$$`, `$...$`, `\begin{...}...\end{...}`) or multi-line equations; `\n` inside a formula is treated as a primary split boundary (`:33`).

---

### 3. Hybrid Search, BM25 Tokenization & Configuration

- **Config (`backend/app/core/config.py`)**:
  - `SearchSettings` (`:135-155`): `provider: Literal["fake", "pgvector"] = "fake"`, `vector_dimension = 1024`, `distance_strategy = "cosine"` (note: `PgvectorHybridSearchAdapter` does not read `distance_strategy`; it hardcodes `cosine_distance` at `pgvector.py:119`).
  - `EmbeddingSettings` (`:204-258`): `provider = "fake"`, `model = "text-embedding-v3"`, `dimension = 1024`, `batch_size = 16`, `timeout = 20.0`, `max_retries = 3`. (Note: `OpenAICompatibleEmbeddingAdapter.embed_documents()` in `embedding/openai.py:174-213` sends `list(texts)` in one request without slicing by `batch_size`.)
- **Search Options (`backend/app/integrations/search/protocol.py:40-49`)**:
  - `top_k: int = 4` (`:43`)
  - `vector_top_k: int = 20` (`:44`)
  - `fusion_method: str = "rrf"` (`:45`)
  - `rrf_k: int = 60` (`:46`)
  - `vector_weight: float = 0.7` (`:47`)
  - `keyword_weight: float = 0.3` (`:48`)
  - **Reranker**: None exists anywhere in `backend/app/`.
- **PgvectorHybridSearchAdapter (`backend/app/integrations/search/pgvector.py:57-231`)**:
  - Step 2 (`:95-121`): PostgreSQL queries `MaterialSnippet` with HNSW cosine distance `ORDER BY embedding <=> query_vector LIMIT vector_top_k` (`:118-120`, default `20`).
  - Step 3 (`:133-166`): Computes Okapi BM25 **only over the `<= 20` vector-retrieved snippets** (`total_docs = len(snippets)`). There is **no** independent PostgreSQL full-text search / `tsvector` / GIN channel, so exact keyword/formula matches outside the vector Top-20 are never recalled.
  - Step 4 (`:184-196`): RRF fusion (`reciprocal_rank_fusion`, `k=60`, `weights=[0.7, 0.3]`) mixes vector ranks and BM25 ranks without any minimum BM25/vector gate at adapter level.
- **BM25 & Tokenization (`backend/app/core/algorithms/search.py:16-118`)**:
  - `tokenize_text()` (`:16-33`): `_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fa5]|[a-z0-9]+")`.
    - Chinese is tokenized as single characters (`unigrams`), with no phrase/bigram/jieba segmentation and no stopwords.
    - All Greek letters (`σ`, `λ`, `α`), math operators (`=`, `+`, `^`, `_`), Cyrillic/garbled glyphs (`ђ`), and LaTeX punctuation (`\`, `$`, `{`, `}`) are **silently stripped**. E.g., `"rank σi=1\nk σpiupi ђvpi"` tokenizes to `["rank", "i", "1", "k", "piupi", "vpi"]`, and `"σi\n2"` tokenizes to `["i", "2"]`.
  - `compute_bm25_score()` (`:36-82`): uses `k1 = 1.5`, `b = 0.75` (`:43-44`). Length normalization `len_norm = 1.0 - b + b * (actual_doc_length / avg_len)` (`:70`) strongly boosts ultra-short 2–6 token snippets (`σi\n2`, `rank σi=1`) whenever a single token (`2`, `i`, `1`, `rank`) matches the query.

---

### 4. Knowledge Linking vs Query-Time Retrieval, Query Formulation & Context Window

- **Parse-Time KP-to-Snippet Linking (`backend/app/services/knowledge.py:138-460`)**:
  - `_run_extraction_with_retries()` (`:264-357`) passes batches of `batch_size = 40` snippets (reduced to `20` on quality-gate retry `:314, :351`) to LLM (`_build_batch_prompt`, `:138-189`), labeled `片段 #{s.snippet_index}: {s.content}` (`:184`).
  - LLM outputs `source_snippet_indices: list[int]` (`core/algorithms/knowledge_tree.py:60`), stored as `KnowledgePointSnippet` rows (`knowledge.py:428-459`).
  - `KnowledgeService.get_snippets_for_point()` (`knowledge.py:626-644`, `repositories/knowledge.py:286-313`) returns those bound `MaterialSnippet` rows directly (`GET /knowledge/{id}/snippets` → `SnippetSourceResponse`, `schemas/knowledge.py:86-138`) with no neighbor merging or cleanup.
- **Question Generation (`backend/app/services/question.py:198-310, 362-372`, `backend/app/services/_question_generation.py:121-161`)**:
  - `_retrieve_and_gate_snippets()` (`question.py:198-310`) loads `bound_snippets` (`:225`) and *also* calls `search_adapter.search(query=kp_name, ...)` (`:229-236`) — using **only `kp_name`** (dropping `kp_description`), with default `SearchOptions(top_k=4, vector_top_k=20)`. It tops up `candidates` to `4` (`:293-296`) and enforces `max_score >= 0.35` (`:300`).
  - `aggregate_snippet_context(snippets, max_chars=2400)` (`_question_generation.py:121-161`) takes `snippets[:4]` (`:126`) and hard-truncates mid-character (`body[:remaining] + "..."`, `:140`) once `2400` chars is reached.
  - `QuestionService.attach_source_snippets()` (`question.py:1218-1246`) and `PracticeService` share `build_source_snippet_map()` (`source_snippets.py:37-68`), returning only the single `question.source_snippet_id` content (`:65`) with **zero context window expansion**.
- **Scoped AI Coach (`backend/app/services/question.py:1641-1722`, `backend/app/integrations/llm/coach_graph.py:42-171`)**:
  - `ask_scoped_coach()` (`question.py:1641-1722`): when `knowledge_point_id` is given (`:1674-1689`), loads `allowed_snippet_ids` from `get_snippets_for_point` (`:1685-1688`) and formats `user_prompt = f"关于知识点「{point.name}」：{user_prompt}"` (`:1689`). No other query expansion or reformulation occurs.
  - `coach_graph.py:retrieve()` (`:45-74`): calls `search.search(..., options=SearchOptions(top_k=8, vector_top_k=20))` (`:55`) per `material_id`, filters `vector_score < 0.35` (`:64-65`), and filters `allowed_snippet_ids` **after** the material-wide `top_k=8` cut (`:62-63`) — meaning KP-bound snippets outside the material-wide Top 8 are silently lost.
  - `coach_graph.py:generate()` (`:79-83`) passes `item.content[:800]` with **no** adjacent-snippet expansion (`snippet_index ± 1`).
  - `ask_scoped_coach()` (`question.py:1717`) constructs `CoachSourceResponse` with **`excerpt=item.content[:320]`**, which **hard-truncates snippets at 320 chars mid-sentence/mid-formula** before sending to `miniprogram/src/components/CoachMessageList.vue:58`.

---

## Files Found

| Path | Role |
| --- | --- |
| `backend/pyproject.toml` | Declares `pypdf>=4.0.0` (`:24`); no `pymupdf` or reranker dependencies |
| `backend/app/core/extractors.py` | `extract_pdf_pages_with_diagnostics` (`:153-193`), `_SYMBOL_FONT_MARKERS` (`:72-80`), `_extract_page_embedded_images` (`:135-150`) |
| `backend/app/core/algorithms/ocr_quality.py` | `detect_symbol_garble` (`:245-284`), `sanitize_symbol_garble` (`:287-298`), `calculate_gibberish_ratio` (`:167-184`) |
| `backend/app/services/_material_pipeline.py` | `repair_garbled_pdf_pages` (`:375-404`), `_repair_pdf_page_text` (`:328-373`), `_try_ocr_pdf_page` (`:297-325`), `prepare_material_snippets` (`:407-444`) |
| `backend/app/services/material.py` | `_extract_source_content` (`:362-418`), `parse_material_pipeline` (`:448-604`) |
| `backend/app/integrations/ocr/protocol.py` | `OCRProtocol` (`:82-129`, image/URL only, no `recognize_pdf_page` or formula mode) |
| `backend/app/integrations/ocr/baidu.py` | `BaiduOCRAdapter` (`:179-182` accurate OCR, `:398-420` `recognize_pdf_page`) |
| `backend/app/integrations/ocr/tencent.py` | `TencentOCRAdapter` (`:116` `GeneralBasicOCRRequest`, no PDF/formula method) |
| `backend/app/core/algorithms/material_chunking.py` | Chunking constants (`:14-36`), `align_overlap_sentence_boundary` (`:105-123`), `find_best_split_point` (`:126-150`), `merge_isolated_short_snippets` (`:196-294`), `split_material_into_snippets` (`:297-417`) |
| `backend/app/models/material.py` | `MaterialSnippet` (`:380-471`, HNSW `vector_cosine_ops` index `:464-470`) |
| `backend/app/core/config.py` | `SearchSettings` (`:135-155`), `EmbeddingSettings` (`:204-258`), `OCRSettings` (`:299-373`) |
| `backend/app/integrations/search/protocol.py` | `SearchOptions` (`:40-58`: `top_k=4`, `vector_top_k=20`, `fusion_method="rrf"`, `rrf_k=60`, `0.7/0.3`) |
| `backend/app/integrations/search/pgvector.py` | `PgvectorHybridSearchAdapter.search` (`:57-231`, vector Top-20 pre-filter then in-memory BM25 + RRF) |
| `backend/app/core/algorithms/search.py` | `tokenize_text` (`:16-33`), `compute_bm25_score` (`:36-82`), `reciprocal_rank_fusion` (`:85-117`) |
| `backend/app/integrations/embedding/openai.py` | `OpenAICompatibleEmbeddingAdapter` (`:33-214`) |
| `backend/app/services/knowledge.py` | `KnowledgeService._run_extraction_with_retries` (`:264-357`), `extract_and_build_knowledge_tree` (`:359-500`), `get_snippets_for_point` (`:626-644`) |
| `backend/app/repositories/knowledge.py` | `KnowledgeRepository.get_snippets_for_point` (`:286-313`) |
| `backend/app/schemas/knowledge.py` | `SnippetSourceResponse` (`:86-138`) |
| `backend/app/services/question.py` | `_retrieve_and_gate_snippets` (`:198-310`), `attach_source_snippets` (`:1218-1246`), `ask_scoped_coach` (`:1641-1722`) |
| `backend/app/services/_question_generation.py` | `aggregate_snippet_context` (`:121-161`, `max_chars=2400`) |
| `backend/app/services/source_snippets.py` | `build_source_snippet_map` (`:37-68`) |
| `backend/app/integrations/llm/coach_graph.py` | `build_coach_graph` (`:42-136`: `top_k=8`, `vector_score >= 0.35`, `allowed_snippet_ids` post-filter) |

---

## Relevant `.trellis/spec/` Files

- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/logging-guidelines.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`

---

## Caveats / Open Questions

1. **Runtime OCR/Embedding Provider**: `config.py` defaults to `fake` for `ocr`, `embedding`, and `search`; actual production behavior depends on `backend/.env` settings (which were not read for secret values, though `issue2-reparse-stuck.md:23` notes `search_provider = pgvector` and `embedding_provider = openai` are active in deployment).
2. **Legacy vs Re-parsed Snippets**: Materials parsed before `repair_garbled_pdf_pages` was added (`5c981b0`) did not run symbol repair at all; however, even after `5c981b0`, pages with `σ`/`ђ`/`σpiupi` fail to trigger `needs_repair`, and `repair_garbled_pdf_pages` + `material_chunking.py` still create the 2-line fragments observed.
3. **Database `MaterialSnippet.content` Length Expectation**: `models/material.py:408` documents `硬性约束 <=800 字符` as a comment (the column type itself is `Text`), and `SearchOptions.top_k` / `aggregate_snippet_context(max_chars=2400)` assume snippets are around `<=800` chars; any chunk-size or neighbor-expansion change should verify downstream prompt budgets (`knowledge.py` batch of 40 snippets, `coach_graph.py` 8×800 chars, `question.py` 2400 chars).
