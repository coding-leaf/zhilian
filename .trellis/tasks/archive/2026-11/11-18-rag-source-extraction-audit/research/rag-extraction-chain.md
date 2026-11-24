# Research: 教材解析 → 分块入库 → RAG检索与引用回溯 → 前端“查看教材原文依据”全链路排查

- **Query**: 端到端排查项目“教材解析 → 分块入库 → RAG检索与引用回溯 → 前端‘查看教材原文依据’展示”完整链路，定位“查看教材原文依据 (5处)”截图中出现的第3/4页仅显示“基本概念”、第5页文本极度碎片化与换行破碎、以及数学符号乱码（`ħx1`）的产生环节与根因。
- **Scope**:
  - `miniprogram/src/subpackages/material/**`、`miniprogram/src/api/**`、`miniprogram/src/stores/material.ts`、`miniprogram/src/components/RichContent.vue`、`miniprogram/src/utils/richText*.ts`
  - `backend/app/api/v1/{materials,knowledge,questions}.py`、`backend/app/services/{material,_material_pipeline,knowledge,question,_question_generation,source_snippets}.py`
  - `backend/app/core/{extractors,config}.py`、`backend/app/core/algorithms/{ocr_quality,markdown_blocks,material_chunking,search,text_excerpt,knowledge_tree}.py`
  - `backend/app/integrations/{container,llm/factory,llm/coach_graph,search/pgvector,search/_neighbors,rerank/siliconflow}.py`
  - `backend/app/models/{material,knowledge}.py`、`backend/app/repositories/{material,knowledge}.py`、`backend/app/schemas/knowledge.py`
- **Date**: 2026-11-18

---

## Findings

### 1. 前端展示链路（`miniprogram/`）

1. **页面与弹窗触发入口**：
   - 讲义详情页 `miniprogram/src/subpackages/material/pages/course/index.vue:20-26, 37-48` 挂载 `KnowledgePointList` 与 `KnowledgeSnippetModal`。
   - 点击考点触发 `useCourseDetail().openPointDetail(node)`（`miniprogram/src/subpackages/material/composables/useCourseDetail.ts:192-207`），打开弹窗并调用 `materialStore.loadKnowledgePointWithSnippets(node.id)`（`miniprogram/src/stores/material.ts:107-119`）。
   - `loadKnowledgePointWithSnippets` 并行请求 `apiGetKnowledgePointDetail(pointId)`（`GET /knowledge/{id}`）和 `apiGetKnowledgePointSnippets(pointId)`（`GET /knowledge/{id}/snippets`，见 `miniprogram/src/api/modules/knowledge.ts:32-37`）。
2. **响应归一化（Adapter）**：
   - `adaptPointSourceList` / `adaptKnowledgeSnippet`（`miniprogram/src/api/adapters/knowledge.ts:134-160`）对每条切片原样透传 `snippet.content ?? ''`，`page_index` 缺省/非法时回退为 `1`，`chapter_title` 仅做 `trim()`（空串转为 `null`）。前端**未做**任何去重、合并或短片段过滤。
3. **弹窗渲染与乱码拦截**：
   - `KnowledgeSnippetModal.vue:82-120` 渲染“查看教材原文依据 (${snippets.length}处)”。展开后遍历 `snippets`：
     - 元信息行（`:102-105`）：`第 {{ snip.page_index || 1 }} 页` 与可选 `snip.chapter_title`。
     - 乱码拦截分支（`:106-110, 192`）：调用 `isGarbledSnippetText(snip.content)`（`miniprogram/src/utils/richText.ts:410-428`）。该函数**仅检测** ASCII 符号簇 `[!"#$%&'*=?@^~]`（连续 >=3 个、或 `[A-Z]{1,2}&` 重复、或高密度符号对），对 `ħ`（`U+0127`）或碎换行**完全放行**。
     - 正文渲染（`:111`）：`<RichContent :content="snip.content" compact muted />`。
