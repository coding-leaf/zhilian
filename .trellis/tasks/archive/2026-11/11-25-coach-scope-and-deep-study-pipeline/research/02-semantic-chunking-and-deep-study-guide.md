# Research: PDF/PPT 语义化重建切片与两阶段考前精讲笔记架构设计

- **Query**: 深度调查 PDF/PPT 切片碎裂与知识点总结过浅的根本架构缺陷，结合真实线上模型配置（`deepseek-flash` + `PaddlePaddle/PaddleOCR-VL-1.5` + `BAAI/bge-m3` + `baidu OCR`，宿主机 2 vCPU / 1.7 GiB RAM），设计「PaddleOCR-VL-1.5 + 小模型语义打标切片」与「收敛考点树 + 懒生成永久缓存的考前精讲级知识点笔记」完整方案。
- **Scope**:
  - 后端提取与切片：`backend/app/core/extractors.py`、`backend/app/core/algorithms/{ocr_quality,markdown_blocks,material_chunking,document_denoising}.py`、`backend/app/services/{_material_pipeline,material}.py`、`backend/app/integrations/llm/{openai,factory,agent_graph}.py`、`backend/app/core/config.py`
  - 后端知识树与异步作业：`backend/app/services/knowledge.py`、`backend/app/core/algorithms/{knowledge_tree,knowledge_quality}.py`、`backend/app/models/knowledge.py`、`backend/app/schemas/knowledge.py`、`backend/app/api/v1/knowledge.py`、`backend/app/worker.py`、`backend/migrations/versions/0011_*.py` & `0014_*.py`
  - 前端展示与交互：`miniprogram/src/subpackages/material/{pages/course/index.vue,components/KnowledgeSnippetModal.vue}`、`miniprogram/src/components/RichContent.vue`、`miniprogram/src/utils/{richText.ts,request.ts,requestError.ts}`、`miniprogram/src/stores/backgroundTask.ts`、`miniprogram/src/pages.json`
- **Date**: 2026-11-25

---

## 一、真机图 2 精确代码根因：为何无 `☒` 乱码的第 7 页被劈成 3 块且章节名变成 `ω^T x_i + b` / `-ω^T x_i + b`

经过逐行追踪 PDF 解析 → VLM 触发 → 分块判题 → 切分合并的完整调用链，真机图 2 暴露的不是单一正则漏洞，而是 **5 个环节串联放大** 的确定性因果链（并额外发现了线上 `PaddleOCR-VL-1.5` 的隐藏协议错配风险）。

### 1.1 五步精确因果链（file:line 取证）

1. **PyMuPDF 块级抽取将二维公式拆成孤立 `\n\n` 块**
   - `backend/app/core/extractors.py:290-316`（`_pymupdf_page_text_and_blocks`）：调用 `page.get_text("blocks")` 后按坐标排序，将每个独立文本块以 `"\n\n".join(parts)` 拼接。
   - 在 PPT 导出 PDF 中，二维分式/分段函数（如 SVM 几何间隔或分段边界条件）的分子、分母与符号项（`ω^T x_i + b`、`-ω^T x_i + b`）各自位于独立的 PDF 文本对象/文本框内，因此输出文本中它们前后被 `\n\n` 隔开，成为**独立文本块**。

2. **第 7 页在 `_page_needs_vlm` 全部 4 条路由条件上同时脱靶，完全绕过 `PaddleOCR-VL-1.5`**
   - 路由入口：`backend/app/services/_material_pipeline.py:454-461`（`_page_needs_vlm`）：
     ```python
     return (
         page.needs_repair
         or page.needs_visual_ocr
         or page.has_formula_visual_risk
         or not page.text.strip()
     )
     ```
   - 逐条核对第 7 页（现代字体导出、无 `☒`、有中文讲解 + 2D 分式/分段公式）为何全部为 `False`：
     - `lacks_tounicode_symbol_font`（`extractors.py:325-342`）：现代 PPT/LaTeX 字体（Cambria Math / Times / SimSun 等）含合法 `/ToUnicode` 表，希腊字母 `ω` 能正常解出，**返回 `False`**。
     - `has_symbol_garble`（`ocr_quality.py:407-453`）：无 `☒`/`\ufffd`/PUA/ASCII 符号簇/希腊拉丁粘连，**返回 `False`**。
     - `has_broken_math_layout`（`ocr_quality.py:480-591`）：
       - `_is_formula_fragment_line`（`ocr_quality.py:480-491`）硬限制 `len(line) <= 8`（`_FORMULA_FRAGMENT_MAX_LINE_CHARS`），而 `ω^T x_i + b`（11 字符）和 `-ω^T x_i + b`（12 字符）**长度超 8 直接不计为公式碎片**；
       - 即使含少量短行，整页触发需要满足「`non_code_lines >= 6` 且短公式行占比 `> 45%`」或「连续 `>= 3` 个单字母行 + 悬空行」（`ocr_quality.py:577-589`）。图文混排的中文 PPT 讲义页占比远低于 45%，**返回 `False`**。
     - `needs_visual_ocr`（`extractors.py:125, 223`）：要求 `non_ws_count < 60`（`_VISUAL_OCR_MAX_VALID_CHARS = 60`）。第 7 页含完整中文讲解（> 60 字），**返回 `False`**。
     - `has_formula_visual_risk`（`extractors.py:127-128, 381-391`）：要求**同时**包含 `=≤≥∈∑∫≈≠` 且 `len(page.get_drawings()) >= 20`（`_FORMULA_VISUAL_RISK_MIN_DRAWINGS = 20`）。几条分数线/绝对值竖线/括号仅 2~8 条矢量路径，远低于 20，**返回 `False`**。
   - **结论**：当前 VLM 触发器实质上只抓「严重缺字库/全页乱码/少字扫描页/极密矢量图」，对**字库正常但二维数学公式散架的 PPT 讲义页**几乎全漏。

