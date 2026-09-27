# 技术设计：后端·文件夹范围出题与组卷

> 上位契约：父任务 `09-27-course-folder-practice-loop/design.md` §3.3、§3.4、§7；依赖 C1 的 `MaterialFolder` / 归档过滤口径。

## 1. 迁移 `0006_practice_folder_scope`

- `revision = "0006_practice_folder_scope"`，`down_revision = "0005_create_material_folders"`。
- `upgrade()`（`batch_alter_table("practices")`，兼容 SQLite）：
  - `material_id` 改为 **nullable**（`alter_column(nullable=True)`）。
  - 新增 `folder_id` UUID nullable（非 SQLite 建 FK → `material_folders.id` ON DELETE SET NULL）。
  - 新增索引 `ix_practices_user_folder_status (user_id, folder_id, status)`。
- `downgrade()`：drop 索引/`folder_id`；`material_id` 还原 `nullable=False`（若存在 NULL 行需先清理——本期数据清空，无风险）。

## 2. 模型（`app/models/practice.py`）

- `Practice.folder_id: Mapped[uuid.UUID | None]`（FK `material_folders.id`, ON DELETE SET NULL, index, nullable）。
- `Practice.material_id` 改为 `Mapped[uuid.UUID | None]`（`nullable=True`）。
- `__table_args__` 增 `Index("ix_practices_user_folder_status", "user_id", "folder_id", "status")`。

## 3. Schemas

### 3.1 `app/schemas/question.py`

- `QuestionGenerateRequest`：新增 `folder_id: uuid.UUID | None = None`；`material_id` 改 `uuid.UUID | None = None`。
  - `_require_knowledge_point_target` 之外新增校验：`material_id` 或 `folder_id` **至少一个**（否则 422）。
  - `knowledge_point_ids` 保持默认空列表；folder 范围允许缺省。
- `QuestionGenerateResponse`：`material_id / version_id / knowledge_point_id` 改**可选**（`| None = None`）；`knowledge_point_ids` 保持列表。

### 3.2 `app/schemas/practice.py`

- `PracticeCreateRequest`：新增 `folder_id: uuid.UUID | None = None`；`knowledge_point_ids` 去掉 `min_length=1`（改为默认空列表），并加校验：`folder_id` 为空且 `knowledge_point_ids` 为空 → 422。
- `PracticeDetailResponse` / `PracticeSummaryResponse` / `PracticeCreateResponse`：`material_id` 改 `uuid.UUID | None = None`；新增 `folder_id: uuid.UUID | None = None`。

## 4. Repository

### 4.1 `app/repositories/question.py`
- `list_questions(...)` 新增 `folder_id: uuid.UUID | None = None`：join `Material`（`Question.material_id == Material.id`）并按 `Material.folder_id == folder_id`、`MaterialFolder.archived_at IS NULL`（或 `Material.folder_id IS NULL` 不参与）过滤。
- 新增 `list_knowledge_points_for_folder(user_id, folder_id) -> list[KnowledgePoint]`：取该文件夹未归档资料的全部知识点（供缺省范围）。

### 4.2 `app/repositories/practice.py`
- `create_practice(...)`（或等价构造）新增 `folder_id` 参数并落库。

## 5. Service

### 5.1 `app/services/question.py`
- `generate_questions_for_knowledge_points(...)` 增补 `defer_commit: bool = False`：`True` 时不在此层 `commit()`/`rollback()`（交由外层），仅 `flush()`；默认 `False` 保持现状（零回归）。
- 新增 `generate_questions_for_folder(*, user_id, folder_id, knowledge_point_ids=None, options=None) -> MultiKnowledgePointGenerationResult`：
  1. 校验文件夹归属且未归档（复用 C1 `folder_repository`/`folder_service`；越权/不存在 → `FolderNotFoundError`）。
  2. 解析考点集：
     - 显式 `knowledge_point_ids`：逐个经 `knowledge_repo.get_knowledge_point_by_id(kp_id, user_id)` 校验，且其 `material_id` 属于该文件夹未归档资料；否则 `KnowledgeNotFoundError`。
     - 缺省：`question_repo.list_knowledge_points_for_folder(user_id, folder_id)`；为空 → 明确异常（`KnowledgeNotFoundError` 或专用「文件夹无可用考点」）。
  3. 按 `(material_id, version_id)` 分组（保序）。
  4. 题量：`group_counts = distribute_count(options.count, len(groups))`；每组内再 `distribute_count(group_count, len(group_kps))`。
  5. 逐组调用 `generate_questions_for_knowledge_points(..., defer_commit=True)`（或直接逐考点 `generate_questions(..., defer_commit=True)` 以复用均分逻辑），聚合结果。
  6. 全部成功 → `self.session.commit()`；任一异常 → `self.session.rollback()` 并 re-raise。
  7. 返回 `MultiKnowledgePointGenerationResult`（`material_id` 取首个分组资料；`knowledge_point_ids` 为全量去重保序）。

### 5.2 `app/services/practice.py`
- `_assemble_and_persist_practice`：`material_id` 允许为空；落库 `folder_id`。
- 抽题范围：`options.folder_id` 非空时，先解析该文件夹未归档资料的全部考点（缺省 `knowledge_point_ids` 来源），再走既有按考点轮转抽题逻辑；若显式给了 `knowledge_point_ids` 则校验其资料属于该文件夹。
- 题量门禁逻辑不变（不足抛 `PracticeEmptyQuestionsError`）。

## 6. Router

- `app/api/v1/questions.py`：
  - `POST /questions/generate`：`payload.folder_id` 非空 → 调 `generate_questions_for_folder`；否则走既有单/多考点链路（零回归）。
  - `GET /questions`：新增 Query `folder_id`，透传 service/repo。
- `app/api/v1/practices.py`：`create_practice` 透传 `folder_id` 到 `CreatePracticeOptions`（新增字段）。

## 7. 归档一致性（与 C1 口径对齐）

- folder 范围出题/组卷/题目列表一律排除归档课程资料（`MaterialFolder.archived_at IS NOT NULL`）。
- 未分类资料（`folder_id IS NULL`）不参与任何 folder 范围；其单资料路径不受影响。

## 8. 测试

- `tests/unit/services/test_question_service.py`（或新增 `test_question_folder_generation.py`）：跨资料分组出题、题量分配、单事务原子（某组失败 → 零落库）、缺省范围、显式跨资料考点校验、归档课程排除、单资料零回归。
- `tests/unit/services/test_practice_service.py`：folder 范围组卷（material_id 空、folder_id 落库）、缺省考点、题量不足、归档排除。
- `tests/unit/repositories/test_question_repo.py`：`folder_id` 过滤 + `list_knowledge_points_for_folder`。
- `tests/unit/api/test_question_router.py` / `test_practice_router.py`：generate/list folder 参数、create folder 参数与响应契约。
- 迁移 0006 upgrade/downgrade 对称（SQLite）。

## 9. 风险

- **原子性**：跨组必须单事务；需确保 `generate_questions` 内部 `flush` 不 `commit`（沿用既有 `defer_commit` 约定）。
- **material_id 放开**：全量回归所有读取 `practice.material_id` 的路径（列表过滤、详情、报告、诊断），确认 `None` 不触发 NPE。
- **knowledge_point 归属校验**：显式 kp 的 `material_id` 必须在目标文件夹内，避免跨课程越界。