4. **富文本与换行渲染放大器**：
   - `RichContent.vue:2-3, 23` 调用 `parseRichContent(props.content)` 输出微信 `<rich-text :nodes>` AST。
   - `parseRichContent`（`miniprogram/src/utils/richText.ts:379-393`）将连续非块级行收集进 `paraLines`，再经 `buildMultilineChildren`（`:215-222`）**把每一个 `\n` 显式转为 `{ name: 'br' }` 节点**。
   - 因此后端切片中残留的所有 PDF 硬折行 `\n` 和短块拼接 `\n` 都会在小程序端原封不动折成独立短行。
5. **其他前端原文依据入口（对照）**：
   - 题卡/报告页的 `source_quote`（来源于 `question.source_snippet?.snippet_content`，`miniprogram/src/api/adapters/question.ts:85`、`adapters/practice.ts:138`）：在 `QuestionPreviewCard.vue:61-67, 112` 与 `reportView.ts:148-155` 同样使用 `isGarbledSnippetText` + `RichContent` 渲染。
   - AI 助教消息气泡的 `msg.sources`（`miniprogram/src/components/CoachMessageList.vue:52-60`）：以纯 `<text>` 渲染 `source.excerpt`（`source.chapter_title || '打开来源讲义'`）。

---

### 2. 后端检索与引用链路（`backend/`）

系统内存在**两条独立**的依据关联/检索链路，前端“查看教材原文依据”走的是**链路 A（解析期静态绑定 + 查库直出）**，而非运行时向量/Rerank 检索：

#### 链路 A：知识点“查看教材原文依据”（当前截图所在链路）
1. **解析期绑定（Parse-Time Linking）**：
   - 在 `MaterialService.parse_material_pipeline`（`backend/app/services/material.py:542-557`）阶段 C，调用 `KnowledgeService.extract_and_build_knowledge_tree`（`backend/app/services/knowledge.py:359-500`）。
   - `_run_extraction_with_retries`（`knowledge.py:264-357`）将切片按 `batch_size=40`（重试缩为 `20`）分批，通过 `_build_batch_prompt`（`:138-189`）以 `片段 #{s.snippet_index} [章节: ...]:\n{s.content}` 喂给 LLM，要求输出 `source_snippet_indices: list[int]`（`backend/app/core/algorithms/knowledge_tree.py:60`）。
   - 落库时（`knowledge.py:428-459`），按 `(kp_uuid, snippet_id)` 写入关联表 `knowledge_point_snippets`（`KnowledgePointSnippet`，`backend/app/models/knowledge.py:145-197`）。
2. **查询期反向溯源（Query-Time Lookup，无检索/无重排）**：
   - 接口 `GET /api/v1/knowledge/{id}/snippets`（`backend/app/api/v1/knowledge.py:110-138`）→ `KnowledgeService.get_snippets_for_point`（`knowledge.py:626-644`）→ `KnowledgeRepository.get_snippets_for_point`（`backend/app/repositories/knowledge.py:286-313`）。
   - SQL 直接 `JOIN knowledge_point_snippets` 按 `MaterialSnippet.snippet_index ASC` 返回全部绑定切片，经 `SnippetSourceResponse`（`backend/app/schemas/knowledge.py:86-138`）序列化 `page_index`（优先取 `source_info["page_number"]`，默认 `1`）、`chapter_title`、`content`。
   - **关键点**：查询期**不做**任何短片段过滤、标题剔除、邻接拼接或文本清洗——入库时 `material_snippets` 长什么样，前端就展示什么样。

#### 链路 B：RAG 混合检索、精排与引用（出题 & AI 助教）
1. **混合检索适配器（`PgvectorHybridSearchAdapter`）**：
   - `backend/app/integrations/search/pgvector.py:133-337` 实现双通道召回 + 融合：
     - 向量通道：PostgreSQL 下用 `MaterialSnippet.embedding.cosine_distance(query_vector)` 取 `vector_top_k`（默认 `20`，助教图传入 `30`）；
     - 独立关键词通道：`build_keyword_statement`（`:66-88`）用 `extract_keyword_tokens` 分词后做全库 `ILIKE` 匹配，按命中词元数降序补召回；
     - 精排打分：对并集候选计算 `cosine_similarity` 与 `compute_bm25_score`（`backend/app/core/algorithms/search.py:109-163`，已设 `b=0.45` 及 `MIN_EFFECTIVE_DOC_LENGTH=25.0` 抑制短碎片虚高，且 `tokenize_text` 在 `:72-106` 支持希腊字母与 `\sigma` 命令互通），再经 `reciprocal_rank_fusion`（`:166-198`）截断返回 `top_k`。
