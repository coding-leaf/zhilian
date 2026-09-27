# 前端·课程 IA、未分类与归档

## Goal

把前端信息架构从「扁平资料列表 + 总学习分」改为「课程文件夹」：控制台首屏为课程列表入口（含未分类 / 已归档），提供课程详情页、文件夹增删改归档恢复、资料上传归属与移动，并**移除总学习分卡**。依赖 C1 后端。

## 依赖与前置

- **依赖 C1**（已归档）：`/folders` CRUD + 归档/恢复、`materials.folder_id`、`PATCH /materials/{id}/folder`、上传/列表 `folder_id`。
- 上位契约：父任务 `09-27-course-folder-practice-loop/design.md` §3.1/§3.2/§3.5、§4.1。
- 前端规范：`.trellis/spec/frontend/quality-guidelines.md`（组件 ≤300 行、Store 不发请求、分包导航参数契约、零 Emoji、DESIGN.md token）。

## Requirements

- R1 契约：`MaterialItem` 增 `folder_id?: string | null`；`MaterialListQueryParams` 增 `folder_id?: string`（含 `__none__`）；`uploadMaterial` 增 `folderId` 参数（formData `folder_id`）；新增 `moveMaterialFolder(materialId, folderId | null)` → `PATCH /materials/{id}/folder`。
- R2 新增 `src/api/folder.ts` + `src/types/folder.ts`：`FolderItem`（id/name/is_archived/archived_at/purge_after/material_count/ready_material_count/knowledge_point_count/question_count/last_practice_at）+ `fetchFolderList({include_archived})`/`createFolder`/`renameFolder`/`archiveFolder`/`restoreFolder`/`fetchFolderDetail`。
- R3 Store：新增课程状态（folders、当前课程、未分类资料），遵循「Store 不发请求」铁律；或在 `materialStore` 扩展。
- R4 控制台 `pages/index/index.vue`：**移除 `MasteryDashboardBar` 总分卡**；首屏改为课程列表入口；固定「未分类」入口（仅当存在无归属资料）与「已归档」入口；保留快捷上传与最近学习。
- R5 新增课程详情页 `subpackages/material/pages/course/index`（`pages.json` 注册，material 分包）：课程内资料列表 + 上传（归属本课程）+ 移动资料 + 出题/题目入口占位（C4 接线）。
- R6 文件夹 CRUD UI：新建 / 重命名 / 归档 / 恢复；归档项展示剩余反悔时间（`purge_after - now`）。
- R7 未分类资料列表（复用 `material/pages/list`，`folder_id=__none__`）+「移动到课程」；课程内资料亦可移动。
- R8 组件 ≤300 行；零 Emoji；复用 DESIGN.md token；上传未指定课程即落未分类（不阻断）。
- R9 前端全门禁绿：`pnpm run lint` / `type-check` / `test:unit` / `build:mp-weixin`。

## Acceptance Criteria

- [ ] AC1：控制台首屏为课程列表，**无综合掌握度分卡**；含未分类与已归档入口。
- [ ] AC2：可新建课程；进入课程详情可见该课程资料列表与上传入口。
- [ ] AC3：课程内上传归属该课程；未选课程上传落「未分类」。
- [ ] AC4：可将资料在「未分类 ↔ 课程」及课程间移动，列表即时更新。
- [ ] AC5：归档课程从主列表隐藏、进入「已归档」可恢复并显示剩余反悔时间。
- [ ] AC6：前端 `lint`/`type-check`/`test:unit`/`build:mp-weixin` 全绿，新增组件/Store 有单测。

## Out of Scope

- 课程内出题与「开始答题」接线（属 C4）。
- 多层嵌套文件夹、批量移动。
- 与信息架构无关的纯视觉改版。

## Notes

- 导航参数统一 `material_id`（沿用《Material Subpackage Navigation Param Contract》），`navigateTo` 必带 `fail` 兜底。
- 复用现有 `MaterialCard`、`MaterialUpload`、DESIGN.md 组件装配规则。
