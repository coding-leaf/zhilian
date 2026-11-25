# Technical Design: 主界面全局助教、视觉语义切片与两阶段考前精讲笔记

## 1. Swarm 清晰职责分组与零重叠所有权

为避免扁平堆砌，本任务划分为 **3 条业务交付线 + 1 条独立质量核验线**，每个 Worker 仅修改显式拥有文件，0 冲突：

| 交付线 (Thread) | Worker | 模型 | 职责边界 |
| --- | --- | --- | --- |
| `t-coach-scope` | `coach-backend` | `gemini-4-hydrogen-high` | 全局/课程/讲义助教统一契约、`allowed_version_ids` 1 次 Embedding 检索、`build_global_study_context`、`generate_general` 兜底 |
| `t-coach-scope` | `coach-frontend` | `gemini-4-hydrogen-high` | 工作台 `useHomeCoach.ts` 解耦、`CoachScopeSelector.vue` 胶囊切换、三套快捷提问与会话隔离 |
| `t-doc-chunking` | `doc-pipeline` | `gemini-4-hydrogen-high` | 高召回 VLM 路由、`PaddleOCR-VL-1.5` 协议适配、滚动 JPEG 省内存渲染、`is_heading_block` 禁公式、`deepseek-flash` 8 页滑窗语义打标切片 |
| `t-study-guide` | `guide-backend` | `gemini-4-hydrogen-high` | Stage 1 全局收敛 2 层考点树（修 `MAX_LEVEL_2_RATIO`）+ 迁移 `0015` + Stage 2 单飞锁 `max_tokens=6144` 考前精讲 + RQ 整章预热 |
| `t-study-guide` | `guide-frontend` | `gemini-4-hydrogen-high` | 全屏分段「考点精讲页」（`精讲笔记 \| 典型例题 \| 对比与避坑 \| 教材原文`）+ 懒生成/缓存/重生成 + 讲义页「已精讲」与一键整章预热 |
| `t-verify` | `verifier` | `gemini-4-neon-high` | 合入后独立跨层契约、微信红线、300 行红线与回归审查 |

---

## 2. Thread 1 契约：主界面全局助教

### 2.1 后端 (`coach-backend`)
- `POST /api/v1/coach/ask` (`ScopedCoachRequest`):
  - 新增 `scope: Literal["global", "folder", "material", "knowledge_point"] | None = None` 与 `history: list[CoachHistoryMessage] = []`。
  - 校验规则：若三 ID 全空且 `scope is None` -> 自动归一化为 `"global"`；若显式传 `scope="folder"` 但 `folder_id is None`（或 `material` 缺 `material_id`、`knowledge_point` 缺 `knowledge_point_id`）-> 返回 422，严禁静默回退首课。
- `SearchOptions`: 新增 `allowed_version_ids: tuple[uuid.UUID, ...] | None = None`（`pgvector.py` 与 `memory.py` 同步过滤 `MaterialSnippet.version_id.in_(allowed_version_ids)`），将跨资料/全库检索收敛为 **1 次 Embedding + 1 次 SQL**。
- `QuestionRepository.list_ready_current_versions_for_user(user_id)` 返回用户所有未删、未归档、已解析资料的 `(material_id, current_version_id, title, folder_id)`。
- `_coach_context.build_global_study_context`：汇总就绪资料数、考点总数、薄弱考点 Top 5（复用 `DiagnosisRepository`）。
- `coach_graph.py`：全局模式（`scope == "global"`）检索不到高置信度教材切片时，走 `generate_general`（通用学科知识解答，`cited_snippets=[]`，显式标注通用解答不捏造教材页码）。

### 2.2 前端 (`coach-frontend`)
- `miniprogram/src/pages/index/composables/useHomeCoach.ts`：独立维护 `coachFocusedFolderId`（默认 `undefined` 即全局），彻底与 `folderStore.currentFolderId` 解耦。
- `miniprogram/src/components/CoachScopeSelector.vue`（<= 160 行）：横向 `scroll-view` 胶囊条（「全部资料 · 全局」+ 各课程），供工作台内嵌到 `AiCoachDrawer.vue` 顶部语境栏。
- `useCoachChat.ts`：解除 `folderId`/`materialId` 为空时的本地拒发限制；支持 `scope: 'global' | 'folder' | 'material' | 'knowledge_point'` 与三套独立快捷提问（`GLOBAL_QUICK_PROMPTS` / `FOLDER_QUICK_PROMPTS` / `MATERIAL_QUICK_PROMPTS`）；会话 key 保持 `zhilian:coach:history:<userId>:<sessionKey>`（全局用 `global`）。

---

## 3. Thread 2 契约：视觉重建与语义打标切片 (`doc-pipeline`)

- **VLM 触发与协议**：
  - `PdfPageExtraction` 新增 `is_slide_layout: bool = False`、`has_math_expression_layout: bool = False`。
  - `_page_needs_vlm` 放宽覆盖 PPT 数学/图解页（`is_slide_layout` + 希腊字母/数学符/`drawings >= 4`/内嵌图）及孤立公式块/上下堆叠分式；清晰封面/目录/致谢跳过 VLM。
  - `VLMSettings` 新增 `prompt_style: Literal["auto", "general_markdown", "paddleocr_vl"] = "auto"`、`image_format: Literal["jpeg", "png"] = "jpeg"`、`jpeg_quality: int = 85`、`max_image_edge: int = 1440`。
  - `OpenAICompatibleLLMAdapter` 支持 `image_first` 消息序列化，按 `PaddleOCR-VL-1.5` 实测最佳格式调用；`transcribe_dirty_pages_with_vlm` 改为滚动批渲染（每批 `<= max_concurrency * 2` 页 JPEG，立即释放字节并更新进度）。
