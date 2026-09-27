# Component Guidelines

> **事实源**：`miniprogram/src/components/**`、`miniprogram/src/subpackages/**/components/**`、`miniprogram/src/uni.scss`、`docs/DESIGN.md`
> **最后核对**：2026-09-28 @ ca062a1
> **核对方式**：`rg "defineProps|withDefaults|defineEmits|defineExpose" miniprogram/src`

> How components are built in this project. 本文档描述**当前代码**实际遵循的 Vue SFC 约定。

---

## Overview

- 组件全部为 **Vue 3 SFC + `<script setup lang="ts">`**，模板语言为 uni-app 小程序语法（`view` / `text` / `button` / `input` / `textarea` / `scroll-view`）。
- Props 用 `interface Props` + `defineProps<Props>()` + `withDefaults(...)` 声明默认值；Emits 用 `defineEmits` 显式类型化；需要被页面/测试驱动的组件用 `defineExpose` 暴露状态与方法。
- 组件默认**纯展示优先**：数据经 props 下传，交互经 emit 上交；页面负责编排 API 与 store。
- Wot Design Uni 通过 `pages.json` 的 `easycom` 按 `^wd-(.*)` 自动引入；当前实际仅使用 `wd-icon`、`wd-loading`、`wd-tag`、`wd-skeleton` 四个基础组件，大量「卡片 / 按钮 / 抽屉」为自定义组件（`CourseCard.vue`、`OptionCard.vue`、`QuestionConfigDrawer.vue` 等）。
- **零表情包原则**（`docs/DESIGN.md` 第 1 节）：全系统严禁 Unicode Emoji，状态一律用结构化文本 / `wd-tag` / 矢量图标表达。

**代码锚点**
- `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue::defineProps`
- `miniprogram/src/pages.json::easycom`
- `miniprogram/src/components/home/MasteryDashboardBar.vue`（`wd-*` 之外的 `role`/`aria-label` 用法）

---

## Component Structure

标准 SFC 结构（以 `QuestionRenderer.vue` 为例）：

```vue
<template> ... </template>

<script setup lang="ts">
import { computed } from 'vue';
import OptionCard from './OptionCard.vue';

export interface RendererQuestion { /* 领域类型 */ }

interface Props { question: RendererQuestion; modelValue?: string | string[]; orderIndex?: number }
const props = withDefaults(defineProps<Props>(), { modelValue: '', orderIndex: 0 });

const emit = defineEmits<{ (e: 'update:modelValue', value: string | string[]): void }>();
</script>

<style lang="scss" scoped>
@import './QuestionRenderer.scss';
</style>
```

- 需要导出**纯函数计算核**时，额外加一个普通 `<script lang="ts">` 块与 `<script setup>` 并存（Vue 3 双脚本块），如 `MasteryDashboardBar.vue` 的 `calculateTierPercentages` / `resolveOverallTier`。
- 需要双向绑定（`v-model`）的抽屉/弹窗组件同时接受 `visible` 与 `modelValue` 两个可选 prop，并 emit `update:visible` / `update:modelValue` / `close`。
- 独立文件行数控制：`docs/DESIGN.md` 第 6 节要求任何 `.vue` 不超过 **300 行**；ESLint `max-lines` 设为 500 行（warning）作为兜底阈值（`miniprogram/.eslintrc.cjs`）。

**代码锚点**
- `miniprogram/src/subpackages/practice/components/QuestionRenderer.vue::RendererQuestion`
- `miniprogram/src/components/home/MasteryDashboardBar.vue::calculateTierPercentages`
- `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue::handleClose`（`visible` + `modelValue` 双入参）
- `miniprogram/.eslintrc.cjs`（`max-lines`）

---

## Props Conventions

- Props 必为**类型化接口**，可选字段用 `?`，并在 `withDefaults` 中给出安全默认值（常见：空字符串、空数组工厂 `() => []`、`false`、`0`）。
- 命名使用 camelCase；模板中以 kebab-case 传入（如 `:folder-id`、`:selected-ids`）。
- 数组/对象默认值必须用工厂函数（`selectedIds: () => []`），禁止共享可变默认值。
- 避免在 prop 上直接做重逻辑：派生值用 `computed`（如 `isOpen = visible || modelValue`）。
- 组件对 store 的访问需**最小化且可测**：`KnowledgeTreeNode.vue` 在 `handleToggleSelect` 内先用 `getActivePinia()` 守卫再 `useMaterialStore()`。

**代码锚点**
- `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue::Props`
- `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue::handleToggleSelect`
- `miniprogram/src/components/course/PracticeStartBar.vue::isDisabled`

---

## Emits Conventions

