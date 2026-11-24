# 微信小程序 WXSS、布局兼容性与前端规范缺口审计报告

> **审计角色**：`audit-mp-wxss-layout`（只读审计）
> **审计范围**：`miniprogram/src/**`（全部 40 个 `.vue`、10 个 `.scss`、配置文件）及实际编译产物 `miniprogram/dist/dev/mp-weixin/**`（全部 38 个 `.wxss`、组件 `.js`/`.json`、`common/vendor.js`、`project.config.json`），对照 `.trellis/spec/frontend/*.md` 与微信官方小程序文档。
> **任务目录**：`.trellis/tasks/11-24-mp-weixin-compat-audit`

---

## 1. 审计结论总览

| 严重级别 | 数量 | 核心问题摘要 |
| --- | --- | --- |
| **P0**（真机崩溃 / 完全失效） | **0** | `*` 通配符、WXSS 本地 `url()`、组件内 `page` 选择器、`backdrop-filter`、`+`/`~` 组合器、`:not/:is/:where/:has`、`:deep()` 均核实为 **0 命中** |
| **P1**（真机视觉/交互/原生渲染缺陷） | **4** | 1. `.start-btn[disabled]` 属性选择器在 WXSS 静默失效；2. `<textarea>`/`<input>` 在 `position: fixed` 浮层缺 `:fixed="true"` 及作答页弹窗未隐藏底层原生输入框；3. 全仓 65 处 `<button>` 缺失 `::after { border: none }` 及部分按钮缺 UA 重置；4. `pages/review/index.vue` 双 `sticky; top: 0` 同级层级冲突 |
| **P2**（兼容性风险 / 构建告警 / 产物膨胀） | **7** | 1. 46 处 Sass `@import` 弃用告警 + scoped 共享表 3~6 倍重复编译导致 `.wxss` 膨胀至 `328.5 KB`；2. 111 处 Flex `gap` 未锁定最低基础库/iOS 版本；3. `report.scss` `:last-child` 复制 5 份；4. 15 处 `env(safe-area-inset-bottom)` 缺 `constant()` 降级；5. `App.vue` 标签选择器 `box-sizing` 在隔离组件下不穿透；6. `78vh`/`82vh` 抽屉键盘交互风险；7. 多处 `<textarea>`/`<input>` 缺 `cursor-spacing` / `show-confirm-bar="false"` |

---

## 2. 编译机制与样式隔离实证（`dist/dev/mp-weixin`）

1. **UniApp 组件样式隔离实际编译产物**：
   - 事实源：`miniprogram/dist/dev/mp-weixin/common/vendor.js:7376-7381`（`parseComponent`）：
     ```js
     const options = {
       multipleSlots: true,
       // styleIsolation: 'apply-shared',
       addGlobalClass: true,
       pureDataPattern: /^uP$/
     };
     ```
   - 所有 29 个编译后自定义组件（`.json` 仅含 `component: true` 与 `usingComponents`）默认继承 `addGlobalClass: true`；其中 4 个组件显式追加 `virtualHost: true`（`RichContent.vue:11-15`、`CoachMessageList.vue:78`、`BackgroundTaskBar.vue:29`、`KnowledgePointPickerDrawer.vue:92`）。
2. **`App.vue` 全局 `--color-*` / `--z-*` CSS 变量在自定义组件中的可行性**：
   - `miniprogram/src/App.vue:34-127` 在 `page { ... }` 上声明了 `--color-*`、`--shadow-*`、`--z-*` 变量（编译到 `miniprogram/dist/dev/mp-weixin/app.wxss:3-96`），全仓样式共引用 `var(--*)` **708 次**。
   - **官方机制核实**：在微信小程序 WebView（Exparser Shadow DOM）中，CSS 自定义属性（`--*`）具有原生继承性，且 UniApp 默认开启 `addGlobalClass: true`（等价于全局类渗透），因此 `page` 上定义的 CSS 变量与 `.paper-card` / `.paper-btn-primary` 类选择器可正常在自定义组件内生效。
   - **例外限制**：依据微信官方文档，`addGlobalClass: true` **仅使 `app.wxss` 中的 class 选择器**作用于自定义组件，不保证标签选择器生效；因此 `app.wxss:97` 的 `view, text, scroll-view, textarea, button, input { box-sizing: border-box; }` 在组件内（尤其 Skyline 或旧基础库）不可靠。
