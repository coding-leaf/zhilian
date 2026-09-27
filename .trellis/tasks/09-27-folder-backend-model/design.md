# 技术设计：后端·课程文件夹实体、归档与资料归属

> 上位契约：`09-27-course-folder-practice-loop/design.md`（§2、§3.1、§3.2、§3.5）。本文件细化到可实施粒度。

## 1. 数据模型

### 1.1 `MaterialFolder`（新表 `material_folders`，`app/models/material.py`）

继承 `Base, TimestampMixin, TenantModelMixin`。

| 字段 | 类型 | 约束 |
|---|---|---|
| id | UUID | PK, default uuid4 |
| user_id | UUID | 来自 TenantModelMixin（FK users, CASCADE, index） |
| name | String(100) | NOT NULL |
| parent_id | UUID | FK `material_folders.id` ON DELETE CASCADE, nullable, default None（本期恒 NULL，预留） |
| sort_order | Integer | NOT NULL, default 0 |
| archived_at | DateTime(timezone=True) | nullable, default None, index |

- `__table_args__`：`UniqueConstraint("user_id", "name", name="uq_material_folders_user_name")`；`Index("ix_material_folders_user_archived", "user_id", "archived_at")`。
- 关系：`materials: Mapped[list["Material"]]`（`back_populates="folder"`，`foreign_keys="Material.folder_id"`，不设 delete-orphan，避免误删资料）。

### 1.2 `Material` 增加 `folder_id`

- `folder_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("material_folders.id", ondelete="SET NULL"), nullable=True, default=None, index=True, comment="所属课程文件夹 (NULL=未分类)")`。
- 关系：`folder: Mapped["MaterialFolder | None"] = relationship("MaterialFolder", back_populates="materials", foreign_keys=[folder_id])`。
- `__table_args__` 增加 `Index("ix_materials_user_folder_deleted", "user_id", "folder_id", "is_deleted")`。
- 导出：`app/models/__init__.py` 增加 `MaterialFolder`。

## 2. 迁移 `0005_create_material_folders`

- `down_revision = "0004_add_practice_mode"`；`revision = "0005_create_material_folders"`。
- `upgrade()`：
  1. `op.create_table("material_folders", ...)`：id, user_id(FK users CASCADE), name, parent_id(FK self CASCADE, nullable), sort_order(default 0), archived_at(nullable), created_at/updated_at，含唯一约束 `uq_material_folders_user_name`。
  2. 索引：`ix_material_folders_user_id`（TenantModelMixin index）、`ix_material_folders_user_archived`、`ix_material_folders_archived_at`。
  3. `batch_alter_table("materials")` 加列 `folder_id`（nullable, FK `material_folders.id` ON DELETE SET NULL）+ 索引 `ix_materials_folder_id` + 复合索引 `ix_materials_user_folder_deleted`。
- `downgrade()`：drop 复合索引/`folder_id` 列（batch），drop `material_folders` 表（含索引）。
- 兼容 SQLite batch 模式（沿用 0004 的 `op.batch_alter_table` 风格）。

## 3. Schemas（`app/schemas/folder.py`）

- `FolderCreateRequest { name: str(1..100) }`
- `FolderUpdateRequest { name: str(1..100) }`
- `FolderDetailResponse { id, name, parent_id, sort_order, is_archived: bool, archived_at: datetime|None, purge_after: datetime|None, material_count: int, ready_material_count: int, knowledge_point_count: int, question_count: int, last_practice_at: datetime|None, created_at, updated_at }`
- `FolderListResponse { items: list[FolderDetailResponse], total: int }`
- `FolderDeleteResponse { id, is_deleted: bool, archived_at, purge_after, message }`

`MaterialListItem` / `MaterialDetailResponse`（`app/schemas/material.py`）新增 `folder_id: uuid.UUID | None = None`。

## 4. Repository（`app/repositories/folder.py`，方法强制 `user_id`）

- `create(*, user_id, name, parent_id=None, sort_order=0) -> MaterialFolder`
- `get_by_id(folder_id, user_id, *, include_archived=False) -> MaterialFolder | None`
- `list_by_user(user_id, *, include_archived=False, limit, offset) -> tuple[list[MaterialFolder], int]`
- `update_name(folder_id, user_id, name) -> MaterialFolder`
- `archive(folder_id, user_id, archived_at) -> MaterialFolder`
- `restore(folder_id, user_id) -> MaterialFolder`
- `list_expired(user_id, *, before: datetime) -> list[MaterialFolder]`（`archived_at < before`）
- `name_exists(user_id, name, *, exclude_id=None) -> bool`
- 聚合计数由 `folder_service` 组合查询（见 §5），或在仓储加 `count_materials / count_ready / count_knowledge_points / count_questions / last_practice_at`（推荐仓储提供计数方法，service 组装）。

