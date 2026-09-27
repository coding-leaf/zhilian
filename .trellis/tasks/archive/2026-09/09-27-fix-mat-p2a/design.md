# 技术设计：MAT 切片 P2-A 修复（005-011）

## 1. 背景与根因

### BUG-MAT-005: 文件大小校验双端规则漂移
- **文件与行号**：前端 `miniprogram/src/utils/file.ts:12-13`；后端 `backend/app/services/material.py:68-77`。
- **根因**：前端写死 `const MAX_FILE_SIZE = 20 * 1024 * 1024;`（20MB），未根据文档类型区分；而后端按格式严格控制（图片 10MB，纯文本 5MB，文档 20MB）。15MB 的 JPG 文件可以通过前端校验，但会被后端拒绝并导致用户感知到不明确的报错。
- **修复方案**：前端声明 `MAX_FILE_SIZES: Record<string, number>` 映射表对齐后端，并在 `validateMaterialFile` 中结合后缀取对应上限。

### BUG-MAT-006: 允许格式范围收窄
- **文件与行号**：前端 `miniprogram/src/utils/file.ts:12`；后端 `backend/app/models/material.py:60-68`。
- **根因分析**：后端底座支持 pptx/txt/md，但微信小程序端因移动端选文交互及渲染限制，设计上限定为 pdf、docx、图片。属于既定设计收窄，非意外遗漏。
- **方案**：保持白名单收窄范围，在代码注释中补充与后端子集的映射说明，并在测试用例中明确预期断言，标记为已确认非缺陷。

### BUG-MAT-007: retakeMaterialPage 响应类型契约漂移
- **文件与行号**：前端 `miniprogram/src/types/material.ts:93-98`、`miniprogram/src/api/material.ts:197-223`；后端 `backend/app/schemas/material.py:164-175`。
- **根因**：后端真实重拍接口响应 DTO 为 `MaterialReshootResponse`（包含 `material_id, version_id, page_index, is_qualified, reshoot_count, parse_status, unqualified_reason`），而前端早期使用了 `RetakePageResponse`（`page_no, status, message`），字段完全不对齐。
- **修复方案**：前端统一 `retakeMaterialPage` 返回类型为 `MaterialReshootResponse`，淘汰 `RetakePageResponse`，并更新 API 单元测试中的 mock 数据。

### BUG-MAT-008: 知识点树切换资料时状态未重置
- **文件与行号**：前端 `miniprogram/src/stores/materialStore.ts:88-90,134-141`；`miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue:136-150,197-209`。
- **根因**：用户由资料 A 切换到资料 B 时，`initData` 仅调用 `setActiveMaterial` 并请求新树，但 `selectedKnowledgeIds` 与 `knowledgeTreeCollapsedMap` 未被清空，导致覆盖率和出题考点选择携带了上一资料的历史 ID。
- **修复方案**：在 `materialStore` 中提供 `clearKnowledgeState()` 方法（清空树节点、选中项、折叠状态）；并在 `knowledge-tree/index.vue` 进入新资料时调用。

### BUG-MAT-009: 知识树缺乏向上联动与父节点半选态
- **文件与行号**：前端 `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue:77-93`；`miniprogram/src/subpackages/material/utils/tree.ts:80-95`。
- **根因**：目前复选框判定仅看 `selectedIds.includes(node.id)`，子节点全选/部分选时无法联动更新父节点的视觉与选中状态。
- **修复方案**：
  1. 在 `tree.ts` 中实现节点勾选状态判定函数 `getNodeCheckStatus(node, selectedIdsSet)`，根据当前节点的所有叶子/子孙节点的勾选比例，返回 `'checked' | 'indeterminate' | 'unchecked'`。
  2. `KnowledgeTreeNode.vue` 中支持 `indeterminate` 状态渲染（例如：自定义 CSS 横杠或减号图标）。
  3. 点击交互：若当前状态为 `indeterminate` 或 `unchecked`，点击后将其自身及全部子孙节点加入选中集合；若为 `checked`，则将其自身及全部子孙节点从选中集合中移除。

