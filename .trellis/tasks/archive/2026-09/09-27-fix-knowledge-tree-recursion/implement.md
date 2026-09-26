# Implementation Plan — 去递归扁平化渲染

前置：所有命令在 `D:\code\Workspace\zhilian\miniprogram` 下用 `pnpm` 执行。实现顺序如下，先纯函数 → 组件 → 页面 → 测试。

## 0. Pre-flight

- [ ] 确认工作区无与本任务无关的未提交改动（`git status`），避免混入无关变更。
- [ ] 记录基线：`pnpm run test:unit` 当前为全绿（用于回归对比）。

## 1. 新增扁平化纯函数

文件：`miniprogram/src/subpackages/material/utils/tree.ts`

- [ ] 新增导出 `interface KnowledgeTreeRow { node: KnowledgeTreeNode; depth: number }`。
- [ ] 新增 `flattenVisibleTree(nodes, collapsedMap = {})`：
  - `Array.isArray(list)` 守卫；`if (!node) continue`；
  - 前序 push `{ node, depth }`；
  - 仅当 `!collapsedMap[node.id]` 且 `node.children` 为非空数组时递归，`depth + 1`。
- [ ] 保持既有导出（`flattenKnowledgeTree` / `collectNodeAndDescendantIds` 等）不变。

## 2. 去递归：行组件 `KnowledgeTreeNode.vue`

文件：`miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue`

- [ ] 删除模板中的递归子节点块 `<view v-if="hasChildren && !isCollapsed" class="node-children-list">…</view>`（当前 42–54 行）。
- [ ] 删除 `import KnowledgeTreeNode from './KnowledgeTreeNode.vue'`（当前 63 行）。
- [ ] 保留 props（`node` / `level` / `selectedIds` / `collapsedMap`）、emits、`nodeTitle`/`hasChildren`/`isSelected`/`isCollapsed` 与两个 handler。
- [ ] `handleToggleSelect` 内级联逻辑（`collectNodeAndDescendantIds` + `toggleKnowledgeSubtree`）保持不变。
- [ ] 静态确认组件内不再出现任何指向自身的组件引用。

## 3. 页面改单层列表渲染

文件：`miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue`

- [ ] 引入 `flattenVisibleTree`（与现有 `flattenKnowledgeTree, calculateKnowledgeCoverage` 同源导入）。
- [ ] 新增 `const visibleRows = computed(() => flattenVisibleTree(materialStore.currentKnowledgeTree, materialStore.knowledgeTreeCollapsedMap));`
- [ ] 模板 `.tree-list` 内改为：
  ```
  <KnowledgeTreeNode
    v-for="row in visibleRows"
    :key="row.node.id"
    :node="row.node"
    :level="row.depth"
    :selected-ids="materialStore.selectedKnowledgeIds"
    :collapsed-map="materialStore.knowledgeTreeCollapsedMap"
    @toggle-select="handleToggleSelect"
    @toggle-collapse="handleToggleCollapse"
  />
  ```
- [ ] 保留 `rootNodes`（空态判断）、`allFlatNodes`（全选/覆盖率，全量语义不动）。

## 4. 测试同步

- [ ] `miniprogram/tests/unit/materialTreeUtils.spec.ts`：新增 `flattenVisibleTree` 用例
  - 默认全部展开 → 5 行、深度 [1,2,3,2,1]；
  - 折叠 `kp-1` → 仅剩余 `kp-1`（其子孙被裁剪）与 `kp-2`；
  - 折叠中间节点 `kp-1-1` → 隐藏 `kp-1-1-1`，保留 `kp-1-1`；
  - 空输入 / 含空元素 → 不抛错。
- [ ] `miniprogram/tests/unit/components/KnowledgeTreeNode.spec.ts`：
  - 删除/改写原「hides children list when collapsed」用例（组件不再渲染子孙）；
  - 新增：有 `children` 的节点渲染 `.collapse-hit-area`；叶子渲染 `.collapse-placeholder`。
  - 其余用例（标题/描述/低可信度徽章/勾选 emit/选中样式/折叠 emit/级联）保持通过。
- [ ] `miniprogram/tests/unit/pages/knowledgeTreePage.spec.ts`：新增用例
  - 折叠根节点后 `wrapper.text()` 不再包含其子孙文本（如 `进程与线程模型`），折叠节点自身仍在；
  - 折叠状态下点击「全选」仍为 3、覆盖率 100%（全量语义）。

## 5. 验证命令（按序执行，全部必须通过）

```bash
cd miniprogram
pnpm run lint
pnpm run type-check
pnpm run test:unit
```

- [ ] 三命令全绿；`test:unit` 无新增失败/跳过。
- [ ] 编译校验自引用移除：`pnpm run build:mp-weixin`，检查
  `dist/build/mp-weixin/subpackages/material/components/KnowledgeTreeNode.json`
  的 `usingComponents` 不再包含 `"knowledge-tree-node"` 自引用键。
- [ ] 人工/真机验收（对应 PRD AC1–AC5）：微信开发者工具打开知识点树页，确认无 `reading 'children'` 与 `uP` 报错，折叠/级联勾选/全选正常。

## 6. 风险文件与回滚点

- 高风险文件：`KnowledgeTreeNode.vue`（删递归块）、`knowledge-tree/index.vue`（模板改 v-for）。
- 回滚点：本任务为单次实现提交；异常时 `git revert <commit>` 即可，无数据副作用。

## 7. 完成前检查（对齐 PRD AC）

- [ ] AC1–AC7 逐条核对并记录证据（命令输出 / 编译产物片段）。
- [ ] 若有可复用经验（mp-weixin 避免递归组件 / `u-p` 透传陷阱），进入 Phase 3 写入 frontend 规范。
