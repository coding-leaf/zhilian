# 修复 RAG 原文提取展示碎片化及题目问答上下文丢失

## Goal

一次性修复线上已暴露的两条核心体验链路缺陷，使教材“查看教材原文依据”呈现完整连贯、公式可读的段落，同时让“题目问答区域”具备真正的多轮对话记忆与教材原文依据感知能力：
1. **链路 A（RAG 文档解析 → 分块入库 → 知识点依据展示）**：修复 PDF 数学符号错误映射（如 `ħx1`）绕过 VLM、图文页只提取出 4 字标题“基本概念”、视觉硬折行被切碎并放大为满屏 `<br>` 等问题。
2. **链路 B（题目问答区域多轮对话上下文）**：修复做题页/报告页 `POST /questions/{id}/ask-coach` 无状态单轮设计导致 AI 无法回忆早先对话的问题，并补充题目关联的教材切片依据与未作答防剧透保护。

## Confirmed Evidence

- **RAG 展示直出架构**：`KnowledgeSnippetModal.vue` 通过 `GET /knowledge/{id}/snippets`（`backend/app/api/v1/knowledge.py:110-138` → `KnowledgeRepository.get_snippets_for_point`）按 `snippet_index` 原样返回 `material_snippets`（不经过运行时 RAG 检索）；详细排查见 `research/rag-extraction-chain.md`。
- **PDF 脏页/图文页漏判**：`extractors.py:239` 丢弃图像块，`extractors.py:245-262` 仅查 7 个符号字体且要求 `ToUnicode == "null"`；`ocr_quality.py:336-440` 未覆盖 Latin Extended-A（如 `ħ` `U+0127`）及矩阵/单字母维度碎行；`_page_needs_vlm`（`_material_pipeline.py:430-432`）只要页内存在“基本概念” 4 字且 `needs_repair=False` 就跳过 VLM。
- **硬折行与标题污染**：PyMuPDF `get_text("blocks")`（`extractors.py:237`）保留视觉硬折行 `\n`，`_material_pipeline.py:528-536` 从未传 `is_title=True`，`material_chunking.py:376-383` 严禁跨页合并且前端 `richText.ts:215-222` 逐 `\n` 转为 `<br>`。
- **题目问答无状态断点**：`useCoachChat.ts:58, 139-153` 仅在组件内存 `sessionHistories` Map 维持 UI 气泡，调用 `apiAskQuestionCoach`（`POST /questions/{id}/ask-coach`）时仅传 `{ user_prompt, user_answer, grading_points }`（`useCoachChat.spec.ts:188-197` 显式锁定不传 `thread_id`）；后端 `AskCoachRequest`（`schemas/question.py:312-317`）与 `QuestionService.ask_coach`（`services/question.py:1591-1654`）未使用 `self.memory_store`，每次仅发 `[system, user]` 两条消息且无条件拼入 `【标准答案】`；详细排查见 `research/chat-context-chain.md`。

## In Scope

### R1: PDF 脏页与图文页识别增强（触发 VLM/OCR 兜底）
- `backend/app/core/algorithms/ocr_quality.py`：扩展 `detect_symbol_garble` / `detect_broken_math_layout` / `_math_garble_tokens`，识别混入中英文/公式中的异常 Latin Extended-A/B 映射字符（如 `ħ` `U+0127` 等粘连变量/数字/公式符号的乱码 token），以及孤立单字母变量/下标碎行堆积模式（如连续单独成行的 `m`、`n`、`d`、`X`）。
- `backend/app/core/extractors.py` & `backend/app/services/_material_pipeline.py`：
  - 扩充 `_SYMBOL_FONT_MARKERS` 并支持检测携带图像/矢量绘图但有效正文字符稀疏（例如非空白字符 `< 60` 且包含内嵌图片或复杂矢量绘制）的页面（`needs_visual_ocr` / `needs_repair`），使其路由至 VLM 视觉转录，防止“第3/4页只剩基本概念4个字”丢正文。

### R2: PDF 段落重连、标题识别与短噪切片过滤
- `backend/app/core/algorithms/markdown_blocks.py` & `backend/app/services/_material_pipeline.py`：
  - 增加 `unwrap_pdf_visual_line_breaks` 纯函数：在保留 Markdown 标题、列表、代码块、GFM 表格、`$$...$$` 公式块与句末终止标点换行的前提下，将 PDF 视觉硬折行切断的中英文连续段落重新拼连（中文间无缝拼接，英文保留空格/去连字符）。
  - 在段落构造环节识别 Markdown 标题及独立无标点短标题（设置 `is_title=True`），使 `split_material_into_snippets` 将其吸收进 `chapter_title` 而不是生成孤立 4 字正文切片。
- `backend/app/core/algorithms/material_chunking.py` & `backend/app/services/knowledge.py`：
  - 在整份资料仍有有效内容的前提下，避免纯标题/极短无实质语义残片（如单独 `基本概念`、`m`、`n`）独立落库或单独作为考点依据返回；同时在 `KnowledgeService.get_snippets_for_point` 做查询期轻量兜底过滤（当同一知识点下存在实质切片时，过滤掉与章节标题重复且无实质内容的历史极短切片，兼容老数据；若全部为短片则保留防空）。

### R3: 前端原文依据乱码兜底与软折行兼容
- `miniprogram/src/utils/richText.ts`：
  - 更新 `isGarbledSnippetText`，补充识别历史未重解析切片中的扩展拉丁乱码字符簇（如 `ħx1`）及高频单字母碎行模式，触发友好的“原文公式乱码提示”。
  - 优化 `parseRichContent` 对普通非 Markdown 正文段内的中文半句硬折行容错合并（不影响 `#` 标题、列表、`$$` 公式、引用和表格的换行）。