3. **分块与标题误判：`is_heading_block` 将数学表达式直接判为一级章节标题**
   - `_build_pdf_paragraphs_from_classified`（`_material_pipeline.py:583`）调用 `split_markdown_blocks(txt)`（`markdown_blocks.py:92-160`），按空行 `\n\n` 把 `ω^T x_i + b` 和 `-ω^T x_i + b` 切为独立 `block`。
   - `_build_pdf_block_paragraph`（`_material_pipeline.py:634-636`）调用 `is_heading_block(block)`（`_material_pipeline.py:519-560`）：
     ```python
     _PLAIN_HEADING_FORBIDDEN_CHARS: frozenset[str] = frozenset("。！？!?;:，,=$\\|`")
     _PLAIN_LIST_OR_QUOTE_RE = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+|>\s?|```|\|)")
     ```
   - 致命漏网：
     - 禁止字符集里**完全漏掉**了数学运算与符号字符：`+`、`-`、`*`、`/`、`^`、`_`、`(`、`)`、`[`、`]`、`<`、`>`、`≤`、`≥`、`×`、`·`、`‖` 以及希腊字母 `ω/α/λ/Σ`；
     - `_PLAIN_LIST_OR_QUOTE_RE` 仅拦截带空格的列表符 `-\s+`，对负号紧贴变量的 `-ω^T x_i + b` 放行；
     - 长度校验 `2 <= len(stripped) <= 20`（`_material_pipeline.py:552`）恰好把几乎所有独立公式残块全部收入囊中！
   - 于是 `ω^T x_i + b` 和 `-ω^T x_i + b` 双双返回 `is_heading_block(...) == True`，被赋值为 **`is_title=True, title_level=1`**。

4. **切片器吞掉公式正文并强制切断同页合并**
   - `backend/app/core/algorithms/material_chunking.py:707-709`：
     ```python
     if is_title:
         current_chapter_title = _MD_HEADING_PREFIX_RE.sub("", cleaned_text.strip()).strip()
         continue
     ```
     **双重破坏**：① 公式块本身被 `continue` 吞掉，**正文里的公式凭空消失**；② `current_chapter_title` 被覆写为 `ω^T x_i + b`，紧接着又被覆写为 `-ω^T x_i + b`。
   - `backend/app/core/algorithms/material_chunking.py:394-403`（`_same_segment`）：
     ```python
     if left.chapter_title != right.chapter_title or left.doc_type != right.doc_type:
         return False
     ```
     由于第 7 页内连续产出的 3 段正文分别顶着 `<原章节名>`、`ω^T x_i + b`、`-ω^T x_i + b` 三个不同 `chapter_title`，Stage 2 的 `merge_isolated_short_snippets` **绝对拒绝合并它们**！于是第 7 页最终被劈成 3 块支离破碎的短切片，前端溯源卡片右上角就赫然显示章节名 `ω^T x_i + b` 和 `-ω^T x_i + b`。

### 1.2 额外挖出的线上高危隐患：`PaddleOCR-VL-1.5` 的 Prompt/消息格式错配与内存峰值风险

核查 `backend/app/services/_material_pipeline.py:403-516` 与 `backend/app/integrations/llm/openai.py:43-54` 发现两个在全量/高召回启用 `PaddlePaddle/PaddleOCR-VL-1.5` 时必须解决的工程隐患：

1. **Prompt 与消息结构错配（0.9B 专用 OCR VLM vs 通用 VLM）**：
   - 现有 `_transcribe_page_with_vlm`（`_material_pipeline.py:436-446`）发给 VLM 的是：
     - `role="system"`：250 字长中文指令（为 `Qwen2.5-VL-7B-Instruct` 编写）；
     - `role="user"`：经 `openai.py:51-52` 序列化为 `[{"type": "text", "text": "请严格按要求转录第 7 页的全部内容。"}, {"type": "image_url", ...}]`（文本在前、图片在后）。
   - 而线上模型 `PaddlePaddle/PaddleOCR-VL-1.5` 是 **0.9B 专用文档解析 VLM**，其官方 `chat_template` 仅包含单条 `user` 消息、内容顺序为 `[image_url, text]`，且依赖固定的极简英文任务前缀触发对应模式（`"OCR:"` / `"Formula Recognition:"` / `"Table Recognition:"` / `"Chart Recognition:"` / `"Spotting:"`）。给 0.9B 任务前缀模型灌入长中文 system prompt 属于严重 OOD，容易出现输出退化、丢失公式或被服务侧报错后在 `_material_pipeline.py:507-513` 被 `except Exception` 静默吞掉降级。
2. **全页预渲染进内存（1.7 GiB RAM 宿主机 OOM 风险）**：
   - `transcribe_dirty_pages_with_vlm`（`_material_pipeline.py:480-492`）在启动线程池之前，用一个 `for` 循环把**所有脏页**一次性渲染为 PNG 存入 `rendered: dict[int, bytes]`，全部完成才发 HTTP 请求，且整个循环期间无进度回调。
   - 在 `aliyun` 仅 **2 vCPU / 1.7 GiB RAM**（还要同时承载 FastAPI + Worker + Postgres/Redis 或容器开销）下，若 42 页 PPT 大面积命中 VLM，150 DPI 全彩 PNG 每页 300~700 KB，42 页原始 PNG + base64 编码 + PyMuPDF 渲染缓冲峰值可达 60~120 MB，若遇 100 页扫描教材极易触发容器 OOM Kill。

---

## 二、文档视觉重建与语义切片升级方案（基于线上真实配置）

线上配置核实：`ZHILIAN_VLM__MODEL=PaddlePaddle/PaddleOCR-VL-1.5`（SiliconFlow，免费层 ¥0/token，受 RPM/并发限流）+ `ZHILIAN_LLM__MODEL=deepseek-flash`（高速低价思考模型）+ `BAAI/bge-m3`（1024 dim）。

### 2.1 A 部分：视觉重建触发策略升级与 `PaddleOCR-VL-1.5` 工程适配

#### 策略对比

| 方案 | 命中率（含 2D 公式 PPT） | 42 页耗时估算（并发 3~4） | 1.7 GiB RAM 峰值增量 | 风险与结论 |
| --- | --- | --- | --- | --- |
| 方案 1：仅修补现有脏页阈值 | 中（~60%，仍易漏含少量分式的页） | 5~15s | < 10 MB | 仍会有漏网 2D 分式散架 |
| 方案 2：所有 PDF 100% 强制走 VLM | 100% | 30~65s（大 PDF 150 页会超 3min 且触发限流） | 需流式渲染才安全 | 对纯文字教材/论文浪费配额且易撞 SiliconFlow 免费档 RPM |
| **方案 3（推荐）：分层高召回路由（PPT 视觉公式页高召回 + 纯文页免 VLM）** | **~95%+（所有含公式/图表/幻灯片视觉页全进 VLM）** | **15~40s（42 页约命中 22~36 页）** | **< 15 MB（滚动渲染 + JPEG）** | **精度、耗时、限流、内存综合最优** |

#### 推荐设计细节

