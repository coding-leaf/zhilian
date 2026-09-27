# 实施计划：前端·课程 IA、未分类与归档

## 顺序清单

- [ ] 1. `src/types/material.ts`：`MaterialItem.folder_id`、`MaterialListQueryParams.folder_id`。
- [ ] 2. `src/types/folder.ts` + `src/api/folder.ts`：FolderItem 与 6 个接口。
- [ ] 3. `src/api/material.ts`：`uploadMaterial` 加 `folderId`；新增 `moveMaterialFolder`。
- [ ] 4. `src/utils/`：`formatPurgeRemaining` 纯函数。
- [ ] 5. `src/stores/folderStore.ts`（+ materialStore 扩展移动后剔除）。
- [ ] 6. 组件：`CourseCard.vue`、`ArchivedCourseItem.vue`、`CourseCreateDialog.vue`、`CourseRenameDialog.vue`、`MoveMaterialSheet.vue`、`CourseListSection.vue`。
- [ ] 7. `pages/index/index.vue`：移除 `MasteryDashboardBar`；接入课程列表/未分类/已归档/快捷上传/最近学习。
- [ ] 8. 新增 `subpackages/material/pages/course/index` + `pages.json` 注册（material 分包）。
- [ ] 9. `subpackages/material/pages/list/index`：`folder_id`（含 `__none__`）过滤 + 移动入口。
- [ ] 10. `MaterialUpload` / `QuickUploadBar`：支持 `folderId`（缺省落未分类）。
- [ ] 11. 单测：utils/store/组件/控制台去总分卡断言。
- [ ] 12. 前端全门禁绿。

## 验证命令（`miniprogram/`）

```
pnpm run lint
pnpm run type-check
pnpm run test:unit
pnpm run build:mp-weixin
```

## 评审门禁

- [ ] `lint` / `type-check` / `test:unit` / `build:mp-weixin` 全绿。
- [ ] 组件行数 ≤300；零 Emoji；导航参数统一 `material_id` 且带 `fail` 兜底。
- [ ] 归档/移动/未分类交互单测覆盖。
- [ ] 前端课程导航与归档契约写入 `.trellis/spec/frontend/quality-guidelines.md`。

## 风险与回滚

- 控制台去总分卡后确保报告页 `fetchMasteryOverview` 仍可用（不删后端能力）。
- 首页/列表页行数接近上限 → 拆子组件。
- 回滚：前端页面与组件可独立回退，不影响后端（字段可空、向后兼容）。