3. **版本门禁缺失**：
   - `miniprogram/dist/dev/mp-weixin/project.config.json:15` 中 `"libVersion": ""`，`miniprogram/src/manifest.json` 未声明最低基础库版本。

---

## 3. 已核实通过的检查项（Zero-Issue Baseline）

经全量扫描 `miniprogram/src/**/*.{scss,vue}`（50 个文件）及 `miniprogram/dist/dev/mp-weixin/**/*.wxss`（38 个文件，共 `336,398 B` / `328.5 KB`）：

| 检查项 | 源码命中 | 编译产物 `.wxss` 命中 | 结论 |
| --- | --- | --- | --- |
| 通配符选择器 `*` | 0 | 0 | PASS |
| 本地相对路径 `url(...)` / `@font-face` | 0 | 0 | PASS |
| 兄弟/子代组合器（`+`、`~`、`>`） | 0 | 0 | PASS |
| 不支持伪类（`:not()` / `:is()` / `:where()` / `:has()`） | 0 | 0 | PASS |
| `:deep()` / `::v-deep` / `/deep/` | 0 | 0 | PASS |
| 组件/页面 `.wxss` 内标签选择器（`app.wxss` 除外） | 0 | 0 | PASS |
| `backdrop-filter` 毛玻璃 | 0 | 0 | PASS |
| 业务样式裸 Hex 色值（`App.vue` Token 定义除外） | 0 | 0 | PASS |
| 固定底栏/抽屉缺少 `env(safe-area-inset-bottom)` | 0 | 0 | PASS（9 处固定底栏/抽屉全覆盖） |

---

## 4. 分级缺陷明细（实证 `file:line` + 编译产物对照）

### P1-1：WXSS 不支持的属性选择器 `.start-btn[disabled]` 在产物中静默失效

- **官方规范**：微信小程序官方 WXSS 文档明确指出，WXSS **不支持**属性选择器（如 `[disabled]`、`[type=...]`），应使用 `.class` 类名控制状态。
- **源码位置**：`miniprogram/src/subpackages/material/questions.scss:139`
  ```scss
  .start-btn[disabled] { background: var(--color-border-slate); color: var(--color-ink-slate-subtle); }
  ```
- **调用方**：`miniprogram/src/subpackages/material/components/QuestionPreviewPanel.vue:37-40`
  ```html
  <button class="paper-btn-primary start-btn" :loading="isStarting" :disabled="!canStart" @tap="emit('start')">
  ```
- **编译产物实证**：该规则被编译进 **4 个 `.wxss` 文件**：
  - `miniprogram/dist/dev/mp-weixin/subpackages/material/pages/questions/index.wxss:397`：`.start-btn[disabled].data-v-d9d9dd92`
  - `miniprogram/dist/dev/mp-weixin/subpackages/material/components/QuestionConfigPanel.wxss:397`：`.start-btn[disabled].data-v-28192222`
  - `miniprogram/dist/dev/mp-weixin/subpackages/material/components/QuestionReadyCard.wxss:397`：`.start-btn[disabled].data-v-1be70797`
  - `miniprogram/dist/dev/mp-weixin/subpackages/material/components/KnowledgePointPickerDrawer.wxss:515`：`.start-btn[disabled].data-v-cb071b82`
- **真机影响**：当考点存在覆盖缺口（`!canStart`）时，WXSS 忽略 `[disabled]`，按钮仍保持 `.paper-btn-primary` 的深蓝可点击态视觉（点击仍受 WXML `disabled` 属性阻断），误导用户以为可开始作答。
- **修复建议**：改用显式状态类 `.start-btn.is-disabled`（配合 `:class="{ 'is-disabled': !canStart }"`）。

---

### P1-2：原生组件 `<textarea>` / `<input>` 在 `position: fixed` 浮层缺失 `fixed` 属性，且作答页打开抽屉未隐藏底层原生输入控件