1. **新增 3 条高精度 VLM 触发信号（落位于 `backend/app/core/extractors.py` + `ocr_quality.py`）**：
   在 `PdfPageExtraction` 上新增轻量诊断字段 `is_slide_layout: bool`（由 `page_width > page_height * 1.15` 判定，16:9 与 4:3 PPT 导出 PDF 100% 命中）与 `has_math_expression_layout: bool`，扩展 `_page_needs_vlm`：
   - **信号 1（PPT 数学/图解页）**：`page.is_slide_layout` 为 True，且满足以下任一：
     - 文本中出现任意希腊字母（`[\u0370-\u03ff]`）或数学算符（`= + - ^ _ ≤ ≥ ≠ ≈ ∈ ∑ ∫ ∏ √ ∞ ‖ ∂ ∇` 中任意 2 个及以上，或含 `^`/`_`/`‖` 等典型公式记号）；
     - 矢量路径 `len(page.get_drawings()) >= 4`（从 20 降至 4，即可抓到哪怕只有两条分数线/一个矩阵括号的页面）或含内嵌位图（排除整页背景模板图后 `>= 1`）。
   - **信号 2（独立公式块 / 2D 分式版面）**：无论横屏竖屏，若页内 PyMuPDF 文本块中存在任一满足「不含中文、字符数 2~45、含希腊字母或数学算符/上下标」的孤立块，或存在两个垂直紧邻（`0 <= b2.y0 - b1.y1 <= 12pt`）且水平中心对齐的短非中文块（典型分子/分母堆叠）→ 直接标 `has_math_expression_layout = True`。
   - **信号 3（原有兜底保留）**：`needs_repair`、`needs_visual_ocr`、空白页。
   - **纯文字页/封面目录页优化**：先对所有页跑轻量模板页初筛（封面/目录/致谢/参考文献页若文字清晰直接跳过 VLM，白省 4~6 次 VLM 调用！）。

2. **VLM 协议适配（`VLMSettings` + `_material_pipeline.py`）**：
   - 在 `backend/app/core/config.py::VLMSettings` 新增：
     - `prompt_style: Literal["auto", "general_markdown", "paddleocr_vl"] = "auto"`
     - `image_format: Literal["jpeg", "png"] = "jpeg"`、`jpeg_quality: int = 85`、`max_image_edge: int = 1440`
   - 在 `_material_pipeline.py` 新增 `_build_vlm_messages(model_name, data_uri, page_number, prompt_style)`：
     - 当 `prompt_style == "paddleocr_vl"` 或 `prompt_style == "auto"` 且 `"paddleocr-vl"` in `model_name.lower()`：
       - **不发送 `system` 角色**；
       - `user` 消息的 `content` 数组顺序调整为 **`[image_url, text("OCR:")]`**（需在 `openai.py::_serialize_message` 支持可选 `image_first: bool = False`，或通过 `LLMMessage` 字段保持对旧 `Qwen2.5-VL` 测试零破坏）。
     - **⚠️ 关键验证前置项（Implementation 前务必用 1 张真实第 7 页截图验证）**：`PaddleOCR-VL-1.5` 原生设计偏向「版面切块后元素级识别」，整页 PPT 喂 `"OCR:"` 在 SiliconFlow 托管端是否稳定输出完整 LaTeX（`$...$`/`$$...$$`）与合理阅读顺序，需上线前抽查 3 页实测；若发现整页 `"OCR:"` 漏标题或输出纯文本公式，则有两个即插即用备选：
       - 备选 A：仍由 `PaddleOCR-VL-1.5` 完成高准确率字符/公式识别（零乱码），交由下游 `deepseek-flash` 语义打标批处理同时把识别出的散落公式还原为标准 `$...$`/`$$...$$` Markdown；
       - 备选 B：将 `ZHILIAN_VLM__MODEL` 切回支持整页 Markdown+LaTeX 的多模态模型（如 `Qwen/Qwen2.5-VL-72B-Instruct` 或 `Qwen/Qwen3-VL-30B-A3B-Instruct`），利用 `prompt_style="general_markdown"` 自动切换。

3. **内存与并发/超时护栏（面向 2 vCPU / 1.7 GiB RAM）**：
   - **滚动批渲染**：将 `transcribe_dirty_pages_with_vlm` 改为按批次（每批 `batch = max_concurrency * 2`，默认 6 页）在主线程串行用 PyMuPDF 渲染 JPEG（最长边 `<= 1440px`，单页 ~80 KB）→ 提交 `ThreadPoolExecutor(max_workers=max_concurrency)` → 本批 `as_completed` 收集结果后立即释放图像字节并上报进度（将原 30%→45% 拆分为逐页线性进度写入 Redis 进度缓存）。
   - **限流与降级**：单页复用 `OpenAICompatibleLLMAdapter` 的 429/5xx 指数退避（`max_retries=2`，`timeout=35.0`）；单页失败绝不中断整份解析，降级使用 PyMuPDF 文本并在语义打标层补救。
   - **42 页耗时与成本估算**：命中 30 页 × 平均 2.8s / 并发 3 ≈ **28 秒**（含 429 抖动约 35~45 秒），远低于 RQ `job_timeout=1800s`；SiliconFlow 免费层费用 **¥0**；峰值内存增量 **< 15 MB**。

---

### 2.2 B 部分：确定性标题止血 + `deepseek-flash` 语义打标与逻辑单元切片

#### 第一道防线：彻底修复 `is_heading_block`（确定性、零成本、离线测试全覆盖）

修改 `backend/app/services/_material_pipeline.py:519-560`：
1. **数学与公式字符黑名单全面封堵**：
   - 任何非 `#` 开头的纯文本块，只要命中以下任一条件，**立即返回 `False`**：
     - 含数学/代码/关系符：`+-*/^_=<>≤≥≠≈∈∉⊂⊃∪∩∑∫∏√∞±×÷·‖|${}[]()\`\\`；
     - 含希腊字母 `[\u0370-\u03ff]` 或数学字母数字符号 `[\U0001d400-\U0001d7ff]`；
     - 不含任何中文且包含单字母变量组合（如 `w^T x + b`、`f(x)`、`y_i`、`min 1/2`）；
     - 以 `-`、`+`、`=`、数字下标或括号开头。
2. **坐标与结构白名单收紧**：
   - 仅允许两类块判为 `is_title=True`：
     - 显式 Markdown 标题（`^#{1,6}\s+`，且剥离 `#` 后同样不满足「纯公式块」条件）；
     - 显式章节/小节模式（如 `第[一二三四五六七八九十\d]+[章节讲篇]`、`\d+(?:\.\d+)*[\s、.]+[\u4e00-\u9fff]`）或位于页面顶部区域（`y0 / page_height <= 0.22`，从 `PageTextBlock` 坐标直接可得！）的纯中文短标题（含至少 2 个汉字且长度 `2..24`）。
3. **防止标题误吞正文**：在 `material_chunking.py:707-709` 仅当 `is_title=True` 且通过上述严格校验时更新 `current_chapter_title`。

