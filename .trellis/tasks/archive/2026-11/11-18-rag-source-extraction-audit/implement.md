# Implementation Plan: 修复 RAG 原文提取展示与题目问答上下文链路

## Execution Strategy (Swarm — 2 Parallel Authors + Verifier)

两条链路涉及文件几乎完全正交，使用原生 `Swarm` 在独立 `share` 工作区并行推进，最后由主会话合并并执行全量质量门禁：

- **Worker 1 (`rag-pipeline`, workspace: `share`)**：负责 Track A（PDF 乱码/图文检测、段落硬折行重连、标题识别与短噪切片过滤、前端 `richText.ts` 乱码兜底与换行优化，及对应前后端单元测试）。
- **Worker 2 (`coach-context`, workspace: `share`)**：负责 Track B（题目助教 `AskCoachRequest`/`ask_coach` 多轮记忆 + 原生消息组装 + 教材依据注入 + 未作答防剧透 + `CoachSessionMemory` 窗口调整 + 前端 `useCoachChat` 传参/缓存与契约单测）。
- **Verifier / Quality Gate**：合并两个 `share` 工作区改动到主工作区后，运行 `task verify-backend` 与 `task verify-frontend`（在宿主 Windows shell 执行，不走 WSL）。

---

## Ordered Checklist

### Track A: RAG 原文提取、分块与展示 (`rag-pipeline`)
1. [ ] `backend/app/core/algorithms/ocr_quality.py`：增强 `_math_garble_tokens`、`detect_symbol_garble` 与 `detect_broken_math_layout`，覆盖 `ħ` (`U+0127`) 等扩展拉丁粘连乱码、PUA 字符及孤立单字母维度碎行模式。
2. [ ] `backend/app/core/extractors.py` & `backend/app/services/_material_pipeline.py`：扩充数学字体标记；在 `PdfPageExtraction` 增加 `needs_visual_ocr`（有图/复杂矢量图且有效字符 `< 60`）并接入 `_page_needs_vlm`。
3. [ ] `backend/app/core/algorithms/markdown_blocks.py`：新增 `unwrap_pdf_visual_line_breaks`，并在 `_material_pipeline.py` 对非 VLM PDF 文本执行硬折行重连。
4. [ ] `backend/app/services/_material_pipeline.py`、`backend/app/core/algorithms/material_chunking.py` & `backend/app/services/knowledge.py`：解析期识别标题（`is_title=True`）更新 `chapter_title`；过滤无实质内容孤立短切片；`get_snippets_for_point` 对历史短标题噪声做安全兜底过滤。
5. [ ] `miniprogram/src/utils/richText.ts`：增强 `isGarbledSnippetText` 与中文断行容错渲染。
6. [ ] 补充/更新后端 `tests/unit/core/algorithms/test_*.py`、`tests/unit/services/test_material*.py`、`tests/unit/services/test_knowledge*.py` 与前端 `miniprogram/tests/richText.spec.ts`（或既有 richText 测试文件）。

### Track B: 题目问答多轮对话上下文与教材依据 (`coach-context`)
1. [ ] `backend/app/integrations/llm/coach_memory.py`：将 `DEFAULT_MAX_TURNS` 提升至 `12`，放宽单轮截断字符上限至 `600`/`1000`。
2. [ ] `backend/app/schemas/question.py` & `backend/app/api/v1/questions.py`：为 `AskCoachRequest` 新增可选 `thread_id` 与 `history`（`AskCoachHistoryItem`）并透传至 `question_service.ask_coach`。
3. [ ] `backend/app/services/question.py`：改造 `ask_coach` 接入 `self.memory_store`、以请求 `history` 作冷启动兜底、注入 `source_snippet_id` / 轻检索教材原文依据、未作答场景防剧透、并构建原生多轮 `LLMMessage` 列表。
4. [ ] `miniprogram/src/types/question.ts`、`miniprogram/src/api/modules/questions.ts` & `miniprogram/src/composables/useCoachChat.ts`：在题目分支传 `thread_id` 与近期 `history`，并增加轻量 `uni.setStorageSync`/`getStorageSync` 会话持久兜底。
5. [ ] 更新并补充 `backend/tests/unit/services/test_question_service.py`（及 `test_coach_memory.py`）与 `miniprogram/tests/useCoachChat.spec.ts`。

### Verification & Wrap-up
1. [ ] 合并 `rag-pipeline` 与 `coach-context` 的代码改动，检查无冲突及无越界修改 `.trellis/**`。
2. [ ] 执行 `task verify`（即 `task verify-backend` + `task verify-frontend`），确认全部通过（注意 `tests/unit/core/algorithms/` 墙钟阈值测试若因全量并发偶发抖动需单独复核确认）。
3. [ ] 若沉淀了新的通用规范经验，按需更新 `.trellis/spec/`。

---

## Validation Commands

```powershell
task verify-backend
task verify-frontend
```

## Risky Files / Rollback Points

- `backend/app/core/algorithms/markdown_blocks.py` & `material_chunking.py`：注意不可破坏现有 Markdown 表格、围栏代码块、`$$...$$` 公式与 `tests/unit/core/algorithms/` 既有测试断言。
- `backend/app/services/question.py::ask_coach`：注意检查 `AppContainer` 及单测中构造 `QuestionService` 时 `memory_store` / `material_repo` / `search_adapter` 可能为 `None`（做好空安全防护）。
- `miniprogram/tests/useCoachChat.spec.ts`：需对照更新第 188-197 行旧的无 `thread_id` 断言。
