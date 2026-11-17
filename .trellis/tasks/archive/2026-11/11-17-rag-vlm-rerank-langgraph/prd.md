# RAG P0-P2 & Adaptive Corrective LangGraph Pipeline

## Goal

全面升级本项目 RAG 知识库与 AI 助教链路，彻底消除切片碎片化（`σi\n2`、半句截断）与公式乱码（`k σpiupi ђvpi`），落地高性价比的 **P0 切分检索修复 + P1 Contextual/Rerank + P2 PyMuPDF & 硅基流动云 VLM 混合解析 + Adaptive/Corrective LangGraph 编排与多轮记忆 + 前端公式/表格渲染增强**。

---

## Requirements

### R1: P0 — PDF 乱码检测、结构化切分、混合检索与邻接上下文修复
- **R1.1 扩充数学/乱码检测 (`backend/app/core/algorithms/ocr_quality.py`, `extractors.py`)**：
  - 除既有 ASCII 符号簇检测外，识别希腊/西里尔混合乱码字符（如 `ђ`、`σpiupi`）以及每页大量孤立超短数学/符号断行（如 `σi` / `2` / `rank σi=1`），消除漏检。
- **R1.2 切分与循环合并修复 (`backend/app/core/algorithms/material_chunking.py`)**：
  - 修复 `merge_isolated_short_snippets()`：对 `< min_chars`（提升至合理下限如 `120` 字符）的连续短片段**循环合并**而非两两合并一次即停；严格遵守同 `page_number` 与同 `chapter_title` 边界，禁止跨页/跨章拼接；同页/同节连续段落按目标块大小聚合至合理长度（如 `350~750` 字符，`<= 800`）。
  - `PRIMARY_PUNCTUATION_CHARS` 补充英文句号 `.`（跳过小数点如 `3.14` 与常见缩写），重叠边界对齐优先落在完整句界，禁止从 `,`/`;` 或 `$...$`/`$$...$$`/Markdown 表格内部腰斩。
- **R1.3 检索分词、范围下推、邻接扩展与干净摘要 (`search.py`, `pgvector.py`, `question.py`, `source_snippets.py`)**：
  - `tokenize_text()` 保留希腊字母、LaTeX/数学标识符与中文双字词元（兼容既有单测不退化），并降低 BM25 对超短碎片的过度加权。
  - `SearchOptions` 支持 `allowed_snippet_ids`，在 `PgvectorHybridSearchAdapter` 与 `FakeSearchAdapter` 中于检索阶段（SQL `WHERE id IN ...`）直接下推过滤，避免先取全资料 Top-20 再过滤导致考点切片漏召回。
  - `PgvectorHybridSearchAdapter` 增加独立的全库关键词召回分支并与向量 Top-K 合并后执行 BM25 + RRF，避免仅在向量 Top-20 内算 BM25。
  - 助教/出题消费检索结果时支持同版本同页 `snippet_index ± 1` 邻接上下文扩展，并以句/公式完整边界截取展示摘要（替代 `[:320]` 硬截断）。

### R2: P1 — Contextual Retrieval 上下文前缀 & 硅基流动 Rerank
- **R2.1 Contextual Enrichment**：
  - 在生成切片 Embedding 时拼接 `[章节标题 · 第N页]` 上下文前缀（保持数据库存储的 `MaterialSnippet.content` 原文干净用于展示）。
- **R2.2 Rerank 协议与硅基流动适配器 (`backend/app/integrations/rerank/`)**：
  - 新增独立 `app.integrations.rerank` 模块（遵守 6 条 `import-linter` 合约）：`RerankProtocol`、`FakeRerankAdapter`、`SiliconFlowRerankAdapter`（对接 `/v1/rerank`，默认适配 `BAAI/bge-reranker-v2-m3`）、`create_rerank_adapter`。
  - 在 `config.py` 新增 `RerankSettings`（默认 `enabled=False, provider="fake"` 保证离线测试零联网），在 `ProviderRegistry` 中安全集成（不破坏既有 `strict=True` 构造测试）。

### R3: P2 — PyMuPDF 坐标版面抽取 + 硅基流动云 VLM 脏页混合解析
- **R3.1 PyMuPDF 集成 (`backend/pyproject.toml`, `backend/app/core/extractors.py`)**：
  - 引入 `pymupdf`（`fitz`），用坐标/块感知的读取顺序抽取 PDF 文本，并实现 `render_pdf_page_png()` 将指定页渲染为 150 DPI PNG（保留 `pypdf` 降级兼容）。
