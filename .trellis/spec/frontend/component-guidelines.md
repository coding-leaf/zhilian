# Component Guidelines

> **事实源**：`miniprogram/src/components/**`、`miniprogram/src/pages/**/components/**`、`miniprogram/src/subpackages/**/components/**`、`miniprogram/src/App.vue`
> **最后核对**：2026-09-29
> **核对方式**：`rg "defineProps|defineEmits|defineExpose|withDefaults|<style" miniprogram/src`

> How components are built in this project. 本文档描述**当前代码**实际遵循的 Vue SFC 约定。

---

## Overview

- 组件全部为 **Vue 3 SFC + `<script setup lang="ts">`**，模板语言为 uni-app 小程序语法（`view` / `text` / `button` / `input` / `textarea` / `scroll-view` / `slider` / `image`）。
- Props 用**内联类型字面量** `defineProps<{ ... }>()` 声明（**不用独立的 `interface Props`，全仓库没有一处 `withDefaults`**）。可选字段用 `?`，页面负责对缺省值兜底。
- Emits 统一用 **调用签名形式** `defineEmits<{ (e: 'name', payload: T): void }>()`；全仓库没有 `interface Emits` 形式的第二种写法。
- **全仓库没有 `defineExpose`**：组件不给外部/测试暴露内部状态，测试只对纯函数与 store 断言。
- 当前组件清单（共 7 个）：

  | 组件 | 位置 | 行数 | props | emits |
  | --- | --- | --- | --- | --- |
  | `AiCoachDrawer.vue` | `src/components/` | 392 | `visible`（必填）+ 8 个可选上下文 | `update:visible` |
  | `PracticeEntryCard.vue` | `src/pages/review/components/` | 37 | `practice` | `open` |
  | `WrongRecordCard.vue` | `src/pages/review/components/` | 49 | `record` | `practice` |
  | `QuestionPreviewCard.vue` | `src/subpackages/material/components/` | 59 | `question` / `index` / `disabled?` | `remove` / `regenerate` |
  | `ReportSummaryCard.vue` | `src/subpackages/report/components/` | 91 | 8 个展示字段 | 无 |
  | `AttemptResultCard.vue` | `src/subpackages/report/components/` | 94 | `result` | `regrade` / `self-evaluate` / `coach` |
  | `GradingActionModal.vue` | `src/subpackages/report/components/` | 105 | `visible` / `mode` / `result` / `submitting` | `update:visible` / `submit` |

- **Wot Design Uni 当前零引用**：`pages.json` 仍保留 `easycom` 的 `^wd-(.*)` 规则，`package.json` 仍依赖 `wot-design-uni`，但 `src/**` 中**没有任何 `wd-*` 组件使用点**。所有卡片/按钮/抽屉均为自定义 `view` + `button`，样式复用 `App.vue` 的两个全局类：`.paper-card`（纸质卡片）与 `.paper-btn-primary`（主按钮），二者在 `src/**/*.vue` 中共出现在 56 行里。

**代码锚点**
- `miniprogram/src/pages.json::easycom`（`wd-*` 规则声明，但无使用点）
- `miniprogram/src/App.vue::.paper-card` / `::.paper-btn-primary`
- `miniprogram/src/components/AiCoachDrawer.vue::defineProps`
- `miniprogram/src/subpackages/report/components/AttemptResultCard.vue::defineEmits`

---

## Component Structure

标准 SFC 结构（以 `AttemptResultCard.vue` 为例）：

```vue
<template>
  <view class="paper-card detail-card">
    <view :class="['result-tag', `tag-${badge.tone}`]">{{ badge.text }}</view>
    <button @tap="emit('regrade', result)">申请 AI 复查</button>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { AttemptResult } from '@/types';
import { canGradeManually } from '@/api/adapters/practice';
import { resolveResultBadge, typeLabel } from '../utils/reportView';

const props = defineProps<{ result: AttemptResult }>();

const emit = defineEmits<{
  (e: 'regrade', result: AttemptResult): void;
  (e: 'self-evaluate', result: AttemptResult): void;
  (e: 'coach', result: AttemptResult): void;
}>();

const badge = computed(() => resolveResultBadge(props.result));
</script>

<style lang="scss" scoped>
@import '../report.scss';
</style>
```

