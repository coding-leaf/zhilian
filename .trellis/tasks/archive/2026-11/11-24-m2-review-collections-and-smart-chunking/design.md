# Technical Design: M2 学情全量联动归类 + PDF/PPT 智能切片与复习级知识卡

## 1. 架构分层与零冲突并行轨道划分

严格遵守 `import-linter` 6 条分层边界（`api/v1 -> services -> repositories -> models`，`core/algorithms` 纯函数零 I/O）与微信小程序红线（仅 `GET/POST/PUT/DELETE`，`.vue <= 300` 行）。M2 拆分为 **4 条完全无文件重叠的并行轨道**：

| 轨道 | 负责域 | 核心交付 |
| --- | --- | --- |
| **Track A** (`be-review-collections`) | 后端：学情 4 Tab 课程过滤 + 题库讲义/考点分组 + `QuestionCollection` 题单全链路 + 迁移 `0014` | `_filters.py`, `models/collection.py`, `0014_question_collections.py`, `collections` repo/service/schema/router, `diagnosis`/`practice`/`question` 过滤补齐 |
| **Track B** (`be-chunking-kp`) | 后端：PDF/PPT 去噪切片 + `☒` 乱码 VLM/OCR 兜底 + 三层封杀元考点 + 复习级知识卡 + 双层原文去噪 | `core/algorithms/document_denoising.py`, `ocr_quality.py`, `material_chunking.py`, `knowledge_tree.py`, `knowledge_quality.py`, `extractors.py`, `_material_pipeline.py`, `material.py`, `knowledge.py`, `_coach_context.py`, `schemas/knowledge.py` |
| **Track C** (`fe-review-collections`) | 前端：学情 4 Tab 联动过滤 + 题库三视图（题单 / 讲义考点 / 批次）+ 跨页复用收纳抽屉 | `types/collection.ts`, `api/modules/collections.ts`, `api/adapters/collection.ts`, `components/CollectionPickerDrawer.vue`, `pages/review/**`, `subpackages/report/` 收纳入口, `stores/practice.ts` |
| **Track D** (`fe-kp-review-card`) | 前端：复习级知识卡弹窗 + 原文页码范围 + `isGarbledSnippetText` 补齐 `☒`/`\ufffd` | `types/knowledge.ts`, `api/adapters/knowledge.ts`, `subpackages/material/utils/courseStudy.ts`, `KnowledgeSnippetModal.vue`, `utils/richText.ts` |

---

## 2. Track A 契约与数据模型设计

### 2.1 统一课程过滤解析 (`backend/app/api/v1/_filters.py`)
```python
UNCLASSIFIED_FOLDER_SENTINEL = "__none__"

def parse_folder_filter(
    folder_id: str | None,
    *,
    unclassified: bool = False,
) -> tuple[uuid.UUID | None, bool]:
    """Return (folder_uuid, is_unclassified). Raise 422 on invalid UUID."""
```
- `folder_id is None`: 返回 `(None, unclassified)`
- `folder_id.strip() == "__none__"`: 返回 `(None, True)`
- 合法 UUID 字符串: 返回 `(uuid.UUID(val), False)`（若同时传 `unclassified=True` 且有效 `folder_id`，优先明确 `folder_id` 或报 422；保持与 `materials.py` 一致）
- 非法 UUID: 抛出 `ValidationError` / HTTP 422。

### 2.2 既有 4 个端点过滤契约补齐
1. `GET /api/v1/wrong-records`：
   - 查询参数保持 `folder_id: str | None = None`, `unclassified: bool = False`，经 `parse_folder_filter` 解析后同时传入列表查询与 `list_wrong_record_groups(..., folder_id=..., unclassified=...)`。
2. `GET /api/v1/practices`：
   - 新增 `folder_id: str | None = None`。
   - `PracticeRepository` 过滤口径（`OUTER JOIN Material ON Practice.material_id == Material.id`）：
     - 指定 `folder_uuid`：`(Practice.folder_id == folder_uuid) | (Practice.folder_id.is_(None) & (Material.folder_id == folder_uuid))`
     - `unclassified=True`：`Practice.folder_id.is_(None) & (Practice.material_id.is_(None) | Material.folder_id.is_(None))`
   - 新增 `count_practices(...)` 返回真实 `total`；批量查 `MaterialFolder.name` 与 `Material.title` 回填 `PracticeSummaryResponse.folder_name`、`PracticeSummaryResponse.material_title`（零 N+1）。
   - `POST /api/v1/practices`：`PracticeCreateRequest` 新增可选 `collection_id: uuid.UUID | None = None`，当传入时拉取该用户对应题单内前 `MAX_PRACTICE_QUESTIONS`（50）道未软删题目开练。