#### 第二道防线：引入 `deepseek-flash` 按页滑窗语义打标与逻辑单元切分

在获得「每页干净 Markdown 文本（VLM + PyMuPDF 融合、跨页页眉页脚去噪完成）」之后、执行向量化之前，插入可选的 **Semantic Page Tagger & Unit Chunker** 阶段（落位于 `backend/app/services/_semantic_chunker.py`，纯数据结构与合并算法放 `backend/app/core/algorithms/semantic_chunking.py` 以严格满足 `import-linter` 分层约束！）：

1. **滑窗批处理架构（高吞吐、低输出 Token、不改写无错正文）**：
   - 输入：经过跨页去噪的有序页面序列 `[(page_number, page_text, used_vlm), ...]`。
   - 切批：每批 **8 页**（总字符不超过 8,000 字），向下一批传入上一批末尾的 `last_topic_title` 与前 120 字摘要作为连贯锚点。42 页讲义仅需 **5~6 次调用**。
   - **关键设计——避免整页复述（Zero-Rewrite by Default）**：
     - 如果让 LLM 对每一页都完整重写 `cleaned_markdown`，42 页输出 25,000 字会慢 3 倍且引入删减/幻觉风险。
     - 最优设计：要求 `deepseek-flash` 对每页仅输出轻量元标注：
       ```python
       class PageSemanticAnnotation(BaseModel):
           page_number: int
           topic_title: str              # 2~24字规范主题/章节名，跨页延续同一主题时复用上一页标题
           is_substantive: bool          # False=封面/目录/过渡页/纯致谢/空白习题标题页/纯无文字插图页
           merge_with_prev: bool         # True=与上一页同属一个未完结的定义/推导/例题逻辑单元
           needs_formula_repair: bool    # True=仅当该页未走VLM且存在明显散架公式/残行需要轻修复
           repaired_markdown: str | None # 仅 needs_formula_repair=True 时输出修复后的该页正文，否则为 None
       ```
     - 这样 80%~95% 的页 `repaired_markdown=None`，每批输出仅 **400~800 tokens**，单批耗时 **1.5~3 秒**！
2. **逻辑单元聚合规则（纯函数核 `core/algorithms/semantic_chunking.py`）**：
   - 过滤 `is_substantive == False` 的噪声页（带防空兜底：若全篇被判空则回退保留全部）；
   - 按 `merge_with_prev == True` 且 `topic_title` 一致，将跨页连续推导（如第 6~8 页的 SVM 对偶问题推导）合并为**同一个逻辑单元**，保留精确页码区间 `page_number=6, page_end=8, source_ref="第 6-8 页"`、`chapter_title=topic_title`；
   - 单个逻辑单元长度上限提升至 **`1400` 字符**（原 `DEFAULT_MAX_CHARS = 800` 对含完整推导的数学页偏小，常在公式中间硬拆）；仅超过 `1400` 字符时才调用既有 `split_paragraph_into_ranges`（自动绕过 `$$...$$` 与 Markdown 表格保护区）。
3. **触发边界、性能成本与降级兜底**：
   - **开关与边界**：`ZHILIAN_LLM__SEMANTIC_CHUNKING_ENABLED: bool = True`（当 `llm` 为 `FakeLLMAdapter` 或文档为极短纯文本 `< 3` 页时自动旁路跳过，保证 100% 离线单测速度与确定性）。
   - **并发与耗时**：5~6 批采用顺序或 2 路有限并发（因需传递 `last_topic_title`，推荐 2 阶段：若需要严格跨批 `topic_title` 衔接，串行 6 批 × 2s = **12 秒**；或并行打标后做轻量主题归一化耗时 **5 秒**）。
   - **成本估算**：42 页输入 ~18k tokens + 输出 ~3.5k tokens，`deepseek-flash` 单份资料成本 **< ¥0.02**。
   - **降级兜底**：任一批次 LLM 超时/格式校验失败，仅该批 8 页自动回退至「已修复 `is_heading_block` 的确定性 `split_material_into_snippets`」，绝不导致解析失败。

---

## 三、两阶段「收敛考点树 + 懒生成永久缓存的考前精讲笔记」架构设计

### 3.1 现状根因分析：为什么一章切出 33 个碎考点且总结过浅？

核查 `backend/app/services/knowledge.py`、`knowledge_tree.py`、`knowledge_quality.py` 后，确认有 **4 个互锁的架构硬伤**：

| 根因 | 精确代码位置 | 导致的直接恶果 |
| --- | --- | --- |
| **1. 碎片化小窗分批，缺乏全章视野** | `knowledge.py:68-70, 85-120`（`max_batch_snippets=12`, `max_batch_chars=6000`, `chapter_changed and near_budget` 切批） | 42 页讲义被切成 6~10 个互不统筹的小批次，每批机械产出 4~6 个微考点，叠加即 30~40 个 |
| **2. 质检门禁反过来「惩罚」收敛的 2 层树！** | `knowledge_quality.py:24, 45, 394-412`（`MIN_EFFECTIVE_CHARS_PER_KP=625`、`MAX_LEVEL_2_RATIO=0.60`） | ① 22,000 字切 33 个（666 字/考点）在数量门禁直接满分通过；② **致命反转**：一个干净的 2 层收敛树（如 3 个一级模块 + 10 个二级考点），Level-2 占比 = `10/13 = 76.9% > 60%`，触发 `LAYER_DEGENERATE` 失败并给 LLM 发反馈「请进一步下钻拆分」，**系统亲手逼着模型把 13 个考点拆成 33 个！** |
| **3. 向量去重阈值过严** | `knowledge.py:412-416`（`similarity_threshold=0.92`） | 同属一个考点的「硬间隔最大化」「几何间隔定义」「支持向量条件」余弦相似度仅 0.72~0.85，永远不会被归并 |
| **4. 单次输出 Token 饥饿 + 硬截断** | `knowledge.py:280`（整批共用 `max_tokens=4096`）+ `knowledge_tree.py:20`（`_MAX_CORE_SUMMARY_CHARS=200`） | 1 次调用里 6~8 个考点瓜分 4096 tokens（叠加 JSON 键名与 `deepseek-flash` 思考 token），每个考点仅分到 ~150~250 汉字，且 `core_summary` 超过 200 字还会被代码硬截断！结构上就不可能产出考前精讲 |

---

### 3.2 Stage 1：解析期「全局收敛考点骨架」（目标：40 页讲义 → 8~15 个考试级考点）

将解析期的职责严格收敛为：**建立清晰、不碎、高内聚的 2 层考纲树 + 精准切片映射 + 轻量考前预览卡**，把重度写作卸载到 Stage 2。