2. **出题与题目原文依据（`QuestionService`）**：
   - `QuestionService._retrieve_and_gate_snippets`（`backend/app/services/question.py:213-325`）先查 `get_snippets_for_point` 绑定切片，不足 4 条时用 `search_adapter.search(query=kp_name)` 补足 4 条，门禁 `max_score >= 0.35`。
   - `aggregate_snippet_context`（`backend/app/services/_question_generation.py:122-162`）拼接 Top 4（上限 `2400` 字符，超长时调用 `trim_excerpt_cleanly` 保护句末与公式），落库 `Question.source_snippet_id`。
   - 题目查询响应通过 `QuestionService.attach_source_snippets`（`question.py:1233-1260`）调用共享 `build_source_snippet_map`（`backend/app/services/source_snippets.py:37-68`）装配 `SourceSnippetDTO`，同样**直接输出** `snippet.content` 原文（无邻接扩展）。
3. **Scoped AI 助教 Adaptive + Corrective RAG（`coach_graph.py`）**：
   - 接口 `POST /api/v1/coach/ask`（`backend/app/api/v1/questions.py:371`）→ `QuestionService.ask_scoped_coach`（`question.py:1735-1816`）→ `run_coach_graph`（`backend/app/integrations/llm/coach_graph.py:683-741`）。
   - `retrieve_and_rerank`（`:508-535`）：`_search_pool`（`:290-332`）已把 `allowed_snippet_ids`（单考点模式）下推到 `SearchOptions`；随后调用 `SiliconFlowRerankAdapter.rerank`（`backend/app/integrations/rerank/siliconflow.py:136-172`，`BAAI/bge-reranker-v2-m3`）按 `min_score=0.25` / `rewrite_threshold=0.45` 做确定性门禁与至多 1 次 `rewrite_query`。
   - 入选切片经 `_expand_with_neighbors`（`coach_graph.py:363-394`）调用 `fetch_neighbor_snippets`（`pgvector.py:339-383` + `backend/app/integrations/search/_neighbors.py:32-91`）在**同版本同页**内拼接 `snippet_index ± 1`，并经 `merge_adjacent_snippet_texts` & `trim_excerpt_cleanly` 组装 LLM 证据。
   - `verify_citations`（`coach_graph.py:404-413, 613-628`）过滤幻觉 ID 后，由 `ask_scoped_coach`（`question.py:1806-1815`）用 `trim_excerpt_cleanly(item.content, max_chars=480)` 返回 `sources`。

---

### 3. 教材文档解析与分块入库链路（`backend/`）

1. **异步触发与运行时配置**：
   - `POST /api/v1/materials/{material_id}/parse`（`backend/app/api/v1/materials.py:458-500`）→ `MaterialService.trigger_parse`（`backend/app/services/material.py:1333-1417`）→ RQ Worker `_parse_material`（`backend/app/worker.py:44-53`）→ `MaterialService.parse_material_pipeline`（`material.py:460-616`）。
   - 本机实测非敏配置状态（`backend/.env` 通过 `get_settings()` 读取）：`vlm.enabled=True`（`siliconflow`）、`ocr.provider=baidu`、`llm.provider=openai`、`embedding.provider=openai`、`search.provider=pgvector`、`rerank.enabled=True`（`siliconflow`）。`AppContainer.create_material_service`（`backend/app/container.py:187-211`）已正确将 `providers.vlm` 注入 `MaterialService`。