### R4: 题目问答区域多轮对话上下文 + 教材依据 + 防剧透
- `backend/app/schemas/question.py`、`backend/app/api/v1/questions.py`、`backend/app/services/question.py`、`backend/app/integrations/llm/coach_memory.py`：
  - `AskCoachRequest` 新增可选字段 `thread_id: str | None` 与 `history: list[AskCoachHistoryMessage] | None`（向后兼容旧调用方）。
  - `QuestionService.ask_coach` 接入 `self.memory_store`（按 `f"{user_id}:q:{question_id}:{thread_id}"` 隔离；提升 `CoachSessionMemory` 默认窗口至 12 轮以便回溯早期提问；当服务端记忆为空且前端传入 `history` 时以 `history` 作为容错种子）。
  - 按真实多轮消息列表拼装 LLM 请求：`[system, 题目与教材原文上下文, *history_turns, current_user_prompt]`，并将本轮问答追加写入 `memory_store`。
  - 注入教材依据：通过 `question.source_snippet_id` 加载关联切片（及必要时轻量检索同知识点/资料补充）注入上下文，让追问延伸知识有据可依。
  - 防剧透保护：当 `user_answer` 为空/未作答且请求未显式处于复盘已作答态时，提示助教以启发引导为主、不直接剧透标准答案选项（仅在有 `user_answer` 或显式 `reveal_answer` 时完整附带标准答案与解析，或做阶段区分）。
- `miniprogram/src/types/question.ts`、`miniprogram/src/api/modules/questions.ts`、`miniprogram/src/composables/useCoachChat.ts`、`miniprogram/tests/useCoachChat.spec.ts`：
  - `apiAskQuestionCoach` 与 `useCoachChat` 在 `ctx.questionId` 分支发送 `thread_id: targetKey`（`q:${questionId}`）及裁剪后的近期 `history`（作为无 Redis/跨页重建时的兜底），并为 `useCoachChat` 增加基于 `uni.getStorageSync/setStorageSync` 的轻量本地会话持久化（有界容量），使从做题页跳转到报告页或重新打开抽屉时历史气泡不丢失；同步更新 `useCoachChat.spec.ts` 契约测试。

## Out of Scope

- 不新增 PostgreSQL 对话历史表与 Alembic 数据库迁移（复用并增强 `CoachSessionMemory` + 前端有界本地存储）。
- 不自动对线上数据库存量已解析资料批量触发重解析（代码合入后需由用户或运维对目标资料触发 `POST /materials/{id}/parse?force=true` 刷新存量切片）。
- 不改造非题目范围助教 `POST /coach/ask` 的基本契约（仅共享 `CoachSessionMemory` 窗口容量优化）。

## Acceptance Criteria

- [ ] **AC1（`ħx1` 等数学符号乱码拦截与 VLM 路由）**：含 `ħx1, ħx2, ..., ħxm` 或连续单字母维度碎行（`m`, `n`, `d`, `X`）的 PDF 页面，在 `detect_symbol_garble` / `detect_broken_math_layout` 中被稳定判定为 `needs_repair=True`，并触发 `_page_needs_vlm`（离线单测覆盖）。
- [ ] **AC2（图文/少字标题页路由 VLM）**：包含内嵌图片或矢量图形且有效文本字符 `< 60`（如仅有“基本概念”4 字）的 PDF 页面，被判定为需要 VLM 视觉转录，不再被跳过（离线单测覆盖）。
- [ ] **AC3（视觉硬折行段落重连与标题过滤）**：无空行或块内硬折行的中文 PDF 段落（如 `存储、可\n视化、\n建模等操作。`）经解析/重连后合并为自然段落，Markdown 块（`#`、列表、表格、`$$...$$`、代码块）保持完好；孤立短标题（如“基本概念”）被识别为 `chapter_title` 而非独立依据切片；`get_snippets_for_point` 对历史短标题重复切片在有实质切片时做安全过滤（离线单测覆盖）。
- [ ] **AC4（前端兜底与换行渲染）**：`isGarbledSnippetText` 能识别含 `ħx1` 等异常扩展拉丁乱码或密集单字母碎行的存量脏切片；`parseRichContent` 对普通非块级中文断行段落渲染自然连贯（Vitest 单测覆盖）。
- [ ] **AC5（题目问答多轮对话记忆与跨端契约）**：`POST /questions/{id}/ask-coach` 支持 `thread_id` 与 `history`；连续追问后询问“我刚开始问的什么”，后端发往 LLM 的 `messages` 包含按序排列的历史轮次，且支持前端 `useCoachChat` 跨抽屉关闭/页面跳转保留会话历史并传 `thread_id` 与 `history`（后端 pytest + 前端 Vitest 单测覆盖，前后端字段名严格对齐）。
- [ ] **AC6（题目问答教材依据注入与防剧透）**：`ask_coach` 关联 `source_snippet_id` 教材切片进入上下文；未作答场景（`user_answer` 为空）不向模型/回复直接泄露标准答案。
- [ ] **AC7（全量质量门禁）**：`task verify-backend`（ruff format/check、mypy strict、import-linter、pytest >=80% cov）与 `task verify-frontend`（eslint、vue-tsc、vitest）全部通过。

## Research Artifacts

- `research/rag-extraction-chain.md`
- `research/chat-context-chain.md`
