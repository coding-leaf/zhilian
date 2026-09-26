# Technical Design — 去递归扁平化渲染

## 1. Problem Restatement

考点树在微信小程序运行时的**递归自引用组件**与 uni-app 的**递归 props 透传（`u-p`/`propsCaches`）**组合下会丢失 `node` prop，导致整页渲染崩溃。需求本质是：在小程序端稳定地渲染任意深度树并支持折叠与级联勾选。

## 2. Root Cause (evidence-backed)

```
页面 v-for <knowledge-tree-node :node="node">      // common_vendor.p() → u-p="uid,idx,counter"
   └─ 递归子节点 <knowledge-tree-node :node="child">  // 自引用导入 a388e1c
        └─ 原生组件 properties.uP → findComponentPropsData() → propsCaches[uid][idx]
```

任一环节使 `properties.uP` 为 `undefined` 或 `propsCaches[uid]` 缺失，`findPropsData` 即回退 `{}`，`props.node` 变成 `undefined`，`hasChildren` 计算属性读 `props.node.children` 抛错，整页渲染中断。

关键结论：**崩溃由递归组件结构触发，而非数据**。因此设计目标是彻底移除「组件递归 + 递归 props 透传」这一失效面。

## 3. Chosen Approach: 扁平化可见列表渲染

将「树结构」与「渲染结构」解耦：数据仍是嵌套树，**渲染始终是一个单层列表**，每行由纯函数预先计算（前序遍历 + 深度 + 折叠裁剪）。

```
materialStore.currentKnowledgeTree   (嵌套树，数据源，不变)
materialStore.knowledgeTreeCollapsedMap (折叠表，不变)
                │
                ▼  flattenVisibleTree(nodes, collapsedMap)  ← 新增纯函数
        KnowledgeTreeRow[] = [{ node, depth }]   // 折叠节点的子孙被跳过
                │
                ▼  页面单层 v-for
        <KnowledgeTreeNode :node="row.node" :level="row.depth" />   // 无自引用，无递归
```

### 3.1 新增纯函数（`miniprogram/src/subpackages/material/utils/tree.ts`）

```ts
export interface KnowledgeTreeRow {
  node: KnowledgeTreeNode;
  depth: number; // 渲染深度，根为 1
}

/**
 * 前序遍历知识点树，输出折叠感知的可见行列表。
 * 被折叠节点的子孙不进入结果，但折叠节点自身保留。
 */
export function flattenVisibleTree(
  nodes: KnowledgeTreeNode[],
  collapsedMap: Record<string, boolean> = {},
): KnowledgeTreeRow[];
```

实现要点：`Array.isArray` 守卫 + 跳过空节点；`depth` 由遍历层数决定（不信任后端 `level` 字段，保证缩进稳定）；纯函数、无副作用、可单测。

### 3.2 组件契约（`KnowledgeTreeNode.vue`，改行为「行组件」）

- **删除**：`import KnowledgeTreeNode from './KnowledgeTreeNode.vue'`；模板中的 `<view class="node-children-list">` 递归块（当前 42–54 行）。
- **保留 props**：`node`、`level`（现语义=渲染深度）、`selectedIds`、`collapsedMap`。保留以最小化改动与测试面。
- **保留 emits**：`toggle-select`、`toggle-collapse`。
- **保留行为**：`nodeTitle`、`hasChildren`（仅用于折叠箭头显隐）、`isSelected`、`isCollapsed`；
  `handleToggleSelect()` 仍用 `collectNodeAndDescendantIds(props.node)` + `store.toggleKnowledgeSubtree` 做级联，**因为行内 `node` 仍是带 `children` 的完整节点**，故级联语义天然保留。
- `usingComponents` 中不再出现自引用键（由编译产出验证）。

### 3.3 页面改造（`pages/knowledge-tree/index.vue`）

- 引入 `flattenVisibleTree`；新增
  ```ts
  const visibleRows = computed(() =>
    flattenVisibleTree(materialStore.currentKnowledgeTree, materialStore.knowledgeTreeCollapsedMap),
  );
  ```
- 模板由 `v-for="node in rootNodes"` 改为 `v-for="row in visibleRows" :key="row.node.id" :node="row.node" :level="row.depth"`。
- `rootNodes` 仍用于空态判断（`rootNodes.length === 0`）；`allFlatNodes` 仍用于「全选」与覆盖率，保持"全量"语义。
- 其余（统计卡、工具条、吸底栏、抽屉）不动。

## 4. Data Flow & Contracts

| 关注点 | 变化 |
|--------|------|
| 数据契约 `KnowledgeTreeNode` / `KnowledgeTreeResponse` | 不变 |
| Store state/getters/actions | 不变 |
| 组件 props | 语义微调：`level` = 渲染深度（旧实现下根=1，递归层+1，等价） |
| 新增导出 | `KnowledgeTreeRow` 类型 + `flattenVisibleTree` 函数 |
| 折叠/勾选/全选语义 | 不变（见 PRD R3） |

## 5. Compatibility & Migration

- **无数据迁移**：仅前端渲染路径变更。
- **无跨页面影响**：`KnowledgeTreeNode` 仅被 `knowledge-tree/index.vue` 使用（已确认无其他引用）。
- **降级安全**：即使后端返回异常 `children`（非数组/含空元素），`flattenVisibleTree` 有 `Array.isArray` 与空节点守卫，不再抛错。

## 6. Trade-offs

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| A 保留递归 + `defineOptions({name})` 去自引用导入 | 改动最少 | 仍依赖 mp-weixin 递归组件 + 递归 `u-p`，社区反复出现传参丢失，易复发 | 否 |
| **B 扁平化列表（本设计）** | 彻底移除失效面；逻辑集中在可单测纯函数；渲染稳定 | 折叠时需重算列表；深层树一次性构建行数组（数据量为考点级，可忽略） | **采用** |
| B2 页面内联行、删除组件 | 文件更少 | 丢失组件单测与复用边界，页面文件变长 | 否（保留行组件） |

## 7. Risks & Mitigations

- **R-1 折叠裁剪漏项**：由 `flattenVisibleTree` 单测覆盖（根折叠/中间折叠/叶子/空输入/含空元素）。
- **R-2 级联勾选回归**：保留原有 `collectNodeAndDescendantIds` 路径，并补页面级勾选断言。
- **R-3 深度/缩进视觉回归**：`depth` 与旧 `level` 等价（根 1 起），页面用 `row.depth` 显式传入。
- **R-4 全选与折叠耦合误伤**：`allFlatNodes` 保持全量，独立于 `visibleRows`，加断言验证折叠态下全选仍为 100%。

## 8. Rollback

- 变更限于 3 个源文件（`tree.ts`、`KnowledgeTreeNode.vue`、`knowledge-tree/index.vue`）+ 3 个测试文件。
- 回滚方式：`git revert` 单个实现提交即可恢复；无数据/接口副作用。
- 若扁平化后出现新的渲染问题，可临时回退到提交前状态并保留问题复现记录。