- **官方规范**：
  1. 微信官方 `<textarea>` 文档要求：**若 `<textarea>` 处于 `position: fixed` 区域内，必须显式指定 `fixed="true"`**，否则真机（尤其 iOS 与部分 Android 机型）易出现光标错位、文字悬浮、键盘弹起偏移抖动。
  2. `<textarea>`（及聚焦态 `<input>`）属客户端原生组件。虽然现代基础库默认启用同层渲染，但在部分 Android 机型、低版本基础库或聚焦/placeholder 渲染降级时，原生组件层级高于普通 `view` 与 `position: fixed` 遮罩；行业标准做法是在弹窗/抽屉展开时用 `v-if` 将底层 `<textarea>` 切换为等效样式的普通 `<view>` 占位。
- **源码实证**：
  1. **`position: fixed` 浮层内 `<textarea>` 缺失 `:fixed="true"`**：
     - `miniprogram/src/subpackages/report/components/GradingActionModal.vue:23-28` 与 `:42-47`：位于 `.modal-overlay`（`position: fixed; z-index: var(--z-modal)`）内，未设 `:fixed="true"`，亦未设 `:cursor-spacing` / `:show-confirm-bar="false"`。
     - `miniprogram/src/components/AiCoachDrawer.vue:40-51`：位于 `.sheet-overlay`（`position: fixed; z-index: var(--z-coach)`）内，虽已配 `:cursor-spacing="20"`、`:adjust-position="true"`、`:show-confirm-bar="false"`，但**缺失 `:fixed="true"`**。
  2. **作答页弹出抽屉时底层 `<textarea>` / `<input>` 未隐藏**：
     - `miniprogram/src/subpackages/practice/pages/session/index.vue:25-54`：`<PracticeQuestionBody v-if="currentQuestion">` 与 `<AnswerCardDrawer v-model:visible="showCardDrawer">`（`--z-sheet: 200`）、`<AiCoachDrawer v-model:visible="showCoachDrawer">`（`--z-coach: 300`）共存，且底部还有 `<view class="bottom-bar">`（`position: fixed; z-index: var(--z-bottom-bar): 40`）。
     - `miniprogram/src/subpackages/practice/components/PracticeQuestionBody.vue:94-124`：主观题 `<textarea class="essay-input">`（118 行）和填空题 `<input class="fill-blank-input">`（94、104 行）在 `showCardDrawer || showCoachDrawer` 为 `true` 时仍保持挂载与原生占位渲染。
     - 实测风险：在未启用或降级同层渲染的真机上，打开「答题卡抽屉」或「AI 助教抽屉」时，底层主观题 `textarea` 的 placeholder 或输入文本可能穿透遮罩，且与 `AiCoachDrawer` 内的 `<textarea>` 同时存在双原生输入层。
- **修复建议**：
  - `GradingActionModal.vue` 与 `AiCoachDrawer.vue` 的 `<textarea>` 显式补充 `:fixed="true"`（若仍存在键盘顶起偏移，改用 `:adjust-position="false"` + `@keyboardheightchange` 动态计算弹窗底部偏移）。
  - `session/index.vue` 向 `PracticeQuestionBody` 传入 `:overlay-open="showCardDrawer || showCoachDrawer"`，当浮层打开时用同等高度样式的 `<view class="essay-input essay-placeholder">` 替换 `<textarea>`（保留当前已输入文本或 placeholder 文案）。

---

### P1-3：全仓 65 处 `<button>` 缺失 `button::after { border: none; }` 及 UA 样式重置