1. **全局单次建树（One-Shot Global Outline）+ 超长文档归并（Consolidation Pass）**：
   - `deepseek-flash` 具备大上下文窗口。经过语义切片后的 40~60 页单章讲义，总字符数通常在 **12,000 ~ 26,000 字符**（约 10k~20k tokens）。
   - **常规单章讲义（`total_chars <= 28,000`）**：**不再盲目按 6,000 字切 5 批**，直接一次将全部语义切片（带 `[#snippet_index | 第X-Y页 | topic_title]`）送入 `deepseek-flash`，Prompt 明确预算约束：
     - **树结构**：严格 **2 层清晰树**（Level-1：2~5 个核心知识模块/大主题；Level-2：6~12 个考试级核心考点，总节点数控制在 **8~15 个**；每条 Level-2 考点聚合同一主题下的定义、推导与变式，严禁把单个中间公式或单页 PPT 独立成考点）。
     - **轻量字段**：解析期仅生成 `name`、`parent_temp_id`、`level`、`source_snippet_indices`、`core_summary`（80~160 字直观定位）、`key_takeaways`（2~3 条核心结论句）、`key_formulas`（1~3 条最核心公式）——单次输出仅 ~2,000~3,000 tokens，**1 次 LLM 调用 8~15 秒搞定**！
   - **超长整本书/多章合集（`total_chars > 28,000`）**：按语义大章分批（每批 `<= 16,000` 字）先抽候选，再跑一次极轻量的 **Global Consolidation Pass**（只传候选节点名称 + 摘要 + 切片索引列表），合并近义碎节点并裁剪至合理规模（按每 2,000~2,500 字约 1 个考点的节奏，上限 ~40 个）。
2. **同步修正 `knowledge_quality.py` 门禁（否则新树会被旧门禁打回！）**：
   - **修正 `check_hierarchy_depth`（`knowledge_quality.py:394-412`）**：对干净的 2 层收敛树（`max_depth == 2` 且 `len(levels) <= 25`）豁免 `level_2_ratio <= 0.60` 限制（改为校验 `level_1_count >= 2` 且每个一级节点子节点数 `<= 8`），彻底消除门禁强迫 LLM 拆碎 3 层节点的反效果。
   - **收紧过度拆分红线**：针对单章讲义（`total_snippets >= 20`），将推荐密度区间从 `625~5000` 调整为 **`1000~4500` 字符/考点**（22,000 字单章最多允许 22 个，理想落在 8~15 个），防止模型再吐 33 个碎片。
   - **去重阈值**：向量去重从 `0.92` 下调至 `0.86`，提高同义微考点合并率。
3. **解析总耗时预算（42 页含公式 PPT）**：
   - PyMuPDF + 跨页去噪：< 1s
   - `PaddleOCR-VL-1.5` 高召回视觉重建（30 页，并发 3）：~28s
   - `deepseek-flash` 语义打标（5 批）：~10s
   - `BAAI/bge-m3` 切片向量化（~25 个语义逻辑切片）：~2s
   - Stage 1 全局收敛考点树（1 次 `deepseek-flash`）：~12s
   - **总计：约 50~60 秒**（稳定落在一分钟内，相比之前 6~10 批串行 + 重抽更短，且质量脱胎换骨）。

---

### 3.3 Stage 2：考前精讲笔记（懒生成 + 永久缓存 + 一键整章预热）

#### 3.3.1 数据存储与迁移设计（Alembic `0015`）

**方案对比**：

| 维度 | 方案 A：`knowledge_points` 原表加列（**推荐**） | 方案 B：新建独立表 `knowledge_point_study_guides` |
| --- | --- | --- |
| **关系模型** | 严格 1:1 绑定单个 `KnowledgePoint` | 需外键 + 唯一约束 + 额外 JOIN |
| **重解析版本隔离** | `force=True` 重解析执行 `delete_knowledge_points_by_version`（`knowledge.py:559`）时**自动级联清理旧精讲**，绝无脏缓存残留 | 需靠 `ON DELETE CASCADE`（SQLite 测试中须依赖 `PRAGMA foreign_keys=ON`） |
| **SQLite / PG 兼容** | 完全复用迁移 `0011`（`0011_structured_kp_and_question_jobs.py:20-35`）的 `JSON().with_variant(JSONB, "postgresql")` + `op.batch_alter_table` 模式 | 需多维护 1 张表、1 个 ORM 类、1 组租户索引与迁移测试 |
| **知识树列表查询性能** | 在 `KnowledgeRepository` 树查询中用 `defer(KnowledgePoint.study_guide)`（或 `study_guide.is_not(None)` 投影布尔列 `has_study_guide`），列表接口**零大 JSON 传输开销** | 列表接口需 LEFT JOIN 判断是否存在 |

**最终数据模型变更（`backend/app/models/knowledge.py` + `backend/migrations/versions/0015_kp_study_guide.py`）**：
- `down_revision = "0014_question_collections"`（实测当前 head 为 `0014_question_collections`）。
- 在 `knowledge_points` 表通过 `op.batch_alter_table("knowledge_points")` 新增 3 列：
  1. `study_guide: Mapped[dict[str, Any] | None]` — `JSON().with_variant(JSONB, "postgresql"), nullable=True, default=None`（永久缓存的考前精讲结构化 JSON）；
  2. `study_guide_generated_at: Mapped[datetime | None]` — `DateTime(timezone=True), nullable=True, default=None`（生成时间戳，用于展示与观测）；
  3. `study_guide_version: Mapped[int]` — `Integer, nullable=False, default=0, server_default="0"`（Schema 版本号：`0`=未生成，`1`=v1 精讲格式，未来升级模板时可优雅识别旧版）。
- 补全对称 `downgrade()` 删除上述 3 列，保证通过 `tests/unit/models/test_migration_model_consistency.py` 闸门。

#### 3.3.2 并发点击「单飞防重生成」与短事务边界

遵循 `.trellis/spec/backend/database-guidelines.md` 的 **短事务红线** 与并发安全要求：
1. **分布式单飞锁（Singleflight Lock）**：
   - Key：`zhilian:study_guide:lock:{kp_id}`；
   - Redis 模式（线上）：`redis.set(lock_key, token, nx=True, ex=90)`；Memory/测试模式：进程内 `threading.Lock` 字典按 `kp_id` 串行化；
   - **抢锁成功**：
     1. 短事务只读：查 `KnowledgePoint`（若非 `force` 且 `study_guide is not None` 直接解锁返回缓存）+ 关联的干净 `MaterialSnippet` 列表 + 同章父/兄弟考点名称列表（用于对比表）→ 拷贝为纯内存对象 → 立即 `self.session.rollback()` **释放数据库连接**！
     2. 事务外调 `deepseek-flash` 生成精讲笔记（`timeout=55.0`）。
     3. 重开短事务写回 `study_guide`、`study_guide_generated_at=utcnow()`、`study_guide_version=1` → `self.session.commit()` → Lua 校验 token 释放锁。
   - **抢锁失败（同一考点并发双击或正被整章预热占用）**：
     - 轮询等待（每 `0.5s` 查一次缓存，最多等待 `25s`）；一旦首飞落库立即返回已持久化结果；超时返回 `202 Accepted`（`{status: "generating"}`），前端继续短轮询 `GET /knowledge/{kp_id}/study-guide`，绝不触发重复 LLM 计费。