- **R3.2 多模态 LLMMessage 与云 VLM 脏页混合路由 (`integrations/llm/`, `services/_material_pipeline.py`, `config.py`)**：
  - 扩展 `LLMMessage` 支持可选图片附件（`image_urls` / OpenAI `image_url` 内容块），`OpenAICompatibleLLMAdapter` 支持多模态请求序列化，`FakeLLMAdapter` 保持纯文本兼容。
  - 在 `config.py` 新增 `VLMSettings`（支持 `provider="siliconflow"`、`model="Qwen/Qwen2.5-VL-7B-Instruct"` 等、并发上限 `max_concurrency=3`、`dpi=150`，默认 `enabled=False, provider="fake"`）；`EmbeddingSettings.provider` 同步支持 `"siliconflow"`。
  - `_material_pipeline.py` 实现混合路由：正常纯文本页直接走 `PyMuPDF`（0 成本），仅被判定为公式乱码/缺字库/扫描图页的脏页才并发渲染送 VLM 转录为带 `$...$`/`$$...$$` 的完整 Markdown（严格防幻觉 Prompt；单页失败优雅回退 `PyMuPDF` 文本，不阻断整份文档）；按 Markdown 块与 `$$...$$`/表格原子保护切分，不再按单 `\n` 拆碎。

### R4: Adaptive + Corrective LangGraph 编排与多轮记忆
- **R4.1 升级 `coach_graph.py` 为 Adaptive + Corrective RAG**：
  - 节点 1 `route_intent`：区分「寒暄/元问题（如“你好呀”）→ 直接亲切引导，零检索」、「宏观章节梳理/考点概览 → 读取结构化知识点树 `structured_content`」、「具体概念/公式/题目答疑 → 检索闭环」。
  - 节点 2 `retrieve_and_rerank`：执行范围下推混合检索 + Rerank 精排 + 邻接切片拼接。
  - 门禁 `check_rerank_score`：基于 Rerank 分数确定性路由（不浪费额外 LLM 打分调用）；若分数过低且未重写过，跳入 `rewrite_query`（结合知识点/章节与历史对话指代消解后回流重搜 1 次）；仍不足则走 `honest_fallback`。
  - 节点 `generate_grounded` + 确定性 `verify_citations`（纯 Python 校验与合法引用对齐，省去冗余二轮大模型返工）。
- **R4.2 会话记忆 (`thread_id` / Checkpointer)**：
  - `ScopedCoachRequest` / `ScopedCoachParams` / `useCoachChat.ts` 兼容新增可选 `thread_id`（前端自动传 `sessionKey`）；后端采用 LangGraph `MemorySaver` + 可选 Redis 历史滑动窗口（最近 6 轮，无迁移风险，SQLite/离线单测零阻塞），支撑“那不满足这个条件会怎样”等多轮指代追问。

### R5: 前端 LaTeX 公式与 Markdown 表格渲染增强
- **R5.1 `miniprogram/src/utils/richText.ts`**：
  - 支持常见 LaTeX 环境（`\begin{pmatrix}` / `bmatrix` / `vmatrix` / `cases` / `aligned` + `\\` / `&` 矩阵/分段排版）与常见补充数学命令（`\hat`, `\bar`, `\vec`, `\det`, `\lim`, `\log`, `\sin`, `\cos`, `\binom`, `\mathbb`）。
  - 支持 GFM Markdown 管道表格（`| a | b |`）解析渲染为清晰 `<rich-text>` 表格，不泄露原始 `|` 源码。
  - 同步更新 `miniprogram/tests/richText.spec.ts` 与 `useCoachChat.spec.ts`。

---

## Acceptance Criteria

- [ ] **AC-1**：`ocr_quality.py` 能检出 `σ`/`ђ`/`σpiupi` 类数学乱码与高频孤立断行页；`material_chunking.py` 循环合并短片段至 `>= min_chars`、尊重页/章边界、保护英文句号 `.`、保护 `$$...$$` 与 Markdown 表格。
- [ ] **AC-2**：`SearchOptions.allowed_snippet_ids` 下推至 `PgvectorHybridSearchAdapter` 与 `FakeSearchAdapter`；混合检索具备独立全库关键词召回 + 邻接上下文扩展 + 句边界摘要裁剪；Embedding 入库带 `[章节·页码]` Contextual 前缀。
- [ ] **AC-3**：`app.integrations.rerank` 模块与 `VLMSettings` / `RerankSettings` / `LLMMessage` 多模态支持就绪，`pymupdf` 加入 `backend/pyproject.toml` 并实现 `PyMuPDF` 块抽取与脏页渲染走 VLM 混合路由（含单页超时/失败降级与并发控制），`lint-imports` 6 条合约全部 kept。
- [ ] **AC-4**：`coach_graph.py` 实现 `route_intent`（寒暄直答 / 概览读结构化知识点 / 细节走 Corrective RAG）、Rerank 门禁 + 1 次 `rewrite_query` 回流、确定性引用校验及 `thread_id` 多轮对话记忆；`ScopedCoachRequest` 与前端 `useCoachChat.ts` 兼容打通 `thread_id`。
- [ ] **AC-5**：`miniprogram/src/utils/richText.ts` 支持 LaTeX 矩阵/分段函数/补充算子与 Markdown 表格渲染，前端单测、lint、type-check 与 `build:mp-weixin` 全部通过。
- [ ] **AC-6**：`backend` `ruff format --check`、`ruff check`、`mypy app`、`lint-imports` 与全量 `pytest tests --cov=app --cov-branch --cov-fail-under=80`（含新增离线单测）全部通过；`miniprogram` 全量门禁通过。
