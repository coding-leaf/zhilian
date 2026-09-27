# 实施计划：课程创建与资料列表健壮化（C1）

## 后端
- [ ] 修改 `repositories/folder.py:name_exists` 排除归档。
- [ ] 修改 `models/material.py:__table_args__` 为部分唯一索引。
- [ ] 新增迁移 `0007`（对称）。
- [ ] 新增/更新单测。
- [ ] `task test-backend` → `task verify-backend`。

## 前端
- [ ] `CourseCreateDialog.vue` submitting 禁用。
- [ ] `CourseListSection.vue` 提交锁 + 乐观插入 + 409 文案 + 透传 submitting。
- [ ] 课程页三态 + 移动后 `refreshAll()`。
- [ ] 首页 folders 失败兜底。
- [ ] 新增/更新单测。
- [ ] `task verify-frontend`。

## 验收
- [ ] 连点仅 1 POST；无"创建失败"误报。
- [ ] 活跃同名 409 提示"已存在"；归档同名可创建。
- [ ] 课程页失败显示错误态可重试。
- [ ] 迁移 0007 三向通过。