`MaterialRepository` 扩展：
- `create_material(..., folder_id: uuid.UUID | None = None)`
- `list_materials(..., folder_id: uuid.UUID | None = None, unclassified: bool = False)`
- `move_folder(material_id, user_id, folder_id) -> Material`
- 列表/详情 join `MaterialFolder` 过滤 `archived_at IS NULL`（未分类 `folder_id IS NULL` 不受影响）。

## 5. Service（`app/services/folder.py`）

- `create_folder(user_id, name)`：`name_exists` → `FolderNameConflictError(409)`；否则创建。
- `list_folders(user_id, include_archived=False, ...)`：先 `_purge_expired(user_id)`，再查列表并组装聚合计数。
- `get_folder(user_id, folder_id)`：`_purge_expired` 后取详情；不存在/越权 → `FolderNotFoundError(404)`。
- `rename_folder(user_id, folder_id, name)`：重名校验（排除自身）。
- `archive_folder(user_id, folder_id)`：写 `archived_at=now`；返回 `purge_after=+7d`。
- `restore_folder(user_id, folder_id)`：`archived_at=None`。
- `purge_folder(user_id, folder_id)`：物理删除（先解绑/级联删除其下资料，复用 `MaterialService.hard_delete_material` 逐个）。
- `_purge_expired(user_id)`：`list_expired(user_id, before=now-7d)` → 逐个物理级联删除。
- `move_material(user_id, material_id, folder_id | None)`：目标课程存在、归属且未归档，否则 404/409。
- 聚合计数口径：`material_count`（is_deleted=False 且课程未归档）、`ready_material_count`（status=ready）、`knowledge_point_count`（该课程资料下知识点数）、`question_count`、`last_practice_at`（该课程资料相关练习最大 created_at 或 None）。

## 6. Router（`app/api/v1/folders.py` + `app/api/deps/folder.py`）

| 方法 | 路径 | 处理 |
|---|---|---|
| POST | `/folders` | `create_folder` |
| GET | `/folders` | `list_folders(include_archived)` |
| GET | `/folders/{folder_id}` | `get_folder` |
| PATCH | `/folders/{folder_id}` | `rename_folder` |
| DELETE | `/folders/{folder_id}` | `archive_folder` → `FolderDeleteResponse` |
| POST | `/folders/{folder_id}/restore` | `restore_folder` |
| DELETE | `/folders/{folder_id}/purge` | `purge_folder` |

- 路由层仅做协议解析/调用 service/转换；`deps/folder.py` 仿 `deps/material.py` 从 `request.app.state.container.create_folder_service(session)` 装配。
- `container.py` 增加 `create_folder_service(session) -> FolderService`（+ 兼容别名 `get_folder_service`）。
- `materials.py`：`upload_material` 增 `folder_id: Annotated[uuid.UUID | None, Form()] = None`；`list_materials` 增 `folder_id`（`__none__` → `unclassified=True`）；`MaterialListItem/DetailResponse` 传 `folder_id`；新增 `PATCH /materials/{material_id}/folder`（body `{folder_id: UUID | None}`）。
- `app/api/v1/__init__.py` 或 main 路由注册处挂载 `folders.router`。
- 错误：`app/core/errors.py` 新增 `FolderNotFoundError` / `FolderNameConflictError` 与对应错误码。

## 7. 归档过滤口径（关键，写入 spec）

- 课程列表：默认 `archived_at IS NULL`；`include_archived=True` 时返回归档课程（供「已归档」页）。
- 资料列表/详情：若 `material.folder_id` 指向归档课程 → 默认隐藏；未分类不受影响。
- 出题/组卷/题目列表的范围（C2）：仅纳入未归档课程的资料。
- 惰性清理触发点：`list_folders` / `get_folder` 入口。

## 8. 测试

- `tests/unit/models/test_material_folder.py`：字段/约束/关系/唯一键。
- `tests/unit/repositories/test_folder_repo.py`：CRUD、list 过滤、name_exists、list_expired。
- `tests/unit/services/test_folder_service.py`：创建重名 409、越权 404、归档/恢复、惰性清理（构造 archived_at=now-8d 断言物理删除+资料级联）、聚合计数、移动资料。
- `tests/unit/api/test_folder_router.py`：各端点 HTTP 状态与响应契约；上传带/不带 folder_id；列表 `__none__`；移动端点。沿用现有 `dependency_overrides` 模式。

## 9. 风险

- `ON DELETE SET NULL` 与「归档不删资料」一致；`purge` 才物理删除。需确认 SQLite 测试下 FK 行为（沿用现有 fixture 约定）。
- 聚合计数避免 N+1：用聚合查询而非逐课程循环。
- 惰性清理在只读 GET 中执行写操作：需在事务提交，避免只读会话异常；明确记录该副作用。