2. **格式抽取器（`backend/app/core/extractors.py`）**：
   - 依据 `material.py:380-430`：
     - **图片**（`png/jpg/jpeg/image`）：`process_initial_ocr_page`（`_material_pipeline.py:250-284`）调 OCR + `verify_ocr_quality`，按 `\n` 切段。
     - **DOCX / PPTX / MD / TXT**：`extract_text_from_raw_content`（`extractors.py:510-535`）使用标准库 `zipfile` + `xml.etree.ElementTree` 直接提取 `word/document.xml` 的 `<w:p>/<w:t>` 或 `ppt/slides/slide*.xml` 的 `<a:t>`（PPTX 无 `page_number` 元数据，也无 `is_title`）。
     - **PDF**：`extract_pdf_pages_with_diagnostics`（`extractors.py:334-344`）优先走 `_extract_pages_with_pymupdf`（`:281-309`）：
       - 调用 `page.get_text("blocks")`，过滤掉图像块 `int(b[6]) != 0`（`:239`）；
       - 经 `_order_blocks_reading_order`（`:198-232`）按双栏或 `(round(b[1], 1), b[0])` 排序，块间以 `\n\n` 拼接，**块内部保留 PDF 物理视觉换行 `\n`**（`:235-242`）；
       - PyMuPDF 失败或全空时降级 `_extract_pages_with_pypdf`（`:312-331`）。
3. **PDF 脏页诊断与 VLM / OCR+LLM 混合路由**：
   - 每页经 `_build_page_extraction`（`extractors.py:164-184`）计算三个诊断位，汇总为 `PdfPageExtraction.needs_repair`（`:101-108`）：
     1. `lacks_tounicode_symbol_font`（`_pymupdf_page_lacks_tounicode`，`extractors.py:245-262`）：**仅当**字体名匹配 `_SYMBOL_FONT_MARKERS`（7 个小写子串：`symbol`, `mt-extra`, `mtex`, `wingding`, `webding`, `math`, `zapfdingbats`）**且** `doc.xref_get_key(xref, "ToUnicode")[0] == "null"` 时返回 `True`。
     2. `has_symbol_garble`（`detect_symbol_garble`，`ocr_quality.py:336-378`）：检测 ASCII 符号簇 `[!"#$%&'*=?@^~]`、希腊字母粘连 `>=3` 小写拉丁字母（如 `σpiupi`）、以及混入拉丁/希腊/汉字行中的孤立西里尔字母 `[\u0400-\u04ff]`（如 `ђ`）。
     3. `has_broken_math_layout`（`detect_broken_math_layout`，`ocr_quality.py:411-440`）：命中 `_math_garble_tokens` 或“非空行 >=6 且超短公式碎行（`<=8` 字符、无汉字、含数字/`_MATH_SYMBOL_CHARS`/希腊字母）占比 `> 45%`”。
   - `_page_needs_vlm(page)`（`_material_pipeline.py:430-432`）仅在 `page.needs_repair or not page.text.strip()` 时触发 `transcribe_dirty_pages_with_vlm`（`render_pdf_page_png(..., dpi=150)` → VLM Markdown+LaTeX 转录）；**否则直接走 `_repair_pdf_page_text`（`:339-340`）原样返回 `page.text`**。
