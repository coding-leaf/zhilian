# 技术设计：前端·课程 IA、未分类与归档

> 上位契约：父任务 `design.md` §3.1/§3.2/§3.5、§4.1；依赖 C1 后端 API。

## 1. 类型与 API 契约

### 1.1 `src/types/material.ts`
- `MaterialItem` 增 `folder_id?: string | null`。
- `MaterialListQueryParams` 增 `folder_id?: string`（`'__none__'` 表示未分类）。

### 1.2 `src/types/folder.ts`（新增）
```ts
export interface FolderItem {
  id: string;
  name: string;
  parent_id?: string | null;
  sort_order?: number;
  is_archived: boolean;
  archived_at?: string | null;
  purge_after?: string | null;
  material_count: number;
  ready_material_count: number;
  knowledge_point_count: number;
  question_count: number;
  last_practice_at?: string | null;
  created_at: string;
  updated_at?: string;
}
export interface FolderListQuery { include_archived?: boolean }
```

### 1.3 `src/api/folder.ts`（新增）
| 函数 | 方法/路径 |
|---|---|
| `fetchFolderList({include_archived})` | `GET /api/v1/folders` |
| `fetchFolderDetail(id)` | `GET /api/v1/folders/{id}` |
| `createFolder({name})` | `POST /api/v1/folders` |
| `renameFolder(id,{name})` | `PATCH /api/v1/folders/{id}` |
| `archiveFolder(id)` | `DELETE /api/v1/folders/{id}` |
| `restoreFolder(id)` | `POST /api/v1/folders/{id}/restore` |

### 1.4 `src/api/material.ts`
- `uploadMaterial(...)` 增 `folderId?: string`，真机分支 `formData.folder_id`、非真机 `data.folder_id`。
- 新增 `moveMaterialFolder(materialId, folderId: string | null)` → `PATCH /api/v1/materials/{id}/folder`，body `{folder_id}`。
- `fetchMaterialList` 已透传 params（`folder_id` 自动携带）。

## 2. Store（不发请求）

- 新增 `src/stores/folderStore.ts`：`folders`、`archivedFolders`、`unclassifiedCount`、`currentFolder`；actions：`setFolders`、`setArchivedFolders`、`upsertFolder`、`removeFolder`、`setCurrentFolder`、`reset`。
- `materialStore` 扩展：`unclassifiedMaterials` 或复用 `materials`（按 `folder_id` 过滤）；`removeMaterial(id)`（移动后剔除）。
- 铁律：Store 内严禁发网络请求，全部经组件调用 `src/api/`。

## 3. 页面与路由

| 变更 | 路径 | 说明 |
|---|---|---|
| 改 | `pages/index/index.vue` | 移除 `MasteryDashboardBar`；课程列表入口 + 未分类 + 已归档 + 快捷上传 + 最近学习 |
| 新增 | `subpackages/material/pages/course/index` | 课程详情：课程内资料 + 上传（归属课程）+ 移动资料 + 出题/题目入口（C4 占位） |
| 改 | `subpackages/material/pages/list/index` | 支持 `folder_id`（含 `__none__`）过滤；未分类视图提供「移动到课程」 |
| 新增组件 | `components/home/CourseCard.vue` / `components/course/*` | 课程卡片、归档项、移动选择器 |

- `pages.json` 在 `subpackages/material` 注册 `pages/course/index`（标题如「课程详情」）。
- 导航契约：统一 `material_id`；`navigateTo` 必带 `fail` 兜底；课程详情带 `folder_id`。

## 4. 组件拆分（≤300 行）

- `CourseCard.vue`：名称、资料数/考点数/题目数、最近练习、进入按钮。
- `ArchivedCourseItem.vue`：归档课程 + 剩余反悔时间 + 恢复按钮。
- `CourseCreateDialog.vue` / `CourseRenameDialog.vue`：名称输入与校验。
- `MoveMaterialSheet.vue`：选择目标课程（含「移出到未分类」）。
- 控制台课程区块抽为 `components/home/CourseListSection.vue`，避免 `index.vue` 超行数。

## 5. 归档交互

- 归档：`DELETE /folders/{id}` → 主列表移除，toast 提示「已归档，7 天内可恢复」。
- 已归档列表：`include_archived=true`，展示 `purge_after` 距今剩余天数；恢复走 `POST /folders/{id}/restore`。
- 剩余时间纯函数 `formatPurgeRemaining(purgeAfter, now)` 放 `utils/`，单测覆盖。

## 6. 未分类与移动

- 未分类 = `folder_id IS NULL`；列表 `fetchMaterialList({folder_id: '__none__'})`。
- 移动：`MoveMaterialSheet` 选目标课程 → `moveMaterialFolder(id, folderId|null)` → 本地 store 剔除 + 列表刷新。

## 7. 测试

- `utils`：`formatPurgeRemaining` 边界（已过期/剩余/非法）。
- Store：`folderStore` 增删改状态；`materialStore` 移动后剔除。
- 组件：`CourseCard` 渲染计数与命中事件；`MoveMaterialSheet` 选择与取消。
- 页面：控制台断言**不再渲染** `MasteryDashboardBar`（去总分卡）；课程列表空态；归档项恢复触发。
- 门禁：`pnpm run lint` / `type-check` / `test:unit` / `build:mp-weixin`。

## 8. 风险

- 控制台改造可能触碰首页概览 `fetchMasteryOverview`；**仅移除展示卡**，报告页仍使用该能力。
- 分包导航参数漂移（C3 引入 `folder_id`）→ 统一参数名并在 spec 记录。
- `pages/index/index.vue` 与列表页行数接近上限 → 拆子组件。