- **官方规范**：微信小程序原生 `<button>` 的默认灰框与圆角是由伪元素 `button::after` 绘制（`border: 1px solid rgba(0,0,0,.2); border-radius: 10px; transform: scale(.5);`），同时自带 `margin-left: auto; margin-right: auto; padding-left: 14px; padding-right: 14px; line-height: 2.55555556;`。仅在 `<button>` 本体设置 `border: none` 或自定义 `border` / `border-radius` **无法消除 `::after` 原生边框**，且在 `addGlobalClass: true` 组件中，`app.wxss` 的标签选择器 `button::after` 亦不能稳定穿透到自定义组件内部。
- **源码实证**：
  - 全仓 `miniprogram/src/**` 共 **65 处 `<button>`**，其中 **`plain` 属性使用数为 0**，**`::after` 边框清除规则为 0**（`App.vue`、`styles/*.scss`、各组件样式均无）。
  - **受影响典型锚点**：
    - 带自定义边框的按钮会出现**双层边框 + 错位圆角**：
      - `miniprogram/src/subpackages/report/report.scss:472-477`（`.reinforce-bar-btn`，`border: 1px solid var(--color-orange-border); border-radius: 12rpx;`）
      - `miniprogram/src/subpackages/material/components/MaterialCourseHeader.vue:125-138`（`.refresh-progress-btn` `border-radius: 999rpx` 与 `.review-existing-btn` `border-radius: 10rpx`）
      - `miniprogram/src/subpackages/material/course.scss:270-282`（`.sheet-practice-btn`）
      - `miniprogram/src/subpackages/material/questions.scss:77-80`（`.job-nav-secondary`）
    - 未清除 `margin: 0` / `line-height` 的柔性/行内按钮在 Flex 容器内对齐偏移或行高异常：
      - `miniprogram/src/pages/index/components/MaterialItemCard.vue:125-131`（`.manual-parse-btn` 位于 `.card-footer` 右对齐 Flex 行内，未置 `margin: 0` 与 `line-height`，原生 `margin-left/right: auto` 会异常撑开居中）
      - `miniprogram/src/subpackages/practice/session.scss:26-32`（`.draft-retry-btn` 无 `margin: 0`、无 `line-height`）
      - `miniprogram/src/subpackages/material/questions.scss:123-126`（`.gap-btn` 无 `line-height` / `flex` 居中）
      - `miniprogram/src/pages/review/review.scss:388, 596, 607`（`.mp-breakthrough-btn`、`.master-btn`、`.single-gen-btn`）
- **修复建议**：在 `App.vue` 定义全局类（如 `.paper-btn-primary::after { border: none; }` 与 `.btn-plain-reset { margin: 0; border: none; ... } .btn-plain-reset::after { border: none; }`，利用 `addGlobalClass: true` 穿透所有组件），或在各组件/共享样式显式为自定义按钮类追加 `&::after { border: none; }` 与 `margin: 0`。

---

### P1-4：`pages/review/index.vue` 双重 `position: sticky; top: 0` 同级层级覆盖冲突

- **源码实证**：
  - `miniprogram/src/pages/review/index.vue:3`：`<BackgroundTaskBar auto-refresh />`，内部根节点 `.task-bar-container`（`BackgroundTaskBar.vue:97`）声明 `position: sticky; top: 0; z-index: var(--z-sticky);`（`20`），且该组件开启了 `virtualHost: true`（`BackgroundTaskBar.vue:29`），使其 `.task-bar-container` 直接暴露在 `.review-container` Flex/流式上下文中。
  - `miniprogram/src/pages/review/index.vue:43`：`<view class="segment-bar sticky-surface">`，`.sticky-surface`（`styles/common.scss:52-56`）同样声明 `position: sticky; top: 0; z-index: var(--z-sticky);`（`20`）。
- **真机影响**：当学情页存在活跃后台任务（如错题再生题进行中）且用户向下滚动页面时，DOM 序靠后的 `.segment-bar`（同为 `top: 0; z-index: 20`）会吸顶并**完全压住/遮挡** `BackgroundTaskBar`。
- **核查其他页面**：`pages/index/index.vue`、`course/index.vue`、`questions/index.vue`、`detail/index.vue` 均无第二个 `sticky` 节点，且页面根容器无 `overflow: hidden` 阻断 `BackgroundTaskBar` 吸顶。
- **修复建议**：在 `review/index.vue` 中取消 `.segment-bar` 的 `.sticky-surface`（或仅在无活跃后台任务条时吸顶 / 将 `BackgroundTaskBar` 固定或置于更低/更高错位 `top`）。

---

### P2-1：Dart Sass `@import` 弃用告警 + `scoped` 共享 SCSS 导致 3~6 倍 WXSS 产物膨胀（`328.5 KB`）

- **工具实测**：在 `miniprogram/` 运行 `pnpm exec sass src/subpackages/report/report.scss --no-source-map`（Dart Sass `1.105.0`）：
  ```
  DEPRECATION WARNING [import]: Sass @import rules are deprecated and will be removed in Dart Sass 3.0.0.
  ```