- **派生值一律走 `computed`**：`badge`、`statusText`、`actionText`、`typeLabel`、`stem`、`knowledgePointLabel` 等都是 computed，模板不写表达式。
- **展示文案由纯函数产出，不散落在模板**：`reportView.ts` / `reviewView.ts` / `adapters/question.ts::questionTypeLabel` 负责把领域值映射成中文文案；组件只消费。
- **需要 `v-model` 的浮层组件只提供 `visible` 单向 prop**：`AiCoachDrawer` 与 `GradingActionModal` 都只接受 `visible`（不额外接受 `modelValue`），emit `update:visible`，调用方用 `v-model:visible` 绑定。
- **表单型浮层用 `watch` 重置草稿**：`GradingActionModal` 监听 `[props.visible, props.result?.attemptItemId]`，打开或换题时清空 `reason` / `scoreInput`，避免上一次输入串到下一题。

**代码锚点**
- `miniprogram/src/subpackages/report/components/AttemptResultCard.vue::badge`
- `miniprogram/src/subpackages/report/components/GradingActionModal.vue::watch`
- `miniprogram/src/components/AiCoachDrawer.vue::defineEmits`（`update:visible`）

---

## Props Conventions

- Props 必为**类型化的内联对象字面量**，可选字段用 `?`；**没有 `withDefaults`**，缺省值由使用方或组件内部 `computed` 兜底（如 `ReportSummaryCard` 显式要求调用方传入 `report: DiagnosisReport | null` 并在模板用 `v-if` 分支）。
- 命名用 camelCase；模板里同样以 kebab-case 传入（如 `:question-id`、`:grading-points`、`:is-fully-graded`）。
- 数组/对象类型 props 直接接收引用，不做深拷贝；只读消费。
- **上下文袋式 props 是既有先例**：`AiCoachDrawer` 用 8 个可选 prop（`title` / `questionId` / `contextText` / `userAnswer` / `gradingPoints` / `folderId` / `materialId` / `knowledgePointId`）区分「题目级答疑」与「范围级答疑」两种模式。新增挂载点时优先复用该形状，不要另开组件。
- **组件可以直接读 store**：`WrongRecordCard` / `PracticeEntryCard` 通过 `reviewView.ts` 纯函数消费传入的领域对象，不读 store；而页面（`pages/review/index.vue`、`subpackages/material/pages/course/index.vue`）直接 `useXxxStore()` 取数下传。当前组件里没有 `useXxxStore()` 调用点。

**代码锚点**
- `miniprogram/src/components/AiCoachDrawer.vue`（8 个可选上下文 prop）
- `miniprogram/src/subpackages/report/components/ReportSummaryCard.vue::defineProps`
- `miniprogram/src/subpackages/material/components/QuestionPreviewCard.vue::disabled`

---

## Emits Conventions

- Emits 统一 `defineEmits<{ (e: 'name', payload: T): void }>()` 调用签名形式。
- 事件名：`update:visible` / `self-evaluate` 等用 kebab-case；`remove` / `regenerate` / `open` / `practice` / `coach` / `submit` / `regrade` 为单词。模板绑定用 kebab-case（`@self-evaluate`、`@update:visible`）。
- **payload 形状**：单值事件直接传领域对象（`emit('regrade', result)`）；`GradingActionModal` 的 `submit` 传聚合对象 `{ reason: string; score: number }`，把两种模式（复查 / 自评）收敛成一个事件。
- **组件内校验失败用 `uni.showToast` 直接反馈**（`GradingActionModal.handleSubmit` 校验分数区间与理由非空），校验通过才 emit。
- **副作用归属**：路由跳转与 toast 兜底由**组件或页面**处理，但下面这条是硬性且 100% 遵守的——全仓库 12 处 `uni.navigateTo` / `uni.redirectTo` **全部**带 `fail` 回调提示。
- **已知例外：`AiCoachDrawer` 自己发请求**。它是唯一直接 import `@/api` 的组件（`apiAskQuestionCoach` / `apiAskScopedCoach`），在 `handleSend` 内维护 `messageList` 与 `isThinking`，失败时往对话流推一条「助教网络开小差了，请稍后再试。」。这与「组件纯展示、副作用上交」的原则有冲突，但对话状态是组件私有且无跨页共享需求，暂未上提到 store/page；新增类似的对话型组件请先评估是否值得改为「数据经 props、请求经 emit 上交」。

