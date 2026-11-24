# Implementation Plan: M2 学情全量联动归类 + PDF/PPT 智能切片与复习级知识卡

## 执行编排策略
- **模式**：原生 `Swarm`（4 条零文件重叠轨道并行，全部采用 `workspace:"share"`，模型按用户约定默认 `gemini-4-hydrogen-high`）。
- **合入红线**：每个 Worker 仅修改自己显式拥有的文件列表，严禁修改 `.trellis/**` 或执行 `git commit`/`push`；主会话逐轨道仅复制其显式拥有文件合入主工作区，随后统一跑全量离线门禁 `task verify` + `pnpm run build:mp-weixin`。

## 轨道清单与验证目标

### Track A (`be-review-collections`, `gemini-4-hydrogen-high`, `workspace:"share"`)
1. 新增 `backend/app/api/v1/_filters.py`（`parse_folder_filter`），复用至 `materials.py`、`diagnosis.py`、`practices.py`、`questions.py`、`collections.py`。
2. 补齐 `GET /wrong-records`（`groups` 按范围过滤 + 支持 `__none__`）、`GET /practices`（`OUTER JOIN Material` 过滤 + 真实 `total` + 批量回填 `folder_name`/`material_title` + `POST /practices` 支持 `collection_id`）、`GET /questions/batches` & `GET /questions`（`folder_id`/`__none__`/`unclassified`）、新增 `GET /questions/grouped-summary`。
3. 新增 `QuestionCollection` / `QuestionCollectionItem` 模型、`0014_question_collections.py` 迁移、repository/service/schemas/router（仅 `GET/POST/PUT/DELETE`，无 `PATCH`），注册到 `api/v1/__init__.py`、`container.py`、`deps.py`。
4. 补齐单元测试（含模型迁移一致性、过滤器、题单 CRUD/幂等收纳/删除不删原题/按题单开练、零 N+1 验证），在 share 工作区跑 `ruff` + `mypy` + `lint-imports` + 目标 `pytest`。

### Track B (`be-chunking-kp`, `gemini-4-hydrogen-high`, `workspace:"share"`)
1. 新增纯函数模块 `backend/app/core/algorithms/document_denoising.py`（跨页页眉/页脚/校名水印剔除、`PageRole` 分类、非实质章节判定、双层原文依据过滤与排序）。
2. 升级 `ocr_quality.py`（`☒`/`\ufffd`/`▯`/数学语境方框检测）、`extractors.py`（`PdfPageExtraction.blocks`、扩展 `_SYMBOL_FONT_MARKERS`、`extract_pptx_slides`）、`_material_pipeline.py` & `material.py`（串联去噪/分类、PPTX 对齐、无 VLM 时脏页渲染 PNG 走 OCR 兜底、`source_info["page_end"]`）。
3. 升级 `material_chunking.py`（同章相邻短页柔合并 `page_end`、修复「谢谢！」漏滤）。
4. 升级 `knowledge_tree.py`、`knowledge_quality.py`、`services/knowledge.py`、`services/_coach_context.py`、`schemas/knowledge.py`（三层封杀元考点、`CONTENT_DEPTH` 质检、`core_summary` 200 字公式安全截断、`derivation_steps`/`common_mistakes`、字符预算分批 + `max_tokens=4096`、双层原文去噪排序、`page_end` 下发）。
5. 补齐算法与服务单元测试（覆盖 `福建師範大學` 水印、`谢谢！`、`☒` 公式、`本章知识小结梳理`、200 字截断、PPTX 页码、老资料读取期过滤），跑 `ruff` + `mypy` + `lint-imports` + 目标 `pytest`。

### Track C (`fe-review-collections`, `gemini-4-hydrogen-high`, `workspace:"share"`)
1. 补齐前端课程过滤契约与 4 Tab 联动：`types/practice.ts`、`api/modules/practices.ts`、`api/adapters/practice.ts`、`stores/practice.ts`、`types/question.ts`、`api/modules/questions.ts`、`pages/review/**`（`useReviewCenter.ts` 代际防竞态全量联动、`WrongBookSection.vue` 单课程隐藏冗余二级条、`QuestionBankSection.vue` 接收 `folderId` 重置选中与缓存）。
2. 新增题单契约与组件：`types/collection.ts`、`api/modules/collections.ts`（仅 `GET/POST/PUT/DELETE`）、`api/adapters/collection.ts`、`components/CollectionPickerDrawer.vue`（<= 250 行，`env(safe-area-inset-bottom)`）、`pages/review/components/QuestionCollectionView.vue`、`QuestionGroupedView.vue`、`composables/useQuestionCollections.ts`。
3. 接入跨页面收纳入口：`QuestionBankQuestionRow.vue`、`WrongRecordCard.vue`、`subpackages/report/components/AttemptResultCard.vue` & `subpackages/report/pages/detail/index.vue`。
4. 补齐 `vitest` 单测，验证 `eslint` + `vue-tsc` + `vitest` + `.vue <= 300` 行 + `mpWeixinCompatGuard.spec.ts`。

### Track D (`fe-kp-review-card`, `gemini-4-hydrogen-high`, `workspace:"share"`)
1. 升级 `types/knowledge.ts`、`api/adapters/knowledge.ts`、`subpackages/material/utils/courseStudy.ts` 适配 `derivation_steps`、`common_mistakes`、`page_end`。
2. 升级 `utils/richText.ts::isGarbledSnippetText` 补齐 `☒` / `\ufffd` / `▯` 与数学语境方框检测。
3. 升级 `subpackages/material/components/KnowledgeSnippetModal.vue`（严格 `<= 270` 行，按需拆分 `KnowledgeEvidenceList.vue`），呈现 5 块考前复习卡片与页码范围/友好空态/展开控制。
4. 补齐 `vitest` 单测，验证 `eslint` + `vue-tsc` + `vitest` + `mpWeixinCompatGuard.spec.ts`。

## 最终合入与验收
1. 主会话按各轨道显式文件清单合入修改，并 `swarm kill` 清理全部 Worker。
2. 宿主 Windows PowerShell 执行全量离线门禁：
   - `task verify-backend`
   - `cd miniprogram; pnpm run lint && pnpm run type-check && pnpm run test:unit && pnpm run build:mp-weixin`
3. 沉淀新经验到 `.trellis/spec/`（如需），向用户汇总交付并确认 `git commit` 与推送 `origin` + `aliyun`（自动执行 Alembic `0014_question_collections` 迁移并重启服务）。