- **源码与产物实证**：
  - 全仓共有 **46 行 `@import`**，分布于 **40 个 `.vue`/`.scss` 文件**。
  - 更严重的是工程结构问题：**多个页面级大样式表被多个子组件在 `<style lang="scss" scoped>` 中整份 `@import`**，导致每个组件 `.wxss` 都完整复制一份整页样式（含未使用的 `.review-container` / `min-height: 100vh` 等）：
    - `pages/review/review.scss`（`16,042 B`）被 `review/index.vue` 及 5 个子组件各自完整复制 → **6 份 = `96,252 B`**；
    - `subpackages/material/questions.scss`（`13,164 B`）被 `questions/index.vue` + 3 个组件完整复制 → **4 份 = `52,656 B`**；
    - `subpackages/report/report.scss`（`12,201~15,329 B`）被 `detail/index.vue` + 4 个组件完整复制 → **5 份 = `64,704 B`**；
    - `pages/review/questionBank.scss`（`8,752 B`）被 3 个组件完整复制 → **3 份 = `26,256 B`**；
    - 全包 38 个 `.wxss` 合计 **`336,398 B`（`328.5 KB`）**，其中大量为重复死样式，直接挤压主包/分包体积上限（微信单包 2MB 限制）。
- **修复建议**：
  1. 逐步将 `@import` 迁移至 `@use ... as *` / `@forward`（纯变量与 mixin 的 `tokens.scss` 零产出开销）。
  2. 禁止在组件 `<style scoped>` 中 `@import` 页面级全量 `.scss`；共享基础类收口到 `App.vue`（利用 `addGlobalClass: true` 零重复分发）或按组件拆分独立 `.scss`。

---

### P2-2：111 处 Flexbox `gap` 未配降级且未锁定最低基础库 / iOS 版本

- **官方/平台规范**：Flexbox `gap` / `row-gap` / `column-gap` 在 iOS < 14.5（WKWebView）及早期 Android WebView 中**完全不生效**（元素紧贴无间距）。
- **源码实证**：全仓 `.scss` 与 `.vue` `<style>` 中共有 **111 处 `gap:`**（分布于 `modal.scss:87`、`common.scss:45`、`AiCoachDrawer.vue`、`BackgroundTaskBar.vue`、`CoachMessageList.vue`、`review.scss`、`questionBank.scss`、`report.scss`、`session.scss`、`course.scss`、`questions.scss` 等 28 个文件），无一处提供 `@supports not (gap: 1px)` 或 `margin` 降级。
- **配置事实**：`miniprogram/dist/dev/mp-weixin/project.config.json:15` `"libVersion": ""`，未设定最低基础库或微信后台最低版本要求。
- **修复建议**：在微信公众平台后台与规范中明确要求最低基础库/系统基线（iOS >= 14.5 / Android WebView >= 84），或对关键底栏/按钮组（`modal-footer`、`bottom-bar`）使用传统 `margin` 或 `@supports` 兜底。

---

### P2-3：`:last-child` 结构伪类被复制进 5 个报告 `.wxss` 文件

- **源码位置**：`miniprogram/src/subpackages/report/report.scss:315`（`.ans-row:last-child { margin-bottom: 0; }`）
- **编译产物**：被编译为 `.ans-row.data-v-xxxxxx:last-child` 存在于 5 个报告 `.wxss` 文件中。
- **核实**：在 `AttemptResultCard.vue:31-44` 中，`.answer-compare-box` 内两个 `.ans-row` 均为同级纯 `<view>`（无条件 `v-if` 或混杂节点），现代 WebView 下可正常生效；但在 Skyline 引擎或若未来加入条件分支时易出现末尾识别偏差，建议显式绑定末项类或改用 `margin-top` / 仅对非末项设间距。

---

### P2-4：`env(safe-area-inset-bottom)` 缺少 `constant(safe-area-inset-bottom)` 兼容回退

- **源码实证**：全仓 **15 处** `env(safe-area-inset-bottom)`（涵盖全部固定底栏与抽屉：`common.scss:46`、`AiCoachDrawer.vue:169`、`index.scss:5,160`、`KnowledgePointPickerDrawer.vue:225`、`course.scss:5,262`、`questions.scss:3,129`、`AnswerCardDrawer.vue:56`、`session.scss:5,331`、`report.scss:5,449`、`tokens.scss:40`），均**未写**前置 `constant(safe-area-inset-bottom)` 回退。
- **注**：仅影响 iOS 11.0–11.1 极旧机型（iOS >= 11.2 已全面支持 `env()`），属低优先级兼容项。另 `miniprogram/src/styles/tokens.scss:39-41` 定义的 `@mixin safe-bottom-padding` 全仓**0 引用**。

