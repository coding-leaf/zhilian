# 执行计划：MAT 切片 P2-A 修复（005-011）

## 1. 实施原则与依赖
- **红绿测试原则**：在修改功能代码前，先补充或更新单元测试，明确缺陷断言（先红），修复后全绿。
- **渐进式交付**：按照模块独立性划分执行批次，确保每一项修复都有对应的测试保障。

---

## 2. 有序任务清单

### 阶段一：编写失败回归测试（Red Phase）
- [x] **Step 1.1 (MAT-005/006)**: 在 `miniprogram/tests/unit/components/MaterialUpload.spec.ts` 中添加 15MB 图片被拦截、以及格式子集校验测试用例。（Red 确认：`expected true to be false`）
- [x] **Step 1.2 (MAT-007)**: 在 `miniprogram/tests/unit/api/material.spec.ts` 中更新 `retakeMaterialPage` 测试，断言返回 `MaterialReshootResponse` 结构（包含 `page_index`）。（Red 确认：`type-check` 报 `page_index does not exist on RetakePageResponse`）
- [x] **Step 1.3 (MAT-008)**: 在 `miniprogram/tests/unit/stores/materialStoreTree.spec.ts` 中增加测试用例，验证切换资料时清空知识树、选中项及折叠状态。（Red 确认：`store.clearKnowledgeState is not a function`）
- [x] **Step 1.4 (MAT-009)**: 在 `miniprogram/tests/unit/materialTreeUtils.spec.ts` 与 `KnowledgeTreeNode.spec.ts` 中增加半选态判定及交互测试用例。（Red 确认：`getNodeCheckStatus is not a function`）
- [x] **Step 1.5 (MAT-010/011)**: 在 `miniprogram/tests/unit/pages/materialList.spec.ts` 中添加触底分页去重测试，以及首屏加载去重测试。（Red 确认：`handleReachBottom is not a function`；首屏单请求断言待实现）

### 阶段二：逐项实现与验证（Green Phase）
- [x] **Step 2.1 (MAT-005/006 对齐文件体积与格式规范)**:
  - 编辑 `miniprogram/src/utils/file.ts`，声明 `MAX_FILE_SIZES`（pdf/docx 20MB、png/jpg/jpeg 10MB、`DEFAULT_MAX_FILE_SIZE` 20MB）并更新 `validateMaterialFile` 逻辑与提示语（图片专用文案）。
  - 运行 `pnpm exec vitest run tests/unit/components/MaterialUpload.spec.ts` 验证通过。
- [x] **Step 2.2 (MAT-007 统一重拍响应类型契约)**:
  - 编辑 `miniprogram/src/types/material.ts`（删除 `RetakePageResponse`）与 `miniprogram/src/api/material.ts`（泛型迁移至 `MaterialReshootResponse`）。
  - 更新 `tests/unit/components/RetakeDrawer.spec.ts` 夹具为后端字段。运行 `material.spec.ts` 验证通过。
- [x] **Step 2.3 (MAT-008 知识树状态重置)**:
  - 编辑 `miniprogram/src/stores/materialStore.ts` 添加 `clearKnowledgeState()`。
  - 编辑 `miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue` 的 `initData` 在载入前调用重置。
  - 运行 `tests/unit/stores/materialStoreTree.spec.ts` 验证通过。
- [x] **Step 2.4 (MAT-009 知识树父子半选与向上联动)**:
  - 编辑 `miniprogram/src/subpackages/material/utils/tree.ts` 实现 `getNodeCheckStatus` 半选状态推导函数。
  - 编辑 `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue` 接入 `checked/indeterminate` 状态与半选横杠样式。
  - 运行 `KnowledgeTreeNode.spec.ts` 与 `materialTreeUtils.spec.ts` 验证通过。
- [x] **Step 2.5 (MAT-010 资料列表分页去重)**:
  - 编辑 `miniprogram/src/subpackages/material/pages/list/index.vue`，在追加分页数据时按 ID 去重。
  - 运行 `tests/unit/pages/materialList.spec.ts` 验证通过。
- [x] **Step 2.6 (MAT-011 资料列表首屏去重)**:
  - 编辑 `miniprogram/src/subpackages/material/pages/list/index.vue`，以 `hasShownOnce` 标记让 `onMounted` 独占首屏加载，`onShow` 仅在返回场景刷新。
  - 运行 `tests/unit/pages/materialList.spec.ts` 验证通过。

### 阶段三：全局质量门禁检查（Verify Phase）
- [x] **Step 3.1 前端代码风格与类型检查**:
  - 执行 `pnpm run lint`（0 error）
  - 执行 `pnpm run type-check`（0 error）
- [x] **Step 3.2 前端全量单元测试**:
  - 执行 `pnpm run test:unit`（58 files / 514 tests passed）
- [x] **Step 3.3 缺陷跟踪状态归档**:
  - 核对 BUG-MAT-005 ~ BUG-MAT-011 状态：005/007/008/009/010/011 已修复；006 确认为设计收窄（非缺陷）。
- [x] **Step 3.4 后端门禁（无后端改动，回归确认）**:
  - `uv run ruff format --check .`、`uv run ruff check .`、`uv run mypy app`、`uv run lint-imports`、`uv run pytest tests`（1172 passed）

---

## 3. 验证命令集

```bash
# 1. 运行涉及的单元测试套件
pnpm --filter miniprogram test:unit tests/unit/components/MaterialUpload.spec.ts
pnpm --filter miniprogram test:unit tests/unit/api/material.spec.ts
pnpm --filter miniprogram test:unit tests/unit/stores/materialStoreTree.spec.ts
pnpm --filter miniprogram test:unit tests/unit/materialTreeUtils.spec.ts
pnpm --filter miniprogram test:unit tests/unit/components/KnowledgeTreeNode.spec.ts
pnpm --filter miniprogram test:unit tests/unit/pages/materialList.spec.ts

# 2. 全量前端门禁验证
pnpm --filter miniprogram run lint
pnpm --filter miniprogram run type-check
pnpm --filter miniprogram run test:unit
```

---

## 4. 评审门禁与回滚方案
- **评审门禁**：
  - 必须确保 `type-check` 0 错误（严禁引入 `any`）。
  - 所有新写的半选推导纯函数具备 100% 分支覆盖率。
  - 列表页面在不同机型/环境挂载时无重复网络调用。
- **回滚操作**：
  - 如产生意外交互冲突，直接使用 `git checkout -- miniprogram/` 还原变动。