3. `GET /api/v1/questions/batches` & `GET /api/v1/questions`：
   - 均接入 `folder_id: str | None = None`（支持 `__none__`）与 `unclassified: bool = False`。
   - 当指定过滤条件时，`INNER JOIN Material ON Question.material_id == Material.id` 过滤 `Material.folder_id == folder_uuid` 或 `Material.folder_id.is_(None)`；全量查询保持原行为兼容无资料兜底。
4. `GET /api/v1/questions/grouped-summary`（零迁移结构化视图）：
   - 查询参数：`folder_id: str | None = None`。
   - 返回：
     ```json
     {
       "total_questions": 24,
       "materials": [
         {
           "material_id": "uuid",
           "material_title": "第五章 - SVM.pdf",
           "folder_id": "uuid|null",
           "folder_name": "机器学习",
           "question_count": 12,
           "knowledge_points": [
             { "kp_id": "uuid|null", "kp_name": "超平面与点距离", "question_count": 5 }
           ]
         }
       ]
     }
     ```
   - 通过单次聚合查询 + 批量查 `Material`/`MaterialFolder`/`KnowledgePoint` 组装，零 N+1。

### 2.3 自定义题单数据模型与迁移 `0014_question_collections`
- `backend/app/models/collection.py`（继承 `Base, TimestampMixin, TenantModelMixin`，同步在 `models/__init__.py` 导出）：
  1. `QuestionCollection` (`__tablename__ = "question_collections"`):
     - `id: UUID` PK
     - `user_id: UUID` FK(`users.id`, CASCADE)
     - `name: String(80)` NOT NULL
     - `description: String(255)` NOT NULL default `""`
     - `folder_id: UUID | None` FK(`material_folders.id`, SET NULL), nullable
     - `color_token: String(32) | None` nullable
     - `is_pinned: Boolean` NOT NULL default `False`
     - `sort_order: Integer` NOT NULL default `0`
     - 约束：`UniqueConstraint("user_id", "name", name="uq_question_collections_user_name")`；索引：`(user_id, folder_id)`、`(user_id, is_pinned, updated_at)`。
  2. `QuestionCollectionItem` (`__tablename__ = "question_collection_items"`):
     - `id: UUID` PK
     - `user_id: UUID` FK(`users.id`, CASCADE)
     - `collection_id: UUID` FK(`question_collections.id`, CASCADE)
     - `question_id: UUID` FK(`questions.id`, CASCADE)
     - `note: String(500) | None` nullable
     - `sort_order: Integer` NOT NULL default `0`
     - 约束：`UniqueConstraint("collection_id", "question_id", name="uq_collection_items_collection_question")`；索引：`(user_id, collection_id)`、`(user_id, question_id)`。
- 迁移脚本：`backend/migrations/versions/0014_question_collections.py` (`revision = "0014_question_collections"`, `down_revision = "0013_retire_pending_review"`)。

### 2.4 题单 REST API（严禁 `PATCH`，全量仅 `GET/POST/PUT/DELETE`）
路由前缀 `/api/v1/collections` + `/api/v1/questions/{question_id}/collections`：
- `GET /collections` (`?folder_id=<uuid|__none__>`) -> `{ items: QuestionCollectionResponse[], total: int }`（含 `question_count`、`folder_name`、`updated_at`，排除软删除题目的计数）
- `POST /collections` (`{ name, description?, folder_id?, color_token?, is_pinned? }`) -> `201 QuestionCollectionResponse`（同名返回 `409 Conflict`）
- `PUT /collections/{collection_id}` (`{ name?, description?, folder_id?, clear_folder?, color_token?, is_pinned? }`) -> `200 QuestionCollectionResponse`
- `DELETE /collections/{collection_id}` -> `204`（级联仅删 `question_collection_items`，原题不动）
- `GET /collections/{collection_id}/questions` (`?page=1&page_size=20`) -> `{ items: CollectionQuestionItemResponse[], total: int, page: int, page_size: int }`（返回完整题目展示字段 `question_id, question_type, difficulty, content, options, answer, explanation, kp_id, kp_name, material_id, material_title, note, added_at`）
- `POST /collections/{collection_id}/items` (`{ question_ids: UUID[], note? }`) -> `{ added_count: int, skipped_count: int, total_count: int }`（校验题目归属当前用户且未软删）
- `DELETE /collections/{collection_id}/items/{question_id}` -> `204`
- `GET /questions/{question_id}/collections` -> `{ question_id, collection_ids: UUID[] }`
- `POST /questions/{question_id}/collections` (`{ collection_ids: UUID[] }`) -> `{ question_id, collection_ids: UUID[], added_count: int, removed_count: int }`（原子同步该题归属的所有题单）