4. **块切分、短段合并、向量化与表结构**：
   - `repair_garbled_pdf_pages`（`_material_pipeline.py:528-536`）对每页文本调用 `split_markdown_blocks`（`backend/app/core/algorithms/markdown_blocks.py:49-119`），生成 `ParagraphInput(text=block, source_ref=f"第 {page.page_number} 页", doc_type="pdf", page_number=page.page_number)`（**从未设置 `is_title`**）。
   - `prepare_material_snippets`（`_material_pipeline.py:553-597`）调用 `split_material_into_snippets`（`backend/app/core/algorithms/material_chunking.py:503-629`）：
     - 阶段 1（`:557-601`）：清理控制字符与行首伪列表符；若 `is_title` 为 True 则更新 `current_chapter_title` 并跳过建片（但无一处解析器传入 `is_title=True`）；超长段（`> 800` 字符）按受保护公式/表格区间 + 标点降级切分 + `120` 字符句首重叠。
     - 阶段 2（`:604-606`，`merge_isolated_short_snippets`，`:439-500`）：`DEFAULT_MIN_CHARS = 120`、`DEFAULT_TARGET_CHARS = 500`、`DEFAULT_MAX_CHARS = 800`。严禁跨 `page_number`/`chapter_title` 合并（`_same_segment`，`:376-383`）；片段合并采用 `left.content + "\n" + right.content`（`:393`）。
   - Contextual Embedding（`_material_pipeline.py:543-550, 567-575`）：向量化文本拼接 `[章节 · 页码]\n正文`，入库 `MaterialSnippet.content` 保持纯正文。
   - **入库表结构**（`backend/app/models/material.py:372-478`，`models/knowledge.py:29-197`）：
     - `material_snippets`：`id`, `user_id`, `material_id`, `version_id`, `snippet_index`, `content` (`Text`), `char_length`, `start_offset`, `end_offset`, `chapter_title`, `source_info` (`JSONB`, 含 `source_ref` 和 `page_number`), `embedding` (`vector(1024)` + HNSW `vector_cosine_ops` 索引)。
     - `knowledge_points` + `knowledge_point_snippets`（`(knowledge_point_id, snippet_id)` 唯一约束）。

---

### 4. 根因定位（逐项对应截图现象）

> **前置背景**：本仓库刚于 `fe04fbc`（2026-11-17）合入 PyMuPDF + VLM 脏页转录，但**即便在当前最新代码 + `ZHILIAN_VLM__ENABLED=true` 下重新解析该 PDF，以下 3 类现象仍会全部复现**（旧版未重解析资料则更严重）：

#### 现象 1：第 3 页、第 4 页只显示“基本概念”两个字
1. **文本门禁盲区导致图像/图表页绕过 VLM/OCR**：
   - 第 3、4 页（典型为 PPT 导出 PDF 的目录页/纯图表页/带页眉截图页）在 PyMuPDF `page.get_text("blocks")` 中（`extractors.py:239`）仅过滤出文本块，图片块（`b[6] == 1`）被直接丢弃，仅留下页眉/标题“基本概念”（4 字）。
   - `_page_needs_vlm`（`_material_pipeline.py:430-432`）只判定 `page.needs_repair or not page.text.strip()`。只要页内存在“基本概念”这 4 个字符，`not page.text.strip()` 即为 `False`，因此**既不触发 VLM 整页视觉转录，也不触发图片 OCR**，正文图片内容彻底丢失。
   - 同时 `_build_page_extraction`（`extractors.py:175`）对“干净非空页”甚至不加载 `embedded_images`。
2. **解析器从未识别标题，`chapter_title` 形同虚设，跨页硬隔离保留孤立短切片**：
   - `repair_garbled_pdf_pages`（`_material_pipeline.py:529-535`）构造 `ParagraphInput` 时从未设置 `is_title=True`，导致 `split_material_into_snippets`（`material_chunking.py:578-580`）无法将“基本概念”吸收为 `current_chapter_title`，而是把它当成独立正文切片。
   - `merge_isolated_short_snippets`（`material_chunking.py:376-383, 417`）严禁跨 `page_number` 合并，整页仅有 4 个字的“基本概念”无法与前后页合并，也没有最小有效切片过滤，最终作为 4 字符切片落库并与知识点绑定。
   - **补充路径**：即使第 4 页后续有正文，若“基本概念”在区块排序中排在长段（`>= 120` 字符）之后（例如页眉/角落文本框坐标问题）且前段接近 `800` 字符（`_append_with_backfill` `joined.char_count <= 800` 失败，`material_chunking.py:427-436`），或者位于段尾等待向后合并（`_try_forward_merge` `:420` 对前长后短故意不合并），也会留成孤立短切片。
3. **反向溯源与前端原样直出**：
   - `KnowledgeRepository.get_snippets_for_point`（`repositories/knowledge.py:286-313`）与前端 `KnowledgeSnippetModal.vue:96-112` 原样返回并渲染所有绑定切片，未过滤标题级极短切片。