---

### P2-5：`App.vue` 标签选择器 `box-sizing: border-box` 依赖 `addGlobalClass: true` 的边界问题

- **源码与产物**：`miniprogram/src/App.vue:129-131`（`app.wxss:97-99`）声明 `view, text, scroll-view, textarea, button, input { box-sizing: border-box; }`。
- **规范差异**：微信官方说明 `addGlobalClass: true` 仅保证全局 **class** 选择器渗透入自定义组件；跨组件标签选择器在 Skyline 或部分基础上不生效，因此项目中 `AiCoachDrawer.vue:176`、`CoachMessageList.vue:120-121,134`、`KnowledgePointPickerDrawer.vue:212`、`course.scss:120,126`、`modal.scss:125`、`session.scss:280,312` 不得不手工重复写 `box-sizing: border-box`。应在规范中明确：组件内带 `padding` + `width: 100%` 的 `scroll-view`/`textarea`/`input` **必须自身显式声明 `box-sizing: border-box`**，不可依赖 `App.vue` 标签选择器。

---

### P2-6：`78vh` / `82vh` 固定视口高度抽屉在软键盘弹起时的压缩风险

- **源码实证**：
  - `miniprogram/src/components/AiCoachDrawer.vue:129`（`.coach-drawer-sheet { height: 78vh; max-height: 82vh; }`，含 `<textarea>`）
  - `miniprogram/src/subpackages/material/components/KnowledgePointPickerDrawer.vue:199`（`.picker-sheet-panel { height: 78vh; max-height: 82vh; }`，含 `<input>`）
  - `miniprogram/src/subpackages/material/course.scss:58`（`.study-sheet-panel { height: 82vh; max-height: 84vh; }`）
  - `miniprogram/src/subpackages/practice/components/AnswerCardDrawer.vue:57`（`.card-drawer-sheet { max-height: 60vh; }`）
  - 所有 8 个页面容器使用 `min-height: 100vh`（`pages.json` 为默认原生导航栏与原生 TabBar，小程序端 `100vh` 已扣除导航栏与 TabBar 高度，页面级当前正常；但若未来改为 `navigationStyle: "custom"` 将直接溢出）。
- **风险**：在较矮屏幕（如 iPhone SE）或分屏场景，键盘弹起若触发 WebView 视口高度重算，`78vh` 抽屉内部 `header + context-bar + footer` 会剧烈挤压 `scroll-view` 可视区。

---

### P2-7：部分 `<textarea>` / `<input>` 缺少 `cursor-spacing` 与 `show-confirm-bar="false"`

- **源码实证**：
  - `miniprogram/src/subpackages/practice/components/PracticeQuestionBody.vue:118-124`（`<textarea class="essay-input">` 无 `:cursor-spacing` 与 `:show-confirm-bar="false"`，iOS 键盘上方默认附带高约 44px 的原生"完成"工具栏易遮挡输入框及下方字数统计）
  - `miniprogram/src/subpackages/report/components/GradingActionModal.vue:23-28, 35-47`（无 `:cursor-spacing` / `:show-confirm-bar="false"`）
  - `miniprogram/src/pages/index/components/FolderFormModal.vue:11-16`、`miniprogram/src/pages/profile/components/ProfileEditModal.vue:13-18`、`miniprogram/src/subpackages/material/components/KnowledgePointPickerDrawer.vue:16-21`（`<input>` 无 `:cursor-spacing`）。

---

## 5. `.trellis/spec/frontend/*.md` 覆盖缺口盘点

### 5.1 已有文档已覆盖的 `mp-weixin` 规则（且存在局部过期内容）

