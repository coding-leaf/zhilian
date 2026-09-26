# Plan: 知识点层级树与出题配置页面实施计划

- **关联 Spec**: ZL-133
- **实施执行人 / Agent**: 资深全栈研发工程师 + 专职 Builder Agent
- **当前状态**: In-Execution
- **任务分级**: Tier 2 (单模块特性演进 / 微信小程序前端交互增量)

---

## 1. 变更文件清单 (Files that change)

### 1.1 契约与核心状态扩展
- `miniprogram/src/types/material.ts` (Modify: 补齐 `KnowledgeTreeNode` 对齐后端模型，增加 `name`, `description`, `level`, `is_low_confidence`)
- `miniprogram/src/types/question.ts` (Modify: 扩展 `QuestionItem` 字段，新增 `QuestionEditLogItem` 与 `QuestionAuditLogsResponse`)
- `miniprogram/src/api/question.ts` (Modify: 新增 `fetchQuestionAuditLogs` 封装 `GET /api/v1/questions/{id}/edit-logs`)
- `miniprogram/src/stores/materialStore.ts` (Modify: 扩展考点多选状态与动作 `selectedKnowledgeIds`, `toggleKnowledgeSelection`, `selectAllKnowledge`)
- `miniprogram/src/subpackages/material/utils/tree.ts` (New: 纯函数工具库，平铺树 `flattenKnowledgeTree`、出题参数校验 `validateQuestionConfig`)

### 1.2 路由与页面组件 (单文件均 <= 300 行)
- `miniprogram/src/pages.json` (Modify: 注册分包路由 `subpackages/material/pages/knowledge-tree/index`)
- `miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue` (New: 页面宿主容器，树展示与出题列表双模式切换，预估 250 行)
- `miniprogram/src/subpackages/material/pages/knowledge-tree/knowledge-tree.scss` (New: 遵循 DESIGN.md 样式定义)
- `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue` (New: 递归树节点组件，展开/折叠、勾选、低可信度黄色告警，预估 220 行)
- `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue` (New: 出题配置抽屉，1~50 题量校验、题型胶囊多选，预估 250 行)
- `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.scss` (New: 抽屉与胶囊样式)
- `miniprogram/src/subpackages/material/components/QuestionEditDrawer.vue` (New: 题目行内编辑抽屉，支持题干/选项/答案修改与原因必填，预估 250 行)
- `miniprogram/src/subpackages/material/components/QuestionAuditDrawer.vue` (New: 题目不可变修改审计抽屉，时间线与前后对比，预估 210 行)

### 1.3 伴随式单元测试
- `miniprogram/tests/unit/materialTreeUtils.spec.ts` (New: 树平铺与出题参数校验纯函数测试)
- `miniprogram/tests/unit/stores/materialStoreTree.spec.ts` (New: Store 考点选择与状态流转单测)
- `miniprogram/tests/unit/components/KnowledgeTreeNode.spec.ts` (New: 递归节点展开/折叠与低可信度黄色徽章渲染单测)
- `miniprogram/tests/unit/components/QuestionConfigDrawer.spec.ts` (New: 1~50 题量边界拦截与题型多选单测)
- `miniprogram/tests/unit/components/QuestionEditDrawer.spec.ts` (New: 题目行内编辑与原因非空拦截单测)
- `miniprogram/tests/unit/components/QuestionAuditDrawer.spec.ts` (New: 审计日志时间线与快照渲染单测)
- `miniprogram/tests/unit/pages/KnowledgeTreePage.spec.ts` (New: 知识树页面集成端到端交互单测)

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 契约/API补齐与 Store 扩展 (Contracts, APIs & Store Extensions)
* **操作目标**:
  1. 完善 `types/material.ts` 中的 `KnowledgeTreeNode`，对齐后端 `name`, `level`, `is_low_confidence` 属性；
  2. 扩展 `types/question.ts`，定义 `QuestionEditLogItem` 与 `QuestionAuditLogsResponse`；
  3. 在 `api/question.ts` 中封装 `fetchQuestionAuditLogs` 方法；
  4. 编写 `subpackages/material/utils/tree.ts` 纯函数计算核（`flattenKnowledgeTree` 与 `validateQuestionConfig`）；
  5. 扩展 `materialStore.ts` 纯响应式状态：增加已选考点 ID 数组及全选、反选、单选动作（严格禁止在 Store 内发起 API 调用）；
  6. 编写对应的纯函数与 Store 单元测试。