#### 现象 2：第 5 页文本极度碎片化与换行破碎
由 **PyMuPDF 原始抽取 → Markdown 块切分 → 短段换行拼接 → 前端 `<br>` 渲染** 四层叠加造成：
1. **PDF 物理行折行未做段落重连（Unwrap）**：
   - PyMuPDF `page.get_text("blocks")`（`extractors.py:237`）对文本框内每一条视觉折行都保留 `\n`，于是中文自然段在行宽边缘被硬切断为 `降维的目的就是降低数据的维度从而方便后续对数据的存储、可\n视化、\n建模等操作。`。全链路没有任何步骤合并被 PDF 硬折行切断的汉字/英文单词。
2. **公式上下标与矩阵标注按 `(y0, x0)` 被拆散到段首/段尾**：
   - PDF 中 `x_1, ..., x_m`、`x_i^{(1)}, ..., x_i^{(n)}`、`m × n`、`d`、`X` 等上下标/维度标注在 PDF 内容流中属于不同坐标（`y0` 偏移）的独立字符块或文本框。
   - `_order_blocks_reading_order`（`extractors.py:212`）按 `(round(float(b[1]), 1), float(b[0]))` 对所有 block 排序：略微偏上的上标 `1`、`2` 或偏下的矩阵维度标注 `m`、`m`、`n`、`d`、`X` 被排到前后独立位置，形成 `1, xi` / `2, ..., xi` 及末尾单独成行的 `m`、`m`、`n`、`d`、`X`。
3. **分块层把“没有空行的页面按单行拆碎”再以 `\n` 拼回**：
   - `split_markdown_blocks`（`markdown_blocks.py:67, 112-115`）：只要整页不含空行，就退化为**逐行成块**；即便有空行，块内也原样保留全部 `\n`。
   - `merge_isolated_short_snippets`（`material_chunking.py:393`）把合并的短块用 `"\n"` 硬连接，使碎行永远带 `\n` 落库。
4. **前端逐 `\n` 生成 `<br>`**：
   - `parseRichContent` → `buildMultilineChildren`（`miniprogram/src/utils/richText.ts:215-222`）把每个 `\n` 渲染为 `<br>`，在手机小屏上将所有物理折行和孤立字母直接展示为碎片。

#### 现象 3：数学符号乱码（`ħx1, ħx2, ..., ħxm`）
1. **PDF 子集字体的异常 `/ToUnicode` 映射**：
   - PPT/Word/LaTeX 导出的 PDF 常将花括号 `{` 或矢量符号字形编进子集字体；当该字体缺少 `/ToUnicode` 或存在**错误映射的 `/ToUnicode` CMap** 时，PyMuPDF/pypdf 抽出的 `{` 变成 Unicode `U+0127`（`ħ`，Latin Extended-A），把 `{x_1, x_2, ..., x_m}` 抽成了 `ħx1, ħx2, ..., ħxm`。
2. **后端四重检测门禁全部漏判（False Negative），导致 VLM/OCR+LLM 修复通道被完全绕过**：
   - **字体检查漏判**（`_pymupdf_page_lacks_tounicode`，`extractors.py:245-262`）：仅匹配 7 个 `_SYMBOL_FONT_MARKERS` 子串且严格要求 `ToUnicode == "null"`。若字体名不在白名单内（如 `Cambria`/`Calibri`/`TimesNewRoman`/自定义子集名）或字体**自带了错误映射的 `/ToUnicode` 表**（非 `null`），均返回 `False`。
   - **符号乱码检测漏判**（`detect_symbol_garble`，`ocr_quality.py:336-378`）：只检测 ASCII 符号簇 `[!"#$%&'*=?@^~]`、希腊字母粘连与西里尔字母 `[\u0400-\u04ff]`。`ħ`（`U+0127`）属于 **Latin Extended-A（`\u0100-\u017f`）**，既不在西里尔区也不在希腊/ASCII 符号区，直接漏过。
   - **数学排版损坏检测漏判**（`detect_broken_math_layout`，`ocr_quality.py:401-440`）：`_is_formula_fragment_line` 要求单行 `<= 8` 字符且含数字/`_MATH_SYMBOL_CHARS`/希腊字母；第 5 页的 `ħx1, ħx2, ..., ħxm`（19 字符）、`2, ..., xi`（10 字符）、`m`/`n`/`d`/`X`（不含数字和运算符）均不符合条件，碎行占比低于 `0.45`，判定为 `False`。
   - **结果**：第 5 页 `page.needs_repair` 为 `False`，`_page_needs_vlm`（`_material_pipeline.py:430-432`）返回 `False`，即使线上已配置并开启 `SiliconFlow VLM`，也**不会**渲染第 5 页截图送 VLM 转录，而是直接返回原始乱码文本。