---

## 3. Track B 契约与算法设计

### 3.1 新模块 `backend/app/core/algorithms/document_denoising.py`
纯函数、零 ORM/IO、圈复杂度 `<= 15`：
1. `PageTextBlock(text: str, x0: float, y0: float, x1: float, y1: float, page_width: float, page_height: float)`
2. `PageRole(StrEnum)`: `COVER`, `TOC`, `SECTION_DIVIDER`, `CHAPTER_SUMMARY`, `REFERENCES`, `THANK_YOU`, `LOW_INFO`, `CONTENT`
3. `strip_repeated_headers_footers(pages: Sequence[PageTextInput]) -> list[str]`：
   - 页数 `>= 4` 时统计归一化文本块/首尾行跨页频次（`>= max(3, ceil(0.35 * n))` 且长 `<= 80` 且位于顶 16%/底 16% 或跨页纵坐标一致，或无坐标模式 `>= 40%` 且 `<= 60` 无 `$`/`=`）。
   - 兜底剥离纯页码行与独立双语校名水印行（如 `福建師範大學` + `FUJIAN NORMAL UNIVERSITY`）。
4. `classify_slide_or_page(text, page_number, total_pages, *, is_slide_like: bool) -> PageRole`：
   - 完整实现研究报告 §3.3 的 7 类判定（`THANK_YOU` 不因 `！` 逃逸；`CHAPTER_SUMMARY` 区分空罗列与真表格/公式总结；全模板页安全回退）。
5. `is_non_substantive_chapter(title: str | None) -> bool`：共享 `NON_SUBSTANTIVE_CHAPTER_PATTERNS`。
6. `strip_display_watermark_lines(text: str) -> str` 与 `filter_and_rank_evidence_snippets(snippets, kp_name, kp_summary, *, max_items=5)`：供写入期与读取期复用。

### 3.2 乱码检测与抽取管线升级
- `ocr_quality.py`：新增 `_CORRUPT_GLYPH_RE` 捕获 `\ufffd`、`\u2612` (`☒`)、`\u25af` (`▯`) 及数学邻接方框/Dingbats；`detect_symbol_garble` 命中即 `is_garbled=True`；`sanitize_symbol_garble` 作为无 VLM/OCR 时的末级清理。
- `extractors.py`：
  - `PdfPageExtraction` 新增 `blocks: tuple[PageTextBlock, ...] = ()`（向后兼容默认值）。
  - 扩充 `_SYMBOL_FONT_MARKERS`。
  - 新增 `extract_pptx_slides(content: bytes) -> list[ParagraphInput]`，按 slide 解析标题占位符与 `<a:p>` 段落并赋予 1-based `page_number`。
- `_material_pipeline.py` & `material.py`：
  - PDF 与 PPTX 统一过 Stage 2 跨页去噪 + Stage 4 模板页过滤（`SECTION_DIVIDER` 更新 `current_chapter_title` 但不产出正文段落；丢弃 `COVER`/`TOC`/`THANK_YOU`/`REFERENCES`/空 `CHAPTER_SUMMARY`）。
  - `_repair_pdf_page_text`：当 `vlm is None`（或 VLM 失败）且 `page.needs_repair` 且 `_try_ocr_pdf_page` 为空时，调用 `render_pdf_page_png(pdf_bytes, page.page_number, dpi=150)` 送 `ocr.recognize_image`。

### 3.3 语义切片与复习级知识卡升级
- `material_chunking.py`：
  - `ParagraphInput` / `Snippet` 增 `page_end: int | None = None`（持久化到 `source_info["page_end"]`）。
  - 同章相邻短页柔合并（`allow_cross_page_merge: bool = True`，`target_chars=500`, `max_chars=800`，`source_ref="第 12-13 页"`，绝不跨章）。
  - 修复 `_is_ultra_short_noise_snippet`（先拦截致谢/结束语与纯目录碎片，不再因含 `！` 放行 `"谢谢！"`）。