- Emits 用 `defineEmits<{ (e: 'name', payload: T): void }>()` 的调用签名形式，或等价的 `interface Emits` + `defineEmits<Emits>()`；两者都在本项目中存在，按就近一致即可。
- 事件名 camelCase 或 kebab-case 均出现；模板绑定用 kebab-case（`@update:model-value`、`@toggle-select`）。
- 副作用（发请求、跳转）由组件或页面处理，但**禁止在 emit 处理器里静默吞错**：失败必须 toast 兜底。
- 跨页跳转必须在组件内带 `fail` 回调提示（见 `useMaterialCardActions.handleCardClick`、`miniprogram/src/subpackages/material/pages/questions/index.vue::handleStartPractice`）。

**代码锚点**
- `miniprogram/src/subpackages/practice/components/QuestionRenderer.vue::defineEmits`
- `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue::defineEmits`
- `miniprogram/src/subpackages/material/composables/useMaterialCardActions.ts::handleCardClick`

---

## Styling Patterns

- 组件样式为 **scoped SCSS**，绝大多数组件把样式拆到与组件同名的 `.scss` 文件并以 `@import './xxx.scss';` 引入（如 `MaterialCard.vue` 除外，内联 `<style lang="scss" scoped>`）。
- 设计 token 统一来自 `src/uni.scss` 的 SCSS 变量与 `page` 上的 CSS 变量；**禁止业务组件写未收敛的裸 Hex**，取色应引用 `$--wot-color-*` 或 `var(--color-*)`。历史例外：`MaterialCard.vue`、`wrongBookFormat.ts` 等仍内联 Hex（如 `#2563EB`），属于待收敛项。
- 触控与人体工程学参数（`docs/DESIGN.md` 第 1 节）：最小点击热区 `88rpx × 88rpx`（`$touch-target-min`）、选项卡片最小高度 `96rpx`（`$option-card-min-height`）、吸底栏 `112rpx`（`$action-bar-height`）+ `env(safe-area-inset-bottom)`。
- 微交互参数：按压缩放 `$scale-active`（`scale(0.985)`）、过渡 `$transition-bounce`、页面切入 `$animation-view-fade`。
- 状态色由 `resolveMaterialStatusTag` / `getErrorTypeInfo` 等纯函数映射为 `{ bg, color, border }` 主题对象，组件只消费，不硬编码颜色分支。

**代码锚点**
- `miniprogram/src/uni.scss::$touch-target-min`
- `miniprogram/src/uni.scss::$radius-lg`
- `miniprogram/src/utils/copywriting.ts::resolveMaterialStatusTag`
- `miniprogram/src/subpackages/report/utils/wrongBookFormat.ts::getErrorTypeInfo`

---

## Accessibility

- 可点击但非原生按钮的容器补 `role="button"` 与 `aria-label`（如 `MasteryDashboardBar.vue` 的「学情诊断综合掌握度看板」、`CourseListSection.vue` 的新建课程/未分类入口、`MaterialCard.vue` 行的「移动到课程」）。
- 触控区不小于 `$touch-target-min`；折叠/勾选命中区用独立的 `.collapse-hit-area` / `.checkbox-hit-area` 包装，避免图标本身过小。
- 状态与进度不得仅靠颜色区分：必须有文本标签（`wd-tag`、`.status-badge`、`.step-text`）。这同时满足零表情包与色弱可读性。
- 加载/空/错误三态在页面级显式渲染（loading / empty / error），错误态提供「重新加载」按钮（见 `knowledge-tree/index.vue`、`report/pages/detail/index.vue`）。

**代码锚点**
- `miniprogram/src/components/home/MasteryDashboardBar.vue`（`role="button"` + `aria-label`）
- `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue`（`.collapse-hit-area` / `.checkbox-hit-area`）
- `miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue::handleRetryLoad`

---

## Common Mistakes

- **禁止组件模板递归自渲染**：mp-weixin 下递归自引用组件会丢失 props 透传，导致整页崩溃；深层树必须扁平化后单层 `v-for`。参见 `.trellis/spec/frontend/quality-guidelines.md` 的对应 scenario 与 `miniprogram/src/subpackages/material/utils/tree.ts::flattenVisibleTree`。
- **不要把 store 网络请求塞进组件**：Store 只做内存增删改；网络统一经 `src/api/*` 由页面/组件/composable 触发。
- **不要在提交过程中锁死用户**：出题抽屉允许生成中关闭，`handleClose` 不做 `submitting` 拦截（`QuestionConfigDrawer.vue`、`CourseGenerateDrawer.vue`）。
- **不要省略跳转 `fail` 兜底**：所有 `uni.navigateTo` 必须带 `fail` 提示，否则用户看到「原地不动」。
- **组件内禁止 Emoji**：状态与指示用文本/徽章/图标，遵守 `docs/DESIGN.md` 零表情包原则。

**代码锚点**
- `miniprogram/src/subpackages/material/utils/tree.ts::flattenVisibleTree`
- `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue::handleClose`
- `miniprogram/src/components/course/CourseGenerateDrawer.vue::handleClose`