#### 3.3.3 考前精讲笔记内容 Schema（单考点独享充足 Token 预算）

**针对 `deepseek-flash` 思考模型的 Token 关键提醒**：
- 如 `backend/app/integrations/llm/agent_graph.py:84-91` 实测注释所示，`deepseek-flash` 为 thinking 模型，**`tool_choice` 必须保持 `"auto"`**（不可设 `"required"`），且 `max_tokens` 是 **`reasoning_content` + 最终 JSON 输出的共享上限**！
- 若给 `max_tokens=4096`，当思考消耗 1,800 tokens 时，正文仅剩 2,200 tokens，容易在 2 道例题处截断导致 JSON 解析失败。
- **推荐配置**：`LLMOptions(temperature=0.25, max_tokens=6144, timeout=55.0)`（并在 Prompt 中明确控制精讲正文约 **1,400~2,400 汉字**，确保思考 + 正文永不截断，响应时间稳定在 **15~28 秒**）。

**强类型 Pydantic 输出结构（`StudyGuidePayload`）**：

```python
class StudyGuideSymbol(BaseModel):
    symbol: str          # LaTeX 符号，如 "$w$"
    meaning: str         # 物理/数学含义，如 "超平面法向量，决定决策边界方向"
    note: str = ""       # 维度/取值范围或易错提示，如 "$w \in \mathbb{R}^d$"

class StudyGuideDerivationStep(BaseModel):
    step_title: str      # 步骤标题，如 "第 2 步：构造拉格朗日函数并求偏导"
    formula: str = ""    # 对应展示公式 "$$...$$"（纯概念类可空）
    explanation: str     # 讲清"为什么这一步成立"与关键代数变换

class StudyGuideWorkedExample(BaseModel):
    title: str           # 例题标题，如 "典型例题 1：由支持向量反求超平面与几何间隔"
    question_type: str   # 题型标签：计算题 / 推导证明 / 概念辨析 / 综合应用
    problem: str         # 完整题干（紧扣讲义原型或同构变式，含必要数值/条件）
    solution_idea: str   # 解题切入点与标准套路（1~2 句）
    solution_steps: list[str]  # 分步标准解答（含完整公式演算）
    final_answer: str    # 明确结论/最终答案

class StudyGuideComparison(BaseModel):
    target_concept: str  # 相邻易混概念（优先取同章其他考点名）
    similarities: str    # 共同点
    differences: str     # 本质区别（定义/公式/条件）
    exam_distinction: str # 考场快速区分口诀或判别依据

class StudyGuidePitfall(BaseModel):
    mistake: str         # 考场常见错误做法/误解
    why_wrong: str       # 错因剖析
    correction: str      # 正确做法与记忆锚点

class StudyGuideContent(BaseModel):
    schema_version: int = 1
    exam_positioning: str          # 1. 直观定位与考法（解决什么问题 + 本章地位 + 常见考察形式，严禁捏造考频百分比）
    core_definition: str           # 2. 完整严谨定义 + 通俗直觉类比（Markdown + LaTeX）
    symbol_table: list[StudyGuideSymbol]           # 3. 核心符号速查表（无公式类可空）
    key_formulas: list[str]                        # 4. 核心结论公式组（标准 $$...$$）
    derivation_steps: list[StudyGuideDerivationStep] # 5. 逐步推导 / 算法流程链
    worked_examples: list[StudyGuideWorkedExample] # 6. 1~2 道典型例题与标准解题套路
    comparisons: list[StudyGuideComparison]        # 7. 相邻易混概念对比（前端渲染为对比表/卡片）
    pitfalls: list[StudyGuidePitfall]              # 8. 考场高频避坑（误区→根因→正解）
    memory_anchors: list[str]                      # 9. 考前 30 秒速记锚点 / 口诀（2~4 条）
```

> **防幻觉红线**：System Prompt 明确约束——所有核心定义、定理、符号体系必须严格忠实于传入的本考点原文切片；例题须基于讲义原题或标准同构教学例题，严禁杜撰原文没有的定理编号或「近 5 年必考 85%」类虚假考频标签。

#### 3.3.4 API 契约与一键整章后台预热（复用既有 RQ 队列）

所有新增端点均位于 `backend/app/api/v1/knowledge.py`（及 `materials.py`），严格声明为普通 `def`（禁止 `async def` 阻塞事件循环）：

| 方法与路径 | 请求体 / 参数 | 响应契约 | 说明 |
| --- | --- | --- | --- |
| `GET /api/v1/knowledge/{kp_id}/study-guide` | — | `{knowledge_point_id, status: "empty"\|"generating"\|"ready", study_guide: StudyGuideContent\|null, generated_at: datetime\|null}` | 纯读缓存 + 查单飞锁状态；毫秒返回，零阻塞 |
| `POST /api/v1/knowledge/{kp_id}/study-guide/generate` | `{force?: bool = false}` | 同上（同步返回 `ready`，若抢锁超时返 `202` + `status: "generating"`） | 懒生成入口；命中缓存直接秒返；传 `force=true` 强制重生成 |
| `POST /api/v1/materials/{material_id}/study-guides/prewarm` | `{version_id?: uuid, force?: bool = false}` | `202 Accepted`: `{material_id, version_id, status: "queued"\|"running"\|"completed", total_kps, ready_kps}` | 一键预生成整章全部考点精讲；若全部已就绪直接返回 `completed` 不入队 |
| `GET /api/v1/materials/{material_id}/study-guides/status` | `?version_id=...` | `{material_id, version_id, status: "idle"\|"queued"\|"running"\|"completed"\|"partial_failed", total_kps, ready_kps, failed_kps, current_kp_name}` | 前端轮询整章预热进度 |
| `GET /api/v1/materials/{material_id}/knowledge-tree`（增量扩展） | 原参数不变 | `KnowledgeTreeNodeResponse` 新增 `has_study_guide: bool = False` | 课程页列表直接展示「已精讲」角标，**不返回 `study_guide` 正文** |

