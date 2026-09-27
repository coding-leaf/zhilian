# 实施计划：后端·课程文件夹实体、归档与资料归属

## 顺序清单

- [ ] 1. `app/models/material.py`：新增 `MaterialFolder`；`Material` 加 `folder_id` + `folder` 关系 + 索引。
- [ ] 2. `app/models/__init__.py`：导出 `MaterialFolder`。
- [ ] 3. `migrations/versions/0005_create_material_folders.py`：建表 + 加列 + 索引；对称 `downgrade()`。
- [ ] 4. `app/core/errors.py`：新增 `FolderNotFoundError` / `FolderNameConflictError`（含错误码）。
- [ ] 5. `app/schemas/folder.py`：Create/Update/Detail/List/Delete 模型；`schemas/material.py` 加 `folder_id`。
- [ ] 6. `app/repositories/folder.py`：CRUD + `list_expired` + `name_exists` + 聚合计数方法。
- [ ] 7. `app/repositories/material.py`：`create_material(folder_id=...)`、`list_materials(folder_id/unclassified)`、`move_folder`、归档过滤。
- [ ] 8. `app/services/folder.py`：CRUD、归档/恢复、`_purge_expired` 惰性清理、聚合计数组装、移动资料。
- [ ] 9. `app/container.py`：`create_folder_service` + `get_folder_service`。
- [ ] 10. `app/api/deps/folder.py` + `app/api/v1/folders.py`；注册路由。
- [ ] 11. `app/api/v1/materials.py`：upload `folder_id`、list `folder_id`/`__none__`、响应 `folder_id`、`PATCH /materials/{id}/folder`。
- [ ] 12. 单测：model / repo / service / router（见 design.md §8）。
- [ ] 13. 全工具链绿。

## 验证命令（`backend/`）

```
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run lint-imports
uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
```

## 评审门禁

- [ ] 回归测试先红后绿（新增单测覆盖重名/越权/归档/惰性清理/移动）。
- [ ] 全工具链绿。
- [ ] 归档过滤口径与「惰性清理副作用」写入 `.trellis/spec/backend/quality-guidelines.md`。

## 风险与回滚

- 惰性清理在 GET 中写库 → 确保提交事务；若异常不影响查询返回（降级为不清理）。
- `ON DELETE SET NULL` 与 SQLite 测试 FK 行为 → 与现有 fixture 对齐。
- 回滚：迁移 `downgrade()`；移除路由/服务即可退回无文件夹状态。