* **涉及文件**:
  - `miniprogram/src/types/material.ts`
  - `miniprogram/src/types/question.ts`
  - `miniprogram/src/api/question.ts`
  - `miniprogram/src/stores/materialStore.ts`
  - `miniprogram/src/subpackages/material/utils/tree.ts`
  - `miniprogram/tests/unit/materialTreeUtils.spec.ts`
  - `miniprogram/tests/unit/stores/materialStoreTree.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram &&   pnpm run test:unit tests/unit/materialTreeUtils.spec.ts tests/unit/stores/materialStoreTree.spec.ts &&   pnpm run type-check
  ```
* **预期判据**: 纯函数与 Store 单元测试 100% 绿灯，类型推导与 DTO 契约无任何 TS 报错。

---

### Milestone 2: 知识点层级树组件与低可信度标记 (Knowledge Tree Page & Node Component)
* **操作目标**:
  1. 在 `miniprogram/src/pages.json` 的 `subpackages/material` 中注册 `pages/knowledge-tree/index` 路由；
  2. 实现递归组件 `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue`：
     - 支持 2~5 级嵌套渲染；
     - 展开/折叠过渡，触控热区 $\ge 88	ext{rpx} 	imes 88	ext{rpx}$；
     - 当 `is_low_confidence === true` 时，右侧显示黄色提示徽章（DESIGN.md 警告色 `#F59E0B`、背景 `#FFFBEB`）；
     - 复选框选中与 `materialStore` 联动；
  3. 实现页面容器 `miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue`：
     - 在 `onLoad` 获取 `material_id` 并调用 `fetchKnowledgeTree`；
     - 页面顶部展示资料名称；若整树存在低可信度节点，顶部展示醒目黄色警示横幅（FR-18：“检测到部分知识点抽取可信度较低，已自动降级”）；
     - 顶部全选/反选快捷操作条；
     - 底部吸底操作栏（显示已勾选考点数量，提供“定制出题”主按钮，适配安全区）；
  4. 编写组件单元测试 `tests/unit/components/KnowledgeTreeNode.spec.ts`。
* **涉及文件**:
  - `miniprogram/src/pages.json`
  - `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue`
  - `miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue`
  - `miniprogram/src/subpackages/material/pages/knowledge-tree/knowledge-tree.scss`
  - `miniprogram/tests/unit/components/KnowledgeTreeNode.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram &&   pnpm run test:unit tests/unit/components/KnowledgeTreeNode.spec.ts &&   pnpm run type-check &&   pnpm run lint
  ```
* **预期判据**: 递归展开与选中联动逻辑正常，黄色警示标签渲染正确，单组件代码行数 $\le 260$ 行，Lint 与类型检查 0 报错。

---

### Milestone 3: 出题配置抽屉组件与数量/题型联动 (Question Configuration Drawer)
* **操作目标**:
  1. 实现 `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue` 抽屉组件：
     - 基于 `wd-popup` 从底部滑出，遵循 Squircle 顶部圆角 `24rpx`；
     - 展示当前选中的考点总数提示；
     - 题数配置（FR-27）：步进器输入，严格限制在 `1 ~ 50` 题之间，默认 5 题；
     - 题型胶囊筛选：单选 (`single_choice`)、多选 (`multiple_choice`)、判断 (`true_false`)、简答 (`short_answer`)，点击切换激活态；
     - 难度系数配置：1~5 级星级或单选；
     - 点击「开始定制出题」按钮：调用 `generateQuestions` 接口，进入防重 Loading 状态；
     - 出题成功后触发 `on-generate-success` 事件向父页面传递题目数据，并自动关闭抽屉；
  2. 编写组件单元测试 `tests/unit/components/QuestionConfigDrawer.spec.ts`（重点测试 1~50 题边界拦截与题型校验）。