3. **前端乱码兜底提示同样漏判**：
   - `isGarbledSnippetText`（`miniprogram/src/utils/richText.ts:410-428`）只匹配 `[!"#$%&'*=?@^~]` 符号簇，无法识别 `ħ`（`\u0100-\u017f`）或碎行，因此不触发提示框而直接渲染乱码。

---

## Files Found

| Path | Role |
| --- | --- |
| `miniprogram/src/subpackages/material/components/KnowledgeSnippetModal.vue` | “查看教材原文依据”弹窗 UI、乱码判断分流与 `RichContent` 渲染（`:82-120, 192`） |
| `miniprogram/src/subpackages/material/pages/course/index.vue` | 讲义详情页宿主，绑定考点列表与 `KnowledgeSnippetModal`（`:20-48`） |
| `miniprogram/src/subpackages/material/composables/useCourseDetail.ts` | 点击考点拉取详情与切片状态编排（`:192-207`） |
| `miniprogram/src/stores/material.ts` | 调用 `apiGetKnowledgePointSnippets` 加载切片（`:107-119`） |
| `miniprogram/src/api/modules/knowledge.ts` | 请求 `GET /knowledge/${id}/snippets`（`:32-37`） |
| `miniprogram/src/api/adapters/knowledge.ts` | `adaptPointSourceList` / `adaptKnowledgeSnippet` 切片透传与页码兜底（`:134-160`） |
| `miniprogram/src/components/RichContent.vue` | 小程序 `<rich-text>` 富文本封装（`:1-44`） |
| `miniprogram/src/utils/richText.ts` | `buildMultilineChildren` 将 `\n` 转为 `<br>`（`:215-222`）；`isGarbledSnippetText` 仅检 ASCII 符号簇（`:410-428`） |
| `miniprogram/src/subpackages/material/components/QuestionPreviewCard.vue` | 题目卡片内 `source_quote` 展示与乱码提示（`:61-67, 112`） |
| `miniprogram/src/components/CoachMessageList.vue` | AI 助教引用讲义切片 `msg.sources` 展示（`:52-60`） |
| `backend/app/api/v1/knowledge.py` | `GET /knowledge/{id}/snippets` 反向溯源接口（`:110-138`） |
| `backend/app/services/knowledge.py` | LLM 抽取知识点并绑定 `KnowledgePointSnippet`（`:138-500`）；`get_snippets_for_point` 反向查询（`:626-644`） |
| `backend/app/repositories/knowledge.py` | `get_snippets_for_point` 按 `snippet_index` 查库返回关联切片（`:286-313`） |
| `backend/app/schemas/knowledge.py` | `SnippetSourceResponse` 序列化 `page_index`/`chapter_title`/`content`（`:86-138`） |
| `backend/app/services/question.py` | `_retrieve_and_gate_snippets`（`:213-325`）、`attach_source_snippets`（`:1233-1260`）、`ask_scoped_coach`（`:1735-1816`） |
| `backend/app/services/_question_generation.py` | `aggregate_snippet_context` 切片上下文聚合（`:122-162`） |
| `backend/app/services/source_snippets.py` | `build_source_snippet_map` 题目/练习共享切片装配（`:17-68`） |
| `backend/app/integrations/llm/coach_graph.py` | Adaptive+Corrective RAG 图：`retrieve_and_rerank`、邻接扩展、`verify_citations`（`:290-629`） |
| `backend/app/integrations/search/pgvector.py` | pgvector 向量粗排 + 全库 `ILIKE` 召回 + BM25/RRF 融合 + `fetch_neighbor_snippets`（`:133-384`） |
| `backend/app/integrations/search/_neighbors.py` | 同版本同页 `snippet_index ± window` 邻接切片筛选（`:32-91`） |
| `backend/app/integrations/rerank/siliconflow.py` | SiliconFlow `/rerank` 精排与降级逻辑（`:136-172`） |
| `backend/app/core/algorithms/search.py` | 混合分词（含希腊字母/LaTeX 命令）与平滑 BM25（`:20-163`） |
| `backend/app/core/algorithms/text_excerpt.py` | 摘录安全裁剪与邻接去重拼接（`:98-184`） |
| `backend/app/api/v1/materials.py` | `POST /materials/{material_id}/parse` 解析触发入口（`:458-500`） |
| `backend/app/services/material.py` | `_extract_source_content`（`:370-430`）与 `parse_material_pipeline`（`:460-616`） |
| `backend/app/services/_material_pipeline.py` | `_page_needs_vlm`（`:430-432`）、`transcribe_dirty_pages_with_vlm`（`:435-487`）、`repair_garbled_pdf_pages`（`:490-537`）、`prepare_material_snippets`（`:553-597`） |
| `backend/app/core/extractors.py` | PyMuPDF `get_text("blocks")` 抽取、阅读排序、ToUnicode 字体检测、pypdf 降级（`:78-344, 510-535`） |
| `backend/app/core/algorithms/ocr_quality.py` | `detect_symbol_garble`（`:336-378`）与 `detect_broken_math_layout`（`:411-440`） |
| `backend/app/core/algorithms/markdown_blocks.py` | `split_markdown_blocks` 块划分（`:49-119`） |
| `backend/app/core/algorithms/material_chunking.py` | `split_material_into_snippets` 与 `merge_isolated_short_snippets`（`:376-629`） |
| `backend/app/models/material.py` & `knowledge.py` | `MaterialSnippet`（含 `vector(1024)` HNSW）、`KnowledgePoint`、`KnowledgePointSnippet` 表结构 |
| `backend/app/container.py` & `integrations/container.py` | `AppContainer` 与 `ProviderRegistry` 装配 VLM/OCR/Rerank/Search 适配器 |

