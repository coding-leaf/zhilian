# 后端·课程文件夹实体、归档与资料归属（迁移 0005）

## Goal

新增单层「课程文件夹」实体，让学习资料可归属课程（`folder_id` 可空 = 未分类）；提供课程 CRUD、归档 / 恢复 / 7 天惰性清理、资料按课程过滤与移动。作为 C2（文件夹范围出题/组卷）与 C3（前端课程 IA）的后端基座。

## 依赖与前置

- **无前置**。上位契约为父任务 `09-27-course-folder-practice-loop/design.md`（§2、§3.1、§3.2、§3.5）。
- 父任务 D5：存量数据清空，本任务仅做 DDL，无回填/迁移。

## Requirements

- R1：新增表 `material_folders` 与模型 `MaterialFolder`（`user_id / name / parent_id(预留) / sort_order / archived_at`）。
- R2：`materials` 新增 `folder_id`（可空 FK → `material_folders.id`，`ON DELETE SET NULL`）。
- R3：迁移 `0005`（`upgrade()` + 对称 `downgrade()`）。
- R4：`/folders` CRUD：POST 创建 / GET 列表（含聚合计数）/ GET 详情 / PATCH 重命名 / DELETE 归档 / POST `/restore` 恢复 / DELETE `/purge` 立即清理。
- R5：归档课程默认从列表隐藏；其下资料在查询层随课程隐藏。
- R6：**惰性清理**：任意列表/详情查询时，对 `archived_at < now - 7d` 的课程执行物理级联删除。
- R7：`POST /materials/upload` 支持可选 `folder_id`；`GET /materials` 支持 `folder_id` 过滤（含未分类 `__none__`）；资料响应新增 `folder_id`。
- R8：`PATCH /materials/{id}/folder` 移动资料（`folder_id: UUID | null`）。
- R9：多租户隔离：所有仓储方法强制 `user_id` 过滤，越权返回 404。

## Acceptance Criteria

- [ ] AC1：迁移可 `upgrade` 与 `downgrade`（对称），建表与加列正确。
- [ ] AC2：课程 CRUD 正常；列表返回 `material_count / ready_material_count / knowledge_point_count / question_count / last_practice_at`；同用户重名返回 409；访问他人课程返回 404。
- [ ] AC3：归档写 `archived_at`、列表默认不含、`purge_after = archived_at + 7d`；`/restore` 清空 `archived_at` 后恢复可见。
- [ ] AC4：`archived_at` 超 7 天的课程在查询时被物理删除，其资料/版本/切片/知识点/题目级联清除。
- [ ] AC5：上传可选 `folder_id`（缺省落未分类）；列表可按 `folder_id`（含 `__none__`）过滤；资料响应含 `folder_id`。
- [ ] AC6：`PATCH /materials/{id}/folder` 可在未分类 ↔ 课程间移动；目标课程须归属当前用户且未归档，否则 4xx。
- [ ] AC7：后端全工具链绿（`ruff format --check` / `ruff check` / `mypy app` / `lint-imports` / `pytest`）。

## Out of Scope

- 多层嵌套文件夹（`parent_id` 仅预留、恒 NULL）。
- 归档的独立粒度（本期以「课程」为归档单元）。
- 批量移动接口（前端循环调用即可）。

## Notes

- 命名沿用既有约定：表复数下划线、模型 PascalCase、缩写白名单 `api,id,url,ocr,llm,db,config,env`。
- 错误语义复用 `app/core/errors.py`；新增 `FolderNotFoundError`（404）/`FolderNameConflictError`（409）。