**代码锚点**
- `miniprogram/src/subpackages/report/components/GradingActionModal.vue::handleSubmit`
- `miniprogram/src/components/AiCoachDrawer.vue::openSource`（跳转带 `fail`）
- `miniprogram/src/subpackages/material/pages/questions/index.vue::handleStartPractice`

---

## Styling Patterns

两种样式写法并存，按「该页面区是否有共享样式文件」选择：

1. **`<style lang="scss" scoped>` + `@import '<区域>.scss'`**（10 个文件）。导入的 scss 是**按功能区共享的单一样式表**，不是组件同名文件：
   - `src/pages/review/review.scss` ← `pages/review/index.vue` + 两个 `pages/review/components/*.vue`
   - `src/subpackages/material/questions.scss` ← `subpackages/material/pages/questions/index.vue` + `subpackages/material/components/QuestionPreviewCard.vue`
   - `src/subpackages/practice/session.scss` ← `subpackages/practice/pages/session/index.vue`
   - `src/subpackages/report/report.scss` ← `subpackages/report/pages/detail/index.vue` + 三个 `subpackages/report/components/*.vue`
   
   同名类名（如 `.paper-card`、`.details-section`）由各 SFC 的 `scoped` 各自独立复制一份。
2. **`<style scoped>` 内联普通 CSS**（6 个文件，无 `lang="scss"`、无导入）：`AiCoachDrawer.vue`、`pages/index/index.vue`、`pages/profile/index.vue`、`pages/auth/login.vue`、`subpackages/material/pages/course/index.vue`、`subpackages/material/pages/upload/index.vue`。

- **设计 token 的现状与约定不符**：`App.vue` 在 `page` 上定义了 `--color-paper-bg` / `--color-paper-card` / `--color-ink-primary` / `--color-academic-blue` / `--color-correct` 等 10 个 CSS 变量，但 `src/**` 里引用 `var(--color-*)` 的只有 5 处、**全部在 `App.vue` 自身**；其余样式表内联了约 **361 处裸 Hex**（`#1e3a8a` / `#78716c` / `#f5f5f4` 等）。`docs/DESIGN.md` 第 2 节「禁止裸 Hex」目前是**未落地的承诺**，新增代码应优先引用 CSS 变量，但不要声称现状已收敛。
- **没有 `src/uni.scss`、没有 `src/styles/theme.scss`**：SCSS 入口只有各功能区的共享样式表，`$touch-target-min` / `$radius-lg` 之类的 SCSS token 变量在当前代码中**不存在**。
- 触控尺寸现状：使用内联 `rpx` 数值（如按钮 `height: 76~88rpx`、选项卡片 `padding: 20rpx 24rpx`），未通过 token 统一。

**代码锚点**
- `miniprogram/src/App.vue::page`（`--color-*` CSS 变量与 `.paper-card`）
- `miniprogram/src/subpackages/report/report.scss`（被 4 个文件共享）
- `miniprogram/src/subpackages/practice/session.scss`

---

## Accessibility