* **涉及文件**:
  - `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue`
  - `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.scss`
  - `miniprogram/tests/unit/components/QuestionConfigDrawer.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram &&   pnpm run test:unit tests/unit/components/QuestionConfigDrawer.spec.ts &&   pnpm run type-check &&   pnpm run lint
  ```
* **预期判据**: 边界题量输入被正确防御，题型胶囊选中态正常切换，单组件行数 $\le 260$ 行。

---

### Milestone 4: 题目管理/行内编辑/修改审计与端到端集成 (Question Management, Inline Edit & Audit Flow)
* **操作目标**:
  1. 实现题目行内编辑抽屉 `miniprogram/src/subpackages/material/components/QuestionEditDrawer.vue`：
     - 允许用户修改题干全文、选项、标准答案、解析与难度（FR-26）；
     - **提供必填的修改原因输入框 (reason)**，未填写时阻断提交并给出轻提示；
     - 提交调用 `updateQuestion(id, payload)`，成功后派发局部刷新事件；
  2. 实现修改痕迹审计抽屉 `miniprogram/src/subpackages/material/components/QuestionAuditDrawer.vue`：
     - 接收题目 ID，调用 `fetchQuestionAuditLogs` 加载不可变修改历史；
     - 渲染时间线视图：展示操作动作徽章（创建/修改/删除/重新生成）、变更字段对比、修改前后快照与修改原因；
  3. 在 `knowledge-tree/index.vue` 中集成题目列表展示：
     - 支持题目卡片展示（题干、类型、答案摘要、操作按钮）；
     - 支持单题软删除（调用 `deleteQuestion` 二次确认弹窗）；
     - 提供重新生成题目入口；
     - 底部操作栏提供“进入练习”（预留向 ZL-134 答题页跳转）；
  4. 编写组件单测与页面集成单测，回归全量前端质量门禁。
* **涉及文件**:
  - `miniprogram/src/subpackages/material/components/QuestionEditDrawer.vue`
  - `miniprogram/src/subpackages/material/components/QuestionAuditDrawer.vue`
  - `miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue`
  - `miniprogram/tests/unit/components/QuestionEditDrawer.spec.ts`
  - `miniprogram/tests/unit/components/QuestionAuditDrawer.spec.ts`
  - `miniprogram/tests/unit/pages/KnowledgeTreePage.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram &&   pnpm run test:unit &&   pnpm run type-check &&   pnpm run lint
  ```
* **预期判据**: 全量单元测试 100% 绿灯，所有组件代码行数严格控制在 300 行以内，无类型错误，无 ESLint 告警。

---

## 3. 全局质量门禁核验 (Global Quality Gate)

* **代码风格与静态检查**: `cd miniprogram && pnpm run lint`（强制 0 报错，单文件严格 $\le 300$ 行，严禁 Emoji 与裸 Hex）
* **类型严格检查**: `cd miniprogram && pnpm run type-check`（`vue-tsc --noEmit` 0 报错）
* **单元测试全量回归**: `cd miniprogram && pnpm run test:unit`（脱机毫秒级全绿）
* **生产编译验证**: `cd miniprogram && pnpm run build:mp-weixin`（产物完整，分包配置合规）

---

## 4. 实施偏差记录 (Deviations Log)
* [当前规划阶段无偏差，严格围绕 FR-14, FR-18, FR-26, FR-27 与 DESIGN.md 展开]

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Approved
- **验证人 / 日期**: TechLead (人类授权模式) / 2026-09-25 03:15