- **确定性标题止血 + `deepseek-flash` 语义打标**：
  - `is_heading_block` 全面拉黑数学算符与希腊字母，非 `#` 文本仅认显式章节号或页顶 `y0/page_height <= 0.22` 的纯中文短标题。
  - 新增 `core/algorithms/semantic_chunking.py`（纯函数：逻辑单元合并、上限 1400 字、全空兜底、保护 `$$...$$`/表格）与 `services/_semantic_chunker.py`（8 页滑窗调用 `deepseek-flash`，Zero-Rewrite 轻量标注 `PageSemanticAnnotation`，`< 3` 页或 `FakeLLMAdapter` 自动旁路，单批失败回退确定性切片）。

---

## 4. Thread 3 契约：收敛考点树 + 考前精讲笔记

### 4.1 后端 (`guide-backend`)
- **Stage 1 收敛建树**：
  - `knowledge.py`：当 `total_chars <= 28_000` 时采用 One-Shot 全局单次建树（目标 8~15 个核心考点，干净 2 层树）；`> 28_000` 按大章分批后走轻量归并。
  - `knowledge_quality.py`：干净 2 层树（`max_depth == 2` 且 `<= 25` 节点）豁免 `MAX_LEVEL_2_RATIO=0.60`，改为校验 `level_1_count >= 2` 且单模块子节点 `<= 8`；密度基线调为 `1000~4500` 字/考点，向量去重阈值 `0.86`。
- **Stage 2 考前精讲 & 迁移 `0015_kp_study_guide`**：
  - `knowledge_points` 新增 `study_guide`（`JSON().with_variant(JSONB, "postgresql")`, nullable）、`study_guide_generated_at`（`DateTime(timezone=True)`, nullable）、`study_guide_version`（`Integer`, default `0`）。
  - `KnowledgeTreeNodeResponse` 新增 `has_study_guide: bool = False`（查询层 `defer(KnowledgePoint.study_guide)` 零载荷膨胀）。
  - 单考点生成：Redis/内存单飞锁 `zhilian:study_guide:lock:{kp_id}` + 短事务读快照后 `rollback()` 释放连接 + 事务外调 `deepseek-flash`（`max_tokens=6144`, `tool_choice="auto"`, `timeout=55.0`）+ 短事务写回 `commit()`；并发抢锁超时返 `202` + `status="generating"`。
  - `StudyGuideContent`（9 要素 Pydantic 强类型：`exam_positioning`, `core_definition`, `symbol_table`, `key_formulas`, `derivation_steps`, `worked_examples`, `comparisons`, `pitfalls`, `memory_anchors`）。
  - 端点（全部普通 `def`）：
    - `GET /api/v1/knowledge/{kp_id}/study-guide`
    - `POST /api/v1/knowledge/{kp_id}/study-guide/generate` (`{ force?: bool }`)
    - `POST /api/v1/materials/{material_id}/study-guides/prewarm` (`{ version_id?, force? }`) -> `202`
    - `GET /api/v1/materials/{material_id}/study-guides/status` (`?version_id=...`)
  - RQ 任务：在 `backend/app/worker.py::REGISTERED_TASKS` 注册 `"prewarm_study_guides"`（投递 `zhilian` 普通队列，DB 计数 + Redis Hash `zhilian:study_guide:prewarm:{version_id}` 瞬态进度）。

### 4.2 前端 (`guide-frontend`)
- **独立全屏「考点精讲页」**：`miniprogram/src/subpackages/material/pages/knowledge/index.vue`（在 `pages.json` 注册，严格 `<= 260` 行）。
- **清晰职责分段（拒绝一屏硬塞！）**：页面顶部固定轻量信息栏 + 4 段切换条：
  1. **精讲笔记**（`StudyGuideNoteView.vue`, `<= 240` 行）：考法与直觉定位、完整定义、符号速查表、核心公式组、逐步推导链、30 秒速记锚点。
  2. **典型例题**（`StudyGuideExamplesView.vue`, `<= 220` 行）：1~2 道标准例题（题干 + 解题切入点 + 分步解答 + 可折叠核对答案）。
  3. **对比与避坑**（`StudyGuideCompareView.vue`, `<= 200` 行）：相邻易混概念对比卡片 + 考场高频避坑（误区 → 错因 → 正解）。
  4. **教材原文**（复用既有 `KnowledgeEvidenceList.vue`）：干净重构后的页码溯源文本。
- **懒生成交互**：未生成时展示 Stage 1 轻量核心定义与一键/自动触发精讲生成（`LONG_REQUEST_TIMEOUT_MS=60000`，遇到 `202 generating` 短轮询），完成后永久秒开，右上角支持「重新生成」；吸底操作栏带 `env(safe-area-inset-bottom)` 保留「针对此考点出题」与「向 AI 助教追问」。
- **讲义详情页联动**：点击考点卡片直达全屏精讲页，已生成考点显示「已精讲」徽标；页面顶部增加「一键生成本章精讲」按钮并对接 `BackgroundTaskBar`。