**整章预热 RQ 任务设计（零新增 Job 表，复用现有基础设施）**：
- 在 `backend/app/worker.py::REGISTERED_TASKS` 注册 `"prewarm_study_guides"`，投递到普通优先级队列 **`zhilian`**（不抢占 `zhilian_high` 的资料解析与实时判题）。
- **状态存储**：真实已完成计数由数据库 `COUNT(id)` / `COUNT(study_guide)` 提供（重启不丢、天然一致）；瞬态状态（`status=queued/running/partial_failed`、`current_kp_name`、`failed_kps`）写入 Redis Hash `zhilian:study_guide:prewarm:{version_id}`（TTL 24h），完全复用 `resolve_progress_redis_client` 模式（`_material_pipeline.py:69`）。
- **逐考点独立短事务执行**：Worker 拉取当前版本下 `study_guide IS NULL`（或 `force=True` 时全量）的叶子/核心考点列表（8~15 个），按 `sort_order` 逐个调用同一套 `generate_study_guide`（天然共享单飞锁：即使用户中途点开某个考点，也不会重复生成！），每完成 1 个立刻 `commit` 并更新 Redis 进度。12 个考点串行/2 路并发总耗时约 **2~3 分钟**，单考点失败仅记入 `failed_kps` 继续下一个，用户可随时关闭小程序后台跑完。

#### 3.3.5 前端展示与交互设计（独立精讲页 vs 弹窗评估）

**评估结论：新建独立考前精讲详情页 `miniprogram/src/subpackages/material/pages/knowledge/index.vue`（强烈推荐），不再把 2,000 字精讲硬塞进 `KnowledgeSnippetModal.vue`**。

核心依据：
1. **单文件行数红线**：`KnowledgeSnippetModal.vue` 现已 **249 行**（项目规范单 `.vue` 文件硬上限 `<= 300` 行），无空间承载精讲笔记 + 例题折叠 + 对比表 + 懒生成骨架屏 + 重新生成状态机。
2. **阅读与交互体验**：1,500~2,500 字深度笔记包含多层公式、符号表、逐步推导、1~2 道长例题与对比表；半屏 Bottom Sheet（~78vh）内嵌 `scroll-view` 视野局促、误滑易关闭，而独立详情页（注册在既有 `subpackages/material` 分包下，**零主包体积增长**）可使用原生页面流滚动、吸顶分段 Tab（「核心精讲 / 典型例题 / 对比避坑 / 原文溯源」）、更宽松的公式横向滚动与 `RichContent.vue`（已内置 KaTeX AST + GFM 表格渲染，`miniprogram/src/utils/richText.ts:22`）。
3. **组件拆分（确保所有新 SFC `<= 250` 行）**：
   - `miniprogram/src/subpackages/material/pages/knowledge/index.vue`（页面壳 + 顶部标题/掌握度/面包屑 + 分段导航 + 底部固定安全区底栏「针对此考点出题 / 向 AI 助教追问 / 重新生成」）；
   - `miniprogram/src/subpackages/material/components/StudyGuideNoteView.vue`（定位 + 核心定义 + 符号速查表 + 核心公式 + 逐步推导）；
   - `miniprogram/src/subpackages/material/components/StudyGuidePracticeView.vue`（1~2 道典型例题——支持「先看思路 / 展开完整解答」交互防直接剧透！+ 相邻概念对比卡片/表 + 考场避坑 + 记忆锚点）；
   - 复用现有 `KnowledgeEvidenceList.vue`（展示干净合并后的原文溯源切片）。
4. **交互与状态机 UX**：
   - **进入考点页零白屏**：路由传 `kp_id` + `material_id`，页面先秒显 Stage 1 的 `core_summary` + 原文切片，同时调 `GET /knowledge/{kp_id}/study-guide`：
     - `ready` → 直接渲染永久缓存的完整精讲；
     - `empty` → 自动发起 `POST /knowledge/{kp_id}/study-guide/generate`（传 `timeout: LONG_REQUEST_TIMEOUT_MS` 即 60s，见 `miniprogram/src/utils/requestError.ts:28`），展示温润学术风加载卡片（「正在为你深度拆解本考点推导、典型例题与易错对比，首次生成约 15~25 秒，生成后永久秒开」）；
     - `generating`（正好赶上整章预热正在生成此考点）→ 每 2.5s 轮询 `GET /knowledge/{kp_id}/study-guide` 直至 `ready`；
     - 失败 → 展示具体错误与「重新生成」按钮，不丢失 Stage 1 摘要与原文切片。
   - **课程详情页（`course/index.vue`）一键整章预热**：
     - 在考点列表顶部增加轻量卡片条：「考前精讲笔记 · 已生成 X/N 项」+ 按钮「一键生成全章精讲」（全部就绪时切换为「全章精讲已就绪」）；
     - 点击后调 `POST /materials/{id}/study-guides/prewarm`，并注册到 `useBackgroundTaskStore`（`miniprogram/src/stores/backgroundTask.ts:33` 扩展 `kind: 'material_parse' | 'question_job' | 'study_guide_prewarm'`），借 `BackgroundTaskBar` 跨页追踪进度。
   - **微信兼容红线**：新页面注册进 `miniprogram/src/pages.json` 的 `subPackages[0]`（`subpackages/material`），跳转统一走 `safeNavigateTo`，严禁 `PATCH` / 动态 `import()` / 裸 Hex / Emoji，底部固定栏加 `env(safe-area-inset-bottom)`。

---

## 四、Files Found 清单