| 规范文件 | 已覆盖的小程序规则 | 与当前现状的过期/矛盾点 |
| --- | --- | --- |
| `quality-guidelines.md` | - `@tap.self` 被编译器丢弃 → 独立 `.modal-backdrop` + `inset: 0`（57-78 行）<br>- 零 `backdrop-filter` 与 `--z-*` 层级刻度（616 行）<br>- 严禁裸调 `showLoading`/`hideLoading`（617 行）<br>- 组件内嵌 `scroll-view` 必须 `virtualHost: true` + `box-sizing: border-box`（618 行）<br>- TabBar 页回访注册 `onShow`（619 行） | 第 550-608 行"已知偏离"仍写「5 个超 300 行 `.vue`、仅 5 处 `var(--color-*)`、361 处裸 Hex、无 `tokens.scss`」，与 `index.md`（2026-11-17 更新）矛盾；当前已全部清零 |
| `component-guidelines.md` | - 禁止组件模板递归自渲染（169 行） | 第 17-27 行组件表（7 个）与第 118-159 行样式/Hex/Emoji 描述停留在 2026-09-29，当前已为 25 个组件且已清零裸 Hex 与 Emoji |
| `directory-structure.md` | - 列出 `styles/{tokens,modal,common}.scss`、`virtualHost: true`、`box-sizing`（15,40,57,71 行） | 133 行仍保留旧的「仅 10 个共享 scss + 6 个内联 CSS、无 tokens」描述 |
| `index.md` | - 概括 0 裸 Hex、0 Emoji、固定底栏适配 `env(safe-area-inset-bottom)`（17, 55-56 行） | 仅作现状汇总，无可执行代码契约与门禁脚本 |

### 5.2 完全缺失（GAP）的核心 `mp-weixin` WXSS 与布局规范

1. **WXSS 选择器白名单/黑名单与编译产物校验**：未禁止 `*`、属性选择器（`[disabled]`）、`:not/:is/:where/:has`、`+`/`~`、组件内标签选择器，也未说明 `:deep()` 与 `addGlobalClass: true` / `styleIsolation` 的真实编译行为。
2. **原生组件（`textarea` / `input` / `canvas` / `video` / `map`）层级穿透与 `fixed` 契约**：未规定 `position: fixed` 容器内 `<textarea>` 必设 `:fixed="true"`，未规定弹窗打开时底层 `<textarea>` 必须用 `<view>` 降级占位，未规定 `cursor-spacing` / `show-confirm-bar`。
3. **微信 `<button>` 原生 `::after` 边框与 UA 样式重置规范**：未规定 `button::after { border: none; }`、`margin: 0`、`line-height` 清除方案（以及为什么不能靠 `App.vue` 标签选择器穿透组件）。
4. **`App.vue` 全局 CSS 变量与 `addGlobalClass: true` 边界**：未说明为何 `--color-*` 在 `page` 可继承进组件、为何 `.paper-card`/`.paper-btn-primary` 可穿透而 `view, textarea { box-sizing }` 不能可靠穿透。
5. **WXSS 资源 `url()` 禁令**：未禁止 WXSS 中本地相对路径图片/字体 `url(...)`。
6. **布局属性兼容矩阵（`gap` / `sticky` / `100vh` / `safe-area-inset-bottom`）**：未约定最低 iOS/基础库基线、未禁止多 `sticky` 同 `top: 0` 叠加冲突与 `scroll-view`/`overflow: hidden` 内 `sticky`、未统一 `constant()` + `env()` 安全区写法。
7. **Sass 模块化与 Scoped WXSS 体积防膨胀门禁**：未禁止在组件 `<style scoped>` 中 `@import` 页面级全量 `.scss`（导致 3~6 倍重复编译），未规划 `@import` → `@use` 迁移。

---

## 6. 建议新增规范大纲：`.trellis/spec/frontend/mp-weixin-compatibility.md`

建议在 `.trellis/spec/frontend/` 新增 `mp-weixin-compatibility.md`（并从 `index.md` 索引链接），结构如下：

