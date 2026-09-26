# 修复知识点树递归组件渲染崩溃（去递归扁平化渲染）

## Goal

微信小程序端资料「知识点树」页（`subpackages/material/pages/knowledge-tree/index`）在真机/开发者工具中整页渲染崩溃，报 `TypeError: Cannot read properties of undefined (reading 'children')`，导致考点树完全不可用、无法勾选考点与生成题目。本任务消除崩溃根因（递归自引用组件 + 递归 props 透传），恢复考点树的正常渲染与交互。

用户价值：资料解析后的考点树是「选择考点 → 生成题目」链路的前置入口；该页崩溃会直接阻断核心业务流程。

## Background（已确认事实）

- 报错栈：`KnowledgeTreeNode` 渲染 → 计算属性内读取 `children` 抛错（`WAServiceMainContext` 日志，`at <KnowledgeTreeNode> at <Index materialId=null id="...">`）。
- 编译产物 `miniprogram/dist/dev/mp-weixin/subpackages/material/components/KnowledgeTreeNode.js:31-33` 中 `hasChildren = Array.isArray(props.node.children) && ...`，是渲染时最先求值的计算属性；`props.node === undefined` 时首抛即为 `reading 'children'`。
- 同批日志出现 `Setting data field "uP" to undefined is invalid.`。uni-app mp-weixin 通过单一 `u-p`（`uP`）字符串把 Vue props 透传给原生自定义组件：`renderProps` 将 props 存入模块级 `propsCaches[父组件uid]`（`common/vendor.js:6868/6678`），子组件用 `findComponentPropsData(properties.uP)` 取回（`common/vendor.js:6684/7348`）。`uP` 为 `undefined` 时回退为 `{}`，子组件所有 props（含 `node`）全为 `undefined`。
- 递归实现：`miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue` 通过自引用导入 `import KnowledgeTreeNode from './KnowledgeTreeNode.vue'` + 模板递归 `<KnowledgeTreeNode v-for="child in node.children">`（新增于提交 `a388e1c`）。
- 数据侧无异常：后端 `get_knowledge_tree`（`backend/app/services/knowledge.py:588`）返回合法嵌套树（`children` 默认 `[]`），契约一致（`backend/app/schemas/knowledge.py:16`、`miniprogram/src/types/material.ts:54`）。
- 现有的纯函数 `flattenKnowledgeTree` / `collectNodeAndDescendantIds`（`miniprogram/src/subpackages/material/utils/tree.ts:15/40`）已提供前序遍历与子树 ID 收集能力。
- 降级/告警：其余环境告警（`Some selectors are not allowed in component wxss...`、preload 提示）与本崩溃无因果关系。

## Requirements

- R1 **消除递归组件**：`KnowledgeTreeNode.vue` 不得再自引用自身、不得在模板内递归渲染子节点。层级展示改由父页面单层列表 + 缩进实现。
- R2 **扁平化可见列表**：新增纯函数（`miniprogram/src/subpackages/material/utils/tree.ts`）按前序输出「可见行」列表，每行携带节点与渲染深度；**被折叠节点的子孙不出现**，折叠节点自身仍可见。
- R3 **保持现有交互语义不变**：
  - 折叠/展开：`store.toggleNodeCollapse(id)`，折叠后其子孙从列表消失。
  - 勾选：点击节点或复选框时级联选中该节点及其全部子孙（含被折叠的子孙），使用 `collectNodeAndDescendantIds` + `store.toggleKnowledgeSubtree`，语义与当前一致。
  - 全选 / 清空：仍作用于整棵树的全部节点（与折叠状态无关）。
- R4 **保持展示字段不变**：节点名（`name || title || '未命名考点'`）、描述、低可信度徽章（`is_low_confidence`）、缩进（每层 28rpx）、折叠箭头（有子节点才显示）与现网视觉一致。
- R5 **测试同步更新**：新增/修正单测，覆盖扁平化可见列表、组件行渲染、页面折叠隐藏子孙；不得回归既有断言。
- R6 **质量门禁通过**：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 全绿（在 `miniprogram/` 下运行）。

## Acceptance Criteria

- AC1 微信小程序打开某份已解析资料的知识点树页，不再出现 `Cannot read properties of undefined (reading 'children')` 与 `Setting data field "uP" to undefined` 崩溃；树正常渲染出全部层级节点。
- AC2 点击某节点的折叠箭头后，其子孙节点从列表消失；再次点击后恢复显示；折叠节点自身始终可见。
- AC3 勾选某父节点后，其自身与全部子孙（含被折叠的隐藏子孙）在 Store 中均被选中，覆盖率同步更新；再次点击可级联取消。
- AC4 「全选 / 清空」在任意折叠状态下均作用于整棵树全部节点，覆盖率相应为 100% / 0%。
- AC5 `KnowledgeTreeNode.vue` 内不含对自身的 `import`，也不含递归子节点渲染（静态检查/人工确认）。
- AC6 `cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit` 全部通过，无新增失败用例。
- AC7 `pnpm run build:mp-weixin`（或 `dev:mp-weixin`）编译产物中 `KnowledgeTreeNode.json` 的 `usingComponents` 不再包含对自身的 `knowledge-tree-node` 映射。

## Out of Scope

- 不改动后端接口、数据契约与 Store 状态结构。
- 不改动出题配置抽屉（`QuestionConfigDrawer`）、题目页与多考点生成逻辑。
- 不新增树的搜索、拖拽、懒加载、动画等新功能。
- 不处理与本崩溃无因果关系的 wxss 选择器告警与资源 preload 提示；不顺手清理已废弃的 `.view-tabs` / `.questions-container` 样式（可作为后续独立清理项）。

## Open Questions

- 无（阻塞性决策已清空；架构方向已由用户确认为「去递归扁平化」）。