### BUG-MAT-010: 资料列表分页追加无 ID 去重
- **文件与行号**：前端 `miniprogram/src/subpackages/material/pages/list/index.vue:190-194,279-284`。
- **根因**：`loadData(false)` 时直接使用 `listData.value = [...listData.value, ...items]`，若在触底时后台有资料插入或删除导致分页偏移，相同 ID 的资料会被多次添加到列表中，造成 Vue 渲染 `:key` 冲突及页面重复显示。
- **修复方案**：与 `questions/index.vue` 一致，在追加前基于 `Set` 过滤已存在的 ID：
  ```ts
  const existingIds = new Set(listData.value.map((item) => item.id));
  const newItems = items.filter((item) => !existingIds.has(item.id));
  listData.value = [...listData.value, ...newItems];
  ```

### BUG-MAT-011: 资料列表首屏生命周期重复触发
- **文件与行号**：前端 `miniprogram/src/subpackages/material/pages/list/index.vue:286-306`。
- **根因**：页面加载时 `onMounted` 和 `onShow` 均调用了 `loadData(true)`，异步请求由于事件循环时差可能几乎同时发出；且每次返回前台均强制全表刷为第 1 页。
- **修复方案**：
  引入 `isInitialLoaded` 状态标记：首屏由 `onMounted`（或首个 `onShow`）加载；`onShow` 判断若已有首屏数据，则按需同步（例如仅在处于第一页或特定返回标记时刷新），避免初次挂载时的重复请求并发。

---

## 2. 契约设计与兼容性

### 2.1 契约权威对齐
- **重拍接口返回类型**：严格采用后端 `MaterialReshootResponse`（`schemas/material.py`）：
  ```ts
  export interface MaterialReshootResponse {
    material_id: string;
    version_id?: string;
    page_index: number;
    is_qualified: boolean;
    reshoot_count: number;
    parse_status: string;
    unqualified_reason?: string | null;
  }
  ```
- **文件大小限制表**：
  ```ts
  export const MAX_FILE_SIZES: Record<string, number> = {
    pdf: 20 * 1024 * 1024,
    docx: 20 * 1024 * 1024,
    png: 10 * 1024 * 1024,
    jpg: 10 * 1024 * 1024,
    jpeg: 10 * 1024 * 1024,
  };
  export const DEFAULT_MAX_FILE_SIZE = 20 * 1024 * 1024;
  ```

### 2.2 兼容性与回滚
- **兼容性**：
  - `MaterialReshootResponse` 是对错误 `RetakePageResponse` 的修正，前端之前并未实际深层使用 `RetakePageResponse` 的独有字段，改动不会破坏现有交互。
  - 知识树勾选与半选完全由纯函数驱动，历史持久化或外部 API 不受负面影响。
- **回滚机制**：
  - 各缺陷修复均属于前端独立模块（文件工具、API 声明、Pinia Store、页面生命周期），无不可逆数据库变动，可通过 git revert 快速回滚。

---

## 3. 影响文件清单

### 前端
- `miniprogram/src/utils/file.ts`（文件体积表与格式子集规范）
- `miniprogram/src/types/material.ts`（废除 RetakePageResponse，统一 MaterialReshootResponse）
- `miniprogram/src/api/material.ts`（retakeMaterialPage 泛型修正）
- `miniprogram/src/stores/materialStore.ts`（新增 clearKnowledgeState，状态清空）
- `miniprogram/src/subpackages/material/utils/tree.ts`（半选推导纯函数）
- `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue`（半选视觉与勾选逻辑）
- `miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue`（切换资料时清空 store 考点状态）
- `miniprogram/src/subpackages/material/pages/list/index.vue`（分页去重、首屏去重）

### 测试
- `miniprogram/tests/unit/components/MaterialUpload.spec.ts`（测试不同格式文件大小校验边界）
- `miniprogram/tests/unit/api/material.spec.ts`（测试重拍返回模型结构）
- `miniprogram/tests/unit/stores/materialStoreTree.spec.ts`（测试 clearKnowledgeState）
- `miniprogram/tests/unit/materialTreeUtils.spec.ts`（测试树节点半选推导函数）
- `miniprogram/tests/unit/components/KnowledgeTreeNode.spec.ts`（测试半选节点视觉与点击行为）
- `miniprogram/tests/unit/pages/materialList.spec.ts`（测试分页去重与首屏重复请求防护）