```markdown
# 微信小程序（mp-weixin）WXSS、组件渲染与布局兼容规范

## 1. Scope / Trigger
- 新增或修改任何 `.vue` `<style>`、`.scss`、`pages.json`、`manifest.json`、原生表单/滚动/浮层组件时必读。

## 2. UniApp `mp-weixin` 编译隔离事实
- `common/vendor.js` 默认注入 `addGlobalClass: true`（仅 class 穿透，tag 选择器不穿透组件）
- `App.vue` `page { --color-* }` 继承机制 vs `virtualHost: true`（Flex + scroll-view 宿主断裂修复）

## 3. WXSS 选择器与资源禁令（Wrong vs Correct）
- 严禁：`*`、属性选择器（`[disabled]` → 改用 `.is-disabled`）、`:not/:is/:where/:has`、`+`/`~` 兄弟组合器、组件内标签选择器、本地相对路径 `url(...)`、`backdrop-filter`
- 谨慎使用：`:last-child` / `:nth-child`（仅限纯静态同构兄弟节点）

## 4. 原生组件（textarea / input）穿透与 fixed 契约
- 位于 `position: fixed` 弹窗/抽屉内的 `<textarea>` 必设 `:fixed="true"`、`:cursor-spacing="20"`、`:show-confirm-bar="false"`，且祖先禁止挂 `transform`
- 页面含 `<textarea>` / `<input>` 且同页存在全屏抽屉/弹窗时，浮层展开态必须用 `<view>` 占位替换底层 `<textarea>`

## 5. `<button>` 原生 UA 重置契约
- 所有自定义样式 `<button>` 必须消除 `::after { border: none; }`（通过 `App.vue` 公共类或组件局部规则）并显式归零 `margin: 0` 与 `line-height`

## 6. 布局兼容与安全区契约
- 安全区：所有 `position: fixed` 底栏/抽屉底部同时写 `constant(safe-area-inset-bottom)` + `env(safe-area-inset-bottom)`（或统一走 `@include safe-bottom-padding`）
- `position: sticky`：禁止置于 `scroll-view` 或 `overflow: hidden` 祖先内；同页禁止两个 `sticky; top: 0` 同 `z-index` 兄弟节点共存
- `flex gap`：明确项目最低基础库 / iOS >= 14.5 基线，核心操作栏优先 `margin` 或记录基线豁免
- `100vh` / `box-sizing: border-box`：组件内 `width: 100%` + `padding` 的 `scroll-view`/`textarea`/`input` 必须显式写 `box-sizing: border-box`

## 7. SCSS 模块化与 WXSS 体积门禁
- 禁止新写 `@import`（统一 `@use '../styles/tokens.scss' as *`）；禁止在组件 `<style scoped>` 中整份 `@import` 页面级 `.scss`

## 8. 自动化静态检查门禁（CI / pre-commit 可执行）
```

### 可直接落地的自动化 Lint / Grep 检查规则清单

1. **源码层静态扫描（`miniprogram/src/**/*.{vue,scss}`）**：
   - 属性选择器禁令：`rg -n '\[[a-zA-Z0-9_-]+([~|^$*]?=[^\]]*)?\]' miniprogram/src --glob '*.scss'`（排除 Vue 模板后仅扫 `.scss` 与 `<style>` 块）→ 必须 **0 命中**。
   - 不支持伪类/通配符/毛玻璃/本地资源：`rg -n '(:not\(|:is\(|:where\(|:has\(|backdrop-filter|url\()' miniprogram/src --glob '*.scss'` → 禁止本地 `url()` 与 `backdrop-filter`、`0` 命中。
   - 裸 Hex 禁令：`rg -n '#[0-9a-fA-F]{3,8}\b' miniprogram/src --glob '*.scss'` → 除 `tokens.scss`/`App.vue` 外 **0 命中**。
   - `<textarea>` `fixed` 属性检查：所有在 `.modal-overlay` / `.sheet-overlay` 内的 `<textarea` 必须含 `fixed`。
   - `@tap.self` 禁令：`rg -n '@[a-z]+\.self\b' miniprogram/src --glob '*.vue'` → **0 命中**。
   - 页面级 SCSS 被多组件 `@import` 防膨胀检查：统计单组件 `.wxss` 不得包含 `.review-container` / `.report-container` / `.questions-container` / `.course-container` 等页面根容器选择器。
2. **编译产物层静态扫描（`miniprogram/dist/mp-weixin/**/*.wxss`）**：
   - 禁止出现 `[`（排除 UniApp 内置 `[data-c-h="true"]`）、`*`（排除注释 `/* */`）、`url(`（除非 `https://` 或 `data:`）、`backdrop-filter`、`+`/`~`。
   - 除 `app.wxss` 外，禁止组件 `.wxss` 出现裸标签选择器（`view`/`text`/`button`/`input`/`textarea`/`page`）。
   - 单 `.wxss` 文件体积上限告警（如 `> 10 KB` 触发复核，防止 scoped `@import` 重复打包）。

---

## 7. 发现的 `.trellis/spec/frontend/` 文档路径清单

- `D:/code/Workspace/zhilian/.trellis/spec/frontend/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/component-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/quality-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/directory-structure.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/network-contract.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/api-payload-contracts.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/hook-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/state-management.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/type-safety.md`