| Path | Role |
| --- | --- |
| `backend/app/core/extractors.py` | PyMuPDF/pypdf 页级抽取、缺字库检测、`_pymupdf_page_has_formula_visual_risk`（阈值 20 路径过严）、`render_pdf_page_png` |
| `backend/app/core/algorithms/ocr_quality.py` | `detect_symbol_garble` 与 `detect_broken_math_layout`（短行 <= 8 字符且需占比 > 45%，导致第 7 页漏检） |
| `backend/app/core/algorithms/markdown_blocks.py` | `split_markdown_blocks` 与 `unwrap_pdf_visual_line_breaks` |
| `backend/app/core/algorithms/material_chunking.py` | `split_material_into_snippets`（吞掉 `is_title` 并覆写 `chapter_title`）、`_same_segment`（不同 `chapter_title` 禁合并） |
| `backend/app/services/_material_pipeline.py` | `_page_needs_vlm`、`_transcribe_page_with_vlm`（长中文 system prompt 与 PaddleOCR-VL-1.5 错配）、`transcribe_dirty_pages_with_vlm`（全页预渲染进内存）、`is_heading_block`（漏禁 `+ - ^ _ 希腊字母` 导致公式变标题） |
| `backend/app/integrations/llm/openai.py` | OpenAI 兼容多模态序列化（`_serialize_message` 固定 text 在前、image_url 在后） |
| `backend/app/integrations/llm/agent_graph.py` | LangGraph 结构化输出引擎（已实测 `deepseek-flash` 仅支持 `tool_choice="auto"`） |
| `backend/app/core/config.py` | `VLMSettings`（默认模型/DPI/并发/超时配置） |
| `backend/app/services/material.py` | `parse_material_pipeline`（全链路阶段编排、短事务提交点、Redis 进度上报） |
| `backend/app/services/knowledge.py` | `KnowledgeService`（小窗分批抽取、`max_tokens=4096` 共享、去重 0.92、`delete_knowledge_points_by_version`） |
| `backend/app/core/algorithms/knowledge_tree.py` | `ExtractedKnowledgeItem`、`_MAX_CORE_SUMMARY_CHARS=200`、拓扑自愈 |
| `backend/app/core/algorithms/knowledge_quality.py` | 知识点质检门禁（`MIN_EFFECTIVE_CHARS_PER_KP=625`、`MAX_LEVEL_2_RATIO=0.60` 误杀 2 层收敛树） |
| `backend/app/models/knowledge.py` | `KnowledgePoint`（JSON/JSONB 变体列先例）与 `KnowledgePointSnippet` |
| `backend/app/schemas/knowledge.py` | `KnowledgeTreeNodeResponse`、`KnowledgePointDetailResponse` 等 DTO |
| `backend/app/api/v1/knowledge.py` | 知识点路由（全为普通 `def`） |
| `backend/app/worker.py` | RQ `REGISTERED_TASKS` 注册表与 `zhilian_high` / `zhilian` 双队列 |
| `backend/migrations/versions/0011_structured_kp_and_question_jobs.py` | SQLite/PG `JSONB` `batch_alter_table` 迁移样板 |
| `backend/migrations/versions/0014_question_collections.py` | 当前 Alembic head（`down_revision` 锚点） |
| `miniprogram/src/subpackages/material/pages/course/index.vue` | 资料详情页（考点列表与弹窗/跳转入口） |
| `miniprogram/src/subpackages/material/components/KnowledgeSnippetModal.vue` | 当前 249 行半屏考点弹窗（接近 300 行上限，不适合承载 2,000 字精讲） |
| `miniprogram/src/components/RichContent.vue` & `miniprogram/src/utils/richText.ts` | 零外部依赖 KaTeX AST + Markdown 表格富文本渲染底座 |
| `miniprogram/src/utils/requestError.ts` | `LONG_REQUEST_TIMEOUT_MS = 60000`（对齐同步精讲懒生成超时） |
| `miniprogram/src/stores/backgroundTask.ts` | 全局后台任务条状态管理（可扩展 `study_guide_prewarm`） |
| `miniprogram/src/pages.json` | 主包/分包路由注册表 |

---

## 五、Relevant `.trellis/spec/` Files（供 `implement.jsonl` / `check.jsonl` 批量编入）

- `.trellis/spec/backend/directory-structure.md`（6 条 import-linter 分层红线、同步 `def` 路由红线、RQ Worker 注册与重建规范）
- `.trellis/spec/backend/database-guidelines.md`（短事务/Commit-First 铁律、Alembic 迁移一致性闸门、SQLite `batch_alter_table` 与 `JSONB` 变体写法、CAS `.rowcount` 的 `CursorResult` 兜底）
- `.trellis/spec/backend/error-handling.md`（5 位错误码体系）
- `.trellis/spec/backend/quality-guidelines.md`（`max-complexity = 15`、mypy strict、覆盖率 >= 80%）
- `.trellis/spec/backend/logging-guidelines.md`（脱敏日志与 8 要素指标）
- `.trellis/spec/frontend/directory-structure.md`（分包路由与单文件 `<= 300` 行约束）
- `.trellis/spec/frontend/component-guidelines.md`（自定义 SFC、设计 Token、零 Emoji/裸 Hex）
- `.trellis/spec/frontend/network-contract.md`（`LONG_REQUEST_TIMEOUT_MS`、轮询与错误分类）
- `.trellis/spec/frontend/mp-weixin-compatibility.md`（禁 `PATCH`、禁动态 `import()`、`safeNavigateTo`、`env(safe-area-inset-bottom)`）
- `.trellis/spec/frontend/type-safety.md`（`Wire*` 归一化与零 `any`）
- `.trellis/spec/guides/cross-layer-thinking-guide.md`（跨前后端契约同步检查）

---

## 六、Caveats & Open Questions（主会话立即可决策项）

1. **⚠️ `PaddleOCR-VL-1.5` 整页 PPT 实测验证（高优）**：线上已配 `PaddlePaddle/PaddleOCR-VL-1.5`，但该模型是 0.9B 任务前缀模型（官方仅用 `"OCR:"` / `"Formula Recognition:"` 且无 `system` prompt）。建议实施前先用真实第 6~7 页 PNG 跑一次单页脚本对比：
   - ① 无 system prompt + `[image_url, "OCR:"]` 在 SiliconFlow 上的真实输出（确认是否保留完整 LaTeX 与阅读顺序）；
   - ② 若整页 `"OCR:"` 输出纯文本/轻度乱序，由后续 `deepseek-flash` 语义打标批处理顺带完成 LaTeX 规整（零额外模型切换成本）vs 改配 `Qwen2.5-VL-72B` 对比。
2. **现有质检单元测试回归**：修改 `knowledge_quality.py::check_hierarchy_depth`（豁免干净 2 层收敛树的 `level_2_ratio > 0.60` 误杀）与 `MIN_EFFECTIVE_CHARS_PER_KP` 时，需同步更新 `backend/tests/unit/core/algorithms/test_knowledge_quality.py` 中围绕 625 / 0.60 边界的旧断言。
3. **老资料向后兼容**：线上已解析的旧版本资料仍停留在旧切片与 33 个旧考点；用户无需强制重解析即可对旧考点点击「生成考前精讲」（懒生成天然兼容任何现有 `KnowledgePoint`），若想获得干净切片与收敛的 8~15 个考点树，点击「重新解析」即可无缝切到新管道并自动清空旧精讲缓存。
4. **部署顺序铁律**：发布含迁移 `0015_kp_study_guide` 与新 RQ 任务 `prewarm_study_guides` 时，务必按 `uv run alembic upgrade head` → 重建并重启 `api` + `worker` 容器的顺序执行，避免 `UndefinedColumn` 500 或 Worker 报未知任务名。
