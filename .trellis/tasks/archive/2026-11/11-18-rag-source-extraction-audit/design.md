# Design: 修复 RAG 原文提取展示与题目问答上下文链路

## 1. Architecture & Layer Boundaries

严格遵循 `backend/pyproject.toml` import-linter 分层约束（`core` → 纯算法/协议，不依赖 `services`/`integrations`/`models`；`services` 编排领域与存储；`api` 处理 HTTP Schema；`miniprogram` 通过 `api/modules/*` + `types/*` + `composables/*` 与后端对齐）：

```
┌──────────────────────────────────────────────────────────────────────┐
│ Track A: RAG 解析 / 分块 / 原文依据展示                                │
│                                                                      │
│ backend/app/core/algorithms/ocr_quality.py  (纯算法：ħ 等乱码与碎行检测)│
│ backend/app/core/algorithms/markdown_blocks.py (纯算法：PDF 硬折行重连)│
│ backend/app/core/algorithms/material_chunking.py (纯算法：标题吸收/短片过滤)│
│ backend/app/core/extractors.py              (PDF 图文稀疏页与字体检测) │
│ backend/app/services/_material_pipeline.py  (VLM 路由 + 段落重连 + is_title)│
│ backend/app/services/knowledge.py           (get_snippets_for_point 兜底)│
│ miniprogram/src/utils/richText.ts           (前端乱码兜底 + 中文软折行合并)│
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Track B: 题目问答多轮对话上下文 + 教材依据 + 防剧透                     │
│                                                                      │
│ backend/app/schemas/question.py             (AskCoachRequest +history/thread_id)│
│ backend/app/api/v1/questions.py             (透传 thread_id/history)   │
│ backend/app/integrations/llm/coach_memory.py (DEFAULT_MAX_TURNS=12)   │
│ backend/app/services/question.py            (ask_coach 记忆+RAG依据+消息列表)│
│ miniprogram/src/types/question.ts           (AskCoachParams 类型契约)  │
│ miniprogram/src/api/modules/questions.ts    (apiAskQuestionCoach 传参)│
│ miniprogram/src/composables/useCoachChat.ts (传 thread_id/history + 本地缓存)│
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Design — Track A (RAG 原文提取与依据展示)

### 2.1 数学乱码与孤立碎行检测 (`backend/app/core/algorithms/ocr_quality.py`)
1. **扩展拉丁映射错乱字符识别（解决 `ħx1` 漏判）**：
   - 新增扩展拉丁异常符号集合 `_EXTENDED_LATIN_GARBLE_RE`：匹配混入数学表达式/变音字母直接粘连 ASCII 变量或数字的异常 token，例如 `ħ` (`U+0127`)、`đ` (`U+0111`)、`ø` (`U+00F8`)、`ł` (`U+0142`)、`þ` (`U+00FE`) 等（如 `ħx1`, `ħx2`, `ħxm`, `ħxi`），以及 `[\u0100-\u024f]` 字符紧邻字母/数字/下标/运算符且非普通西欧单词的数学粘连碎片。
   - 在 `_math_garble_tokens(tokens)` 中加入该规则，从而同步被 `detect_symbol_garble()` 和 `detect_broken_math_layout()` 命中，并可在无 VLM 时被 `sanitize_symbol_garble()` 清洗。
2. **孤立单字母/下标碎行检测（解决 `1, xi` + `m/n/d/X` 漏判）**：
   - 在 `detect_broken_math_layout(text)` 中新增判定维度：统计**单字符纯字母行**（如 `len(ln) == 1 and ln.isascii() and ln.isalpha()`，例如独立成行的 `m`, `n`, `d`, `X`）及**残缺上标/下标碎行**（如 `1, xi`、`2, ..., xi`、行尾以 `=` / `(` / `,` 悬空断行）。
   - 当页面同时满足以下之一时返回 `True`：
     - 已有 `_math_garble_tokens` 命中（如 `ħx1`）；
     - 原有 `_FORMULA_FRAGMENT_LINE_RATIO > 0.45`（`lines >= 6`）；
     - 孤立单字母行 `>= 3` 且与其他公式/短碎行合计占比 `>= 0.35`（`lines >= 6`），或出现悬空等号/半截变量行 + 连续 `>= 3` 个孤立单字母行。
   - 保护正常代码或枚举列表：排除 Markdown 列表项、围栏代码块与中文正常句子。

### 2.2 PDF 字体与图文稀疏页 VLM 路由 (`extractors.py` & `_material_pipeline.py`)
1. **扩充 `_SYMBOL_FONT_MARKERS` 与字体异常检测**：
   - 在 `_SYMBOL_FONT_MARKERS` 中补充常见 TeX/Math 字体特征：`cmr`, `cmmi`, `cmsy`, `cmex`, `msam`, `msbm`, `cambria`, `stix`, `latinmodern`, `eusm`, `euex`, `wasy`。注意仍保持仅在 `ToUnicode == "null"` 时由字体名触发（避免误伤正常有正确 ToUnicode 的 Cambria 正文；而错误 ToUnicode 由 2.1 内容特征检测捕获）。
   - 同时检查文本中是否存在 Unicode 私用区字符 `[\ue000-\uf8ff]`（PUA 符号映射失败典型表现），命中直接标为 `has_symbol_garble=True`。
2. **图文主导/少字页检测（解决第 3/4 页只剩“基本概念”丢正文）**：
   - 在 `PdfPageExtraction` 新增字段 `needs_visual_ocr: bool = False`（由 `page_has_visual_content` 决定：当 PyMuPDF 页内存在内嵌位图 `len(page.get_images(full=True)) > 0` 或复杂矢量绘图 `len(page.get_drawings()) >= 8`，且有效非空白文本字符 `< 60` 时，置 `needs_visual_ocr = True`）。
   - `_page_needs_vlm(page)` 改为 `page.needs_repair or page.needs_visual_ocr or not page.text.strip()`。
   - 这样第 3/4 页即便有“基本概念”4 个字，只要页内有示意图/图表/公式矢量图，就会送入 VLM 做完整图文+公式转录；如果 VLM 转录后确实只有“基本概念”纯装饰标题，后续 2.4 标题过滤会将其吸收掉而非生成空洞切片。

### 2.3 PDF 视觉硬折行重连 (`markdown_blocks.py` & `_material_pipeline.py`)
- 新增纯函数 `unwrap_pdf_visual_line_breaks(text: str) -> str`（置于 `markdown_blocks.py`）：
  - 逐行扫描并维护块状态（跳过围栏代码块 ```` ``` ````、GFM 表格连续行、展示公式 `$$...$$` / `\[...\]`、`#` 标题、列表 `- ` / `* ` / `1. `、引用 `> `）。
  - 对于普通正文连续行 `prev` 与 `curr`：
    - 若 `prev` 末尾为句末终止标点（`。！？；：.!?;:`）或冒号/破折号/完整结束符，或者 `curr` 为新块起始（空行、标题、列表、表格、公式、引用），则**保留换行**（不合并）。
    - 否则（即属于 PDF 行宽硬折断，如 `从而方便后续对数据的存储、可` + `视化、` + `建模等操作。`），将两行重连：
      - 若 `prev` 末字符或 `curr` 首字符包含中文/CJK 标点（且非 `ASCII + ASCII` 边界），**直接无空格拼接**；
      - 若 `prev` 以英文连字符 `[A-Za-z]-` 结尾且 `curr` 以 `[A-Za-z]` 开头，去掉连字符拼接；
      - 其余 ASCII 词间保留单个空格拼接。
- 在 `repair_garbled_pdf_pages` 中，对**未走 VLM**（即直接使用 PyMuPDF 提取文本）的页面，先执行 `unwrap_pdf_visual_line_breaks(repaired_text)`，再传给 `split_markdown_blocks()`；同时对被硬折行打散的双换行块内部单换行也完成自然重连。

### 2.4 标题识别与无效短切片兜底 (`_material_pipeline.py`, `material_chunking.py`, `knowledge.py`)
1. **解析期标题识别 (`is_title=True`)**：
   - 新增辅助函数 `is_heading_block(block: str) -> bool`：
     - 命中 Markdown 标题 `^#{1,6}\s+.+$`（且单行，非多行正文）→ 剥离 `# ` 前缀后以 `is_title=True` 传入 `ParagraphInput`，让 `split_material_into_snippets` 自动更新 `current_chapter_title` 而不产出独立正文切片；
     - 命中纯短标题行（单行、长度 `<= 20` 字符、无句末标点 `。！？.!?;:，,`、无数学公式符号 `=$\\`、且属于页内首块或独立短标题块）→ 在同页还有正文块时以 `is_title=True` 更新 `chapter_title`；若整页仅此一个短标题块（且整份资料其他页有实质内容），也先记为 `current_chapter_title` 而避免单独生成 4 字正文切片。
2. **分块与查询期兜底过滤**：
   - 在 `split_material_into_snippets` 合并完成后（阶段 2.5）：若存在极短无信息残片（`char_count < 15` 且无句末标点、无数字、无公式 `$`/`=`，例如残留单字或孤立标题），在保证不把整份有效资料清零的前提下（仅当过滤后仍有至少 1 条实质切片时）予以剔除，并重排 `index`。
   - 在 `KnowledgeService.get_snippets_for_point`（查询期轻量兜底，针对历史已入库的未重解析脏切片）：若某知识点关联了多条切片且其中部分切片满足“极短纯标题噪声”（`len(content.strip()) < 15` 且无公式/无句末标点，或内容与 `chapter_title` 完全相同），而同知识点下还存在其他非噪声切片，则过滤掉这些噪声标题切片后再返回。

### 2.5 前端兜底与富文本换行容错 (`miniprogram/src/utils/richText.ts`)
1. `isGarbledSnippetText`：
   - 补充检测扩展拉丁乱码字符（如 `[\u0127\u0111\u0142\u00fe]` 或混入字母数字的 `\u0100-\u017f` 粘连 token，如 `ħx1`）以及密集超短孤立字母碎行（如多行连续出现单字母 `m`/`n`/`d`/`X`）。
2. `parseRichContent`：
   - 在收集 `paraLines` 后、调用 `buildMultilineChildren` 前，对非 Markdown 块级语法的普通中文视觉断行做温和合并（若前一行末尾为中文字符或中文逗号/顿号 `，、` 且下一行首字符为中文字符且不以块标记开头，合并为连续行），避免老数据 `<br>` 满屏换行，同时完全保留 `$$` 公式、列表、标题、表格与真实段落换行的样式。

---

## 3. Detailed Design — Track B (题目问答区域多轮对话上下文 + 依据 + 防剧透)

### 3.1 跨层契约对齐 (`schemas/question.py` ↔ `miniprogram/src/types/question.ts` & `api/modules/questions.ts`)
- 后端 `AskCoachRequest`（`backend/app/schemas/question.py`）新增两个**可选**字段（100% 向后兼容已有调用）：
  ```python
  class AskCoachHistoryItem(BaseModel):
      role: Literal["user", "assistant"]
      content: str = Field(..., min_length=1, max_length=2000)

  class AskCoachRequest(BaseModel):
      user_prompt: str = Field(..., min_length=1, max_length=1000, description="学生追问内容")
      user_answer: str | None = Field(default=None, description="学生的原始作答")
      grading_points: list[str] | None = Field(default=None, description="相关采分点")
      thread_id: str | None = Field(default=None, min_length=1, max_length=128, description="可选会话线程标识")
      history: list[AskCoachHistoryItem] | None = Field(default=None, max_length=24, description="可选前端兜底历史消息")
  ```
- 前端 `miniprogram/src/types/question.ts` 新增 `AskCoachHistoryItem` 与 `AskCoachParams`（`user_prompt`, `user_answer?`, `grading_points?`, `thread_id?`, `history?`），`apiAskQuestionCoach`（`miniprogram/src/api/modules/questions.ts`）保留原位置参数签名并追加可选 `options?: { threadId?: string; history?: AskCoachHistoryItem[] }`（不破坏现有直接传 2~4 个参数的调用点）。

### 3.2 后端多轮记忆、原生消息组装、RAG 依据注入与防剧透 (`services/question.py` & `coach_memory.py`)
1. **记忆窗口扩充 (`coach_memory.py`)**：
   - 将 `DEFAULT_MAX_TURNS` 从 `6` 调整为 `12`，`_MAX_USER_CHARS` 调整为 `600`，`_MAX_ASSISTANT_CHARS` 调整为 `1000`，确保十几轮正常题目追问时能准确回溯“我刚开始问的什么”。
2. **多轮历史加载与兜底 (`QuestionService.ask_coach`)**：
   - 构造租户隔离键：`effective_thread = (thread_id or f"q:{question_id}").strip()`，`memory_key = f"{user_id}:question:{question_id}:{effective_thread}"`。
   - 先从 `self.memory_store.load(memory_key)` 读取服务端历史轮次 `turns`（仅当 `self.memory_store is not None`）。
   - 若服务端 `turns` 为空（例如无 Redis 重启后、或从前端跨页带入），且请求中传入了非空 `history`（成对或逐条的 `user`/`assistant` 消息），则直接采纳请求传入的 `history` 作为历史消息序列（并可补种到 `memory_store`）。
3. **教材原文依据注入**：
   - 若 `question.source_snippet_id` 非空，通过 `self.material_repo.get_snippet_by_id`（或 `build_source_snippet_map` / `question_repo` 已有切片读取能力 — 实现时核对 `QuestionRepository` / `MaterialRepository` 现有方法，复用不重复造轮子）获取绑定原文片段，拼入上下文 `【教材原文依据】`；若 `question.source_snippet_id` 为空且 `self.search_adapter` 可用，用 `question.stem` 做轻量 `top_k=2` 检索补充背景知识。
4. **防剧透（做题中 vs 复盘/已作答）**：
   - 注意到 `session/index.vue` 在学生未选答案时也会传入 `userAnswer` 为空/空白，`detail/index.vue`（或已作答提交后）通常会携带 `user_answer` 或已作答状态。
   - 当 `user_answer` 为空（`not (user_answer and user_answer.strip())`）时：
     - **不**把 `【标准答案】` 原文直接喂给 prompt 要求输出答案（或明确在 system prompt 约束：“学生尚未提交作答，请优先启发引导思考思路与教材知识点，严禁直接说出正确选项字母或标准答案全文”）；
     - 当 `user_answer` 非空时：正常附带 `【标准答案】`、`【解析】` 与 `【学生作答】` 进行精准纠偏与解析。
5. **原生多轮 `LLMMessage` 组装**：
   - `[LLMMessage(role="system", content=system_content)]`
   - `+ [LLMMessage(role="user", content=question_and_material_context), LLMMessage(role="assistant", content="好的，我已经了解这道题和相关教材内容，请随时告诉我你的疑问。")]`（将静态题干与教材依据独立成首轮背景锚点）
   - `+ [按时间顺序展开的历史 LLMMessage(role="user"|"assistant", content=...) ...]`
   - `+ [LLMMessage(role="user", content=user_prompt)]`
   - 调用 `self.llm.generate_structured(...)` 返回 `output` 后，执行 `self.memory_store.append(memory_key, user_prompt, output.reply)`。

### 3.3 前端会话持久化与双参数发送 (`miniprogram/src/composables/useCoachChat.ts`)
- **发送传参**：在 `ctx.questionId` 分支，读取 `sessionHistories.value.get(targetKey)` 中**发送当前消息之前**已有的成功历史消息（过滤掉 `error` 占位气泡，截取最近 20 条/10 轮），随 `threadId: targetKey` 与 `history` 一起传给 `apiAskQuestionCoach`。
- **跨页局部持久化**：在 `useCoachChat` 中为 `sessionHistories` 增加基于 `uni.getStorageSync` / `uni.setStorageSync` 的轻量缓存（Key 如 `zhilian:coach:history:${targetKey}`，单会话最多保留最近 30 条非 error 消息，try/catch 静默容错避免测试环境无 `uni` 报错），这样从做题页交卷跳转报告页时，`q:${questionId}` 的聊天记录与上下文都能无缝延续。

---

## 4. Risks & Rollback Considerations

- **历史脏切片需重解析**：代码合入后，已入库的旧教材仍保留旧切片；查询期短标题过滤与前端乱码提示可立即缓解旧数据显示，彻底恢复图表/公式（第3/4/5页）需对目标资料执行 `POST /materials/{id}/parse?force=true`。
- **VLM 调用量控制**：图文稀疏页门禁（`valid_chars < 60` 且有内嵌图片/矢量图）仅针对缺文字的图表页触发 VLM，纯文字正常页零额外成本；并发与单页失败降级复用现有 `transcribe_dirty_pages_with_vlm` 机制。
- **测试契约变更**：`miniprogram/tests/useCoachChat.spec.ts:188-197` 原先显式断言“不传 `thread_id`”，本设计改为显式传入 `thread_id` 与 `history`，需同步更新该单测与后端 `test_question_service.py`。