---

## Relevant `.trellis/spec/` Files

- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/logging-guidelines.md`
- `.trellis/spec/frontend/index.md`
- `.trellis/spec/frontend/component-guidelines.md`
- `.trellis/spec/frontend/api-payload-contracts.md`
- `.trellis/spec/frontend/network-contract.md`
- `.trellis/spec/frontend/quality-guidelines.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`
- `.trellis/spec/guides/code-reuse-thinking-guide.md`

---

## Caveats / Open Questions

1. **资料入库时间与“重新解析”状态未知**：截图中的资料可能解析于 `fe04fbc`（PyMuPDF + VLM）之前；但如第 4 节分析所示，**即使使用当前最新代码重新解析同一份 PDF**，第 3/4 页（低字符数含标题）与第 5 页（`ħ` 属于 Latin Extended-A、碎行占比未达阈值且 ToUnicode 非 null）仍会命中检测盲区并绕过 VLM，继续产出完全相同的碎片与 `ħx1` 乱码。
2. **低文本量/图主导页的 VLM 触发边界**：若将“低文本量（如 `valid_char_count < 40`）或包含大面积嵌入位图/矢量公式的页面”纳入 `_page_needs_vlm` 路由，需评估纯封面/目录/过渡页触发 VLM 的额外耗时与成本，以及 VLM 转录为空/纯装饰页时如何避免生成“基本概念”孤立短切片。
3. **PDF 段落重连与 Markdown 兼容性**：修复中文/英文 PDF 视觉硬折行时，须注意不能把 Markdown 标题、列表项（`- `/`1.`）、围栏代码块、GFM 表格或 `$$...$$` 多行公式错误拼接成一行；而在切片落库后，已存量坏切片仍需引导或批量触发 `force=true` 重新解析才能刷新。