- **`role` / `aria-*` 属性当前零使用**：全仓库 `rg "role=|aria-" src` 无命中。可点击容器一律是 `<view @tap>` 或 `<button>`，无额外 ARIA 标注。
- **触控区没有独立命中区包装**：不存在 `.collapse-hit-area` / `.checkbox-hit-area` 之类结构；可点击行靠整卡 `@tap`（`pages/index/index.vue` 的讲义卡片、`subpackages/material/pages/course/index.vue` 的 `tree-node-card`）。
- **状态不靠颜色单通道**：这条**实际成立**——状态用文本徽章表达，如 `pages/index/index.vue` 的 `.status-badge` 渲染 `materialStatusText()`（「待解析 / 排队中 / 解析中 / 已解析 / 解析失败 / 需要重拍」）、`pages/review/components/WrongRecordCard.vue` 的「已攻克 / 待巩固」、`AttemptResultCard` 的「正确 x/y · 错误 x/y · 判题中 · 待重判 · 未作答」。颜色只是附加信息。
- **加载/空/错误三态**：页面级显式渲染。
  - 错误态 + 重试按钮：`subpackages/report/pages/detail/index.vue`（`loadError` → `.error-card` + 「重新加载」）；
  - 空态：`pages/index/index.vue`（`.empty-state`「当前分类下暂无讲义」）、`pages/review/index.vue`（`.empty-state`）、`subpackages/material/pages/course/index.vue`（`.empty-tree` / `.empty-snippets`）；
  - 加载态：`subpackages/material/pages/course/index.vue`（`.loading-spinner` + `parseProgressText`）。
- **零表情包原则当前被违反**：`docs/DESIGN.md` 第 1 节禁止 Unicode Emoji，但代码中存在以下使用点，属**已知偏离**，不要以「已遵守」写入新规范：

  | 文件 | 行 | 内容 |
  | --- | --- | --- |
  | `src/components/AiCoachDrawer.vue` | 7 / 14 / 22 / 31 | `🤖` 头像、`✕` 关闭、`📌 答疑上下文`、`💡 启发延伸` |
  | `src/pages/index/index.vue` | 61 / 81 / 144 / 161 | `📄`、`🎯 课程全景刷题`、`💡`、`✕` |
  | `src/pages/profile/index.vue` | 12 / 13 / 67 | `👤`、`✎`、`✕` |
  | `src/subpackages/material/pages/course/index.vue` | 39 / 81 / 96 / 102 / 111 | `✓`、`💡 讲义助教`、`✕`、`📘`、`📖` |
  | `src/subpackages/material/pages/questions/index.vue` | 29 / 49 | `✓` |
  | `src/subpackages/practice/pages/session/index.vue` | 62 | `☑` / `☐` 多选指示符 |

**代码锚点**
- `miniprogram/src/pages/index/index.vue::.status-badge`
- `miniprogram/src/subpackages/report/pages/detail/index.vue::loadError`
- `miniprogram/src/utils/materialState.ts::materialStatusText`

---

## Common Mistakes

- **禁止组件模板递归自渲染**：mp-weixin 下递归自引用组件会丢失 props 透传，导致整页崩溃；深层树必须先由纯函数扁平化，再**单层** `v-for` 渲染。当前实现见 `subpackages/material/pages/course/index.vue`：`loadDetail` / `syncParseProgress` 拿到嵌套的 `KnowledgeTreeResult.nodes` 后，经本地 `flattenTree(nodes)` 前序展开为扁平的 `knowledgeNodes`，模板只做一层 `v-for`，靠 `L{{ node.level }}` 标签表达层级。
- **不要把网络请求写进页面却忘了兜底**：页面可以直接调 `@/api`（如 `pages/review/index.vue` 调 `apiListWrongRecords`），但必须处理失败（toast 或 `loadError` 错误态），不得静默吞错。
- **不要让组件在生成/提交过程中锁死用户**：浮层组件的 `close` / `closeDrawer` 只 emit，不做 `submitting` 拦截；提交中的关闭由调用方决定是否放行。
- **不要省略跳转 `fail` 兜底**：全仓库 12 处 `uni.navigateTo` / `uni.redirectTo` 全部带 `fail` 提示，新增跳转必须保持。
- **不要在组件内追加 Emoji**：虽然现状已有 6 个文件存在 Emoji（见上表），新代码应遵守 `docs/DESIGN.md` 的零表情包原则，不要扩大偏离面。

**代码锚点**
- `miniprogram/src/subpackages/material/pages/course/index.vue::flattenTree`
- `miniprogram/src/pages/review/index.vue::loadWrongs`
- `miniprogram/src/components/AiCoachDrawer.vue::closeDrawer`
