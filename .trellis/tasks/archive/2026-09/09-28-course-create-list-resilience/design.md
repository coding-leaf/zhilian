# 设计：课程创建与资料列表健壮化（C1）

> 详见父任务 `../09-28-course-qgen-frontend-diag/design.md` §2。本文件仅记录本子任务的落地细节。

## 后端

- `FolderRepository.name_exists`：增加 `MaterialFolder.archived_at.is_(None)`，仅活跃同名冲突（`backend/app/repositories/folder.py`）。
- `MaterialFolder.__table_args__`：`UniqueConstraint(user_id, name)` → 部分唯一 `Index("uq_material_folders_user_name_active", "user_id", "name", unique=True, sqlite_where=text("archived_at IS NULL"), postgresql_where=text("archived_at IS NULL"))`（`backend/app/models/material.py`）。
- 迁移 `0007_folder_active_name_unique.py`：`upgrade` drop `uq_material_folders_user_name` + 建部分唯一索引；`downgrade` 反向。SQLite/PG 双 `where`。

## 前端

- `CourseCreateDialog.vue`：新增 `submitting?: boolean` prop；按钮 `:disabled="!isValid || submitting"`，提交中文案"创建中..."。
- `CourseListSection.vue`：
  - `const creating = ref(false)`；`handleCreateConfirm` 首行 `if (creating.value) return;`。
  - 成功：`const created = await createFolder({name}); folderStore`/本地乐观插入（emit('changed') 仍保留以同步服务端）。失败：`err instanceof AppError && (err.code === 40021 || err.status === 409)` → 「课程名称已存在」；否则通用。
  - 透传 `:submitting="creating"` 给对话框。
- `subpackages/material/pages/course/index.vue`：
  - 新增 `listError = ref(false)`；`loadMaterials` 成功 `listError=false`，失败 `listError=true`（保留 toast）。
  - 模板：`loading` → 加载态；`listError` → 错误态 + 「重试」按钮（调 `refreshAll`）；`listData.length===0` → 空态；否则列表。
  - `handleMoveSelect` 成功后 `await refreshAll()`（替换仅 `loadFolder()`）。
- `pages/index/index.vue:loadDashboardData`：`foldersRes.status === 'rejected'` 时保留现有列表，不调用 `setFolderList([])`；可选轻量错误提示。

## 测试

- 后端：`repositories/folder` 单测（归档同名 `name_exists` false / 创建成功；活跃同名 409）；迁移三向（SQLite）。
- 前端：`CourseListSection.spec`（连点仅 1 次 createFolder；409 文案）；`coursePage.spec`（失败 → error 态 + 重试；移动后刷新）；`index.spec`（folders 失败不清空）。