- `knowledge_tree.py` & `knowledge_quality.py` & `services/knowledge.py` & `schemas/knowledge.py`：
  - `ExtractedKnowledgeItem` / `structured_content` 增可选 `derivation_steps: list[str]`、`common_mistakes: list[str]`；`core_summary` 截断改为 `trim_excerpt_cleanly(..., max_chars=200)`。
  - `compute_chapter_stats` & `check_chapter_coverage` 跳过 `is_non_substantive_chapter`。
  - `knowledge_quality.py` 扩展 `META_KP_NAME_PATTERN` 并新增 `CheckItemCode.CONTENT_DEPTH`（校验叶子节点实质深度、禁裸词条、禁「未展开」废话；当历史测试未提供 `structured_content` 时宽容降级不破坏旧单测）。
  - `services/knowledge.py`：字符预算分批（`<= 12` 切片且 `<= 6000` 字，贴合章节边界）+ `max_tokens=4096`；Prompt 升级为考前复习标准；写入与读取双层调用 `filter_and_rank_evidence_snippets`（最多 5 条，老资料过滤后为空返回 `[]`）；`SnippetSourceResponse` 增 `page_end: int | None = None`。

---

## 4. Track C & Track D 前端交互与组件设计

### 4.1 Track C (`miniprogram/src/pages/review/**`, `components/CollectionPickerDrawer.vue`, `subpackages/report/`)
- **4 Tab 联动**：
  - `useReviewCenter.ts` 增加 `filterEpoch` 代际防竞态；`selectFolderFilter(folderId)` 清理 `selectedWrongIds`、`selectedGroupKey`，并发触发 `loadMastery()`、`loadWrongs()`、`loadPractices()`，并通过 prop `folderId` + `refreshToken` 通知 `QuestionBankSection` 重置选中态与缓存后重拉。
  - `stores/practice.ts`：`loadPractices({ folder_id, ... })` 保存 `practiceTotal` 供 `segmentTabs` 准确显示。
  - `WrongBookSection.vue`：当顶部已选具体课程（非 `all` / `__none__`）且 `groupOptions.length <= 1` 时隐藏冗余二级分组条，但自动选中唯一分组保持「一键举一反三」可用。
- **题库三视图 & 题单抽屉**：
  - `QuestionBankSection.vue` 顶部新增紧凑分段切换：`题单收纳` | `讲义考点` | `生成批次`（全员组件严格 `<= 300` 行，拆分 `QuestionCollectionView.vue`、`QuestionGroupedView.vue`、`composables/useQuestionCollections.ts`）。
  - `CollectionPickerDrawer.vue`（全局可复用组件，`<= 250` 行）：接收 `visible` + `questionId`，打开时拉取 `GET /collections` 与 `GET /questions/{id}/collections`，支持多选勾选、底部输入框快速新建题单并自动选中、点击「确认收纳」调用 `POST /questions/{id}/collections`（遵守微信小程序禁 `PATCH` 与 `env(safe-area-inset-bottom)` 红线）。
  - 入口统一挂载到：`QuestionBankQuestionRow.vue`、`WrongRecordCard.vue`、`subpackages/report/components/AttemptResultCard.vue`（经 `report/pages/detail/index.vue` 托管单一抽屉实例，避免列表内重复挂载抽屉）。

### 4.2 Track D (`miniprogram/src/subpackages/material/**`, `utils/richText.ts`, `types/knowledge.ts`, `api/adapters/knowledge.ts`)
- `KnowledgeStructuredContent` 增可选 `derivationSteps: string[]`、`commonMistakes: string[]`；`KnowledgeSnippet` 增可选 `pageEnd: number | null`。
- `richText.ts::isGarbledSnippetText` 补齐 `\ufffd`、`\u2612` (`☒`)、`\u25af` (`▯`) 及数学语境方框检测。
- `KnowledgeSnippetModal.vue`（严格 `<= 270` 行，必要时拆出 `KnowledgeEvidenceList.vue`）：
  - 展示 5 大考前复习板块（核心定义与直觉 / 核心结论与要点 / 核心公式与符号 / 推导与解题步骤 / 适用条件与高频易错点），空项自动折叠隐藏。
  - 原文依据标题展示 `第 12 页` 或 `第 12–13 页` + 章节标签；空依据时展示清晰引导文案；超长原文支持单条展开。
