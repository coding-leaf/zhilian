# 02 - Vue 3 模板/脚本语法、WXML 编译产物、组件/生命周期与配置兼容性审计

> **审计角色**：`audit-mp-vue-wxml`（只读审计）
> **审计范围**：`miniprogram/src/**/*.vue`（实测共 **40 个 `.vue` 文件**：1 个 `App.vue` + 8 个注册页面 + 29 个活跃自定义组件 + 2 个未引用死组件）、`miniprogram/src/pages.json`、`miniprogram/src/manifest.json`、`miniprogram/vite.config.ts`、`miniprogram/package.json`，以及真实编译产物 `miniprogram/dist/dev/mp-weixin/**`（含 `.wxml` / `.json` / `.js` 与 `common/vendor.js`）和 `miniprogram/dist/build/mp-weixin/**` 分包体积。
> **对照基线**：UniApp Vue 3 (`@dcloudio/uni-mp-weixin@3.0.0-4020920240930001`, Vue `3.4.21`) 官方规范与微信小程序官方文档（`developers.weixin.qq.com`）。

---

## 1. 审计总览与分级统计

| 严重级别 | 数量 | 核心结论 |
| --- | :---: | --- |
| **P0（致命崩溃/不可用）** | **0** | 经源码与 `dist/dev/mp-weixin` 编译产物（含 `common/vendor.js` 运行时）逐项核验，模板语法、插槽、`Map` prop 传参、组件 `ref`/`defineExpose`、事件名映射、递归渲染及包体积均未发现致命阻断缺陷（已排除 11 项高发误报，见第 4 节）。 |
| **P1（真机行为缺陷/竞态/配置漂移）** | **4** | ① `position: fixed` 弹层内 `<textarea>` 缺少 `fixed` 属性，且 `AiCoachDrawer` 存在 `@confirm` 不可达与 `show-confirm-bar="{{false}}"` 安卓失焦陷阱；② 填空/主观题受控 `<input>`/`<textarea>` 同步改写 `value` 与全仓表单缺 `cursor-spacing`；③ `questions/index.vue` 与 `review/index.vue` 存在 `onLoad`/`onShow`/`onMounted` 生命周期竞态与冷启重复请求；④ `manifest.json` `networkTimeout` 超微信 60s 上限、`appid` 仍为 `touristappid`（仅手工改了 `dist`）且缺少隐私合规配置。 |
| **P2（规范缺口/体验隐患/构建卫生）** | **5** | ① 3 处 `<scroll-view scroll-x :show-scrollbar="false">` 缺 `enhanced` 导致配置无效；② `CoachMessageList` `scroll-into-view` 用 `nextTick` 置空重赋易被同帧合并失效；③ 缺少 `lazyCodeLoading: "requiredComponents"`；④ `virtualHost: true` 与页面卸载钩子（`onUnload` vs `onUnmounted`）使用不统一、2 个多根组件无 `virtualHost`；⑤ 34 个产物 `.js` 残留 ES2020 `??`、2 个死组件未清理、共享 SCSS 在 review 组件产生 94KB WXSS 重复。 |

---

## 2. 实证缺陷清单（P1 / P2）

### [P1-1] `position: fixed` 弹层内 `<textarea>` 缺少 `fixed` 属性；`AiCoachDrawer` `@confirm` 不可达且 `show-confirm-bar="{{false}}"` 存在安卓失焦风险

- **源码位置**：
  - `miniprogram/src/components/AiCoachDrawer.vue:40-51`（位于 `.sheet-overlay` `position: fixed` 抽屉内）：
    - 未声明 `fixed`（`:fixed="true"`）
    - 绑定 `@confirm="sendMessage"`，但**未设置 `confirm-type="send"`**，同时又设置了 `:show-confirm-bar="false"`
    - 同时使用 `auto-height` 与 CSS `min-height: 76rpx; max-height: 180rpx;`（L173-177）
  - `miniprogram/src/subpackages/report/components/GradingActionModal.vue:23-28` 与 `42-47`（位于 `.modal-overlay` `position: fixed` 模态框内）：
    - 均未声明 `fixed`，且未设置 `:cursor-spacing`
- **编译产物对照**：
  - `miniprogram/dist/dev/mp-weixin/components/AiCoachDrawer.wxml:1`：
    `<block wx:if="{{r0}}"><textarea class="chat-textarea data-v-41143025" placeholder="向助教追问，支持多行输入..." disabled="{{q}}" auto-height maxlength="{{500}}" cursor-spacing="{{20}}" adjust-position="{{true}}" show-confirm-bar="{{false}}" bindconfirm="{{r}}" value="{{s}}" bindinput="{{t}}"/></block>`
  - `miniprogram/dist/dev/mp-weixin/subpackages/report/components/GradingActionModal.wxml:1`：
    两处 `<textarea>` 均编译为 `<textarea class="form-textarea ..." placeholder="..." maxlength="{{300}}" value="{{...}}" bindinput="{{...}}"/>`，均无 `fixed` 与 `cursor-spacing`。
- **官方规范依据**：
  - 微信小程序 `<textarea>` 官方文档明确规定：`fixed`（默认 `false`）——**"如果 textarea 是在一个 `position:fixed` 的区域，需要显示指定属性 `fixed` 为 `true`"**，否则键盘弹起或页面滚动时易发生输入框错位、光标漂移或遮罩穿透。
  - 微信小程序 `<textarea>` 的 `confirm-type` **默认值为 `"return"`**（换行），点击软键盘右下角仅插入换行符而**不会触发 `bindconfirm`**；同时隐藏了 `show-confirm-bar="{{false}}"`（去除“完成”栏，且在部分 Android 机型上会导致首次聚焦立即失焦），导致 `AiCoachDrawer.vue:50` 的 `@confirm="sendMessage"` 在真机上几乎不可达。
  - 微信小程序 `<textarea>` `auto-height` 会忽略样式 `height`，且部分 Android 机型清空文本后易残留空白高度，与 `max-height: 180rpx` 并存存在跨端差异。
- **修复建议**：
  1. `AiCoachDrawer.vue:40` 与 `GradingActionModal.vue:23,42` 均补齐 `fixed`（即 `:fixed="true"`）；`GradingActionModal` 补齐 `:cursor-spacing="24"`。
  2. `AiCoachDrawer.vue:40` 明确二选一：若希望键盘直接发送，显式加 `confirm-type="send"`；若希望保留多行换行，移除无效的 `@confirm="sendMessage"`，并评估将 `show-confirm-bar` 恢复为默认 `true` 以规避 Android 首次聚焦失焦。

---

### [P1-2] 练习作答受控 `<input>`/`<textarea>` 同步 `setData` 改写 `value` 易引发光标跳动/IME 吞字，且全仓多处表单缺 `cursor-spacing`

- **源码位置**：
  - `miniprogram/src/subpackages/practice/components/PracticeQuestionBody.vue:92-124` + `miniprogram/src/subpackages/practice/utils/practiceSession.ts:133-148`：
    - 多空填空（L94-99）：`<input :value="val" @input="handleMultiBlankInput(idx, $event)" />`
    - 单空填空（L104-109）：`<input :value="answerText" @input="handleSingleTextInput" />`
    - 主观题（L118-124）：`<textarea :value="answerText" :maxlength="1000" @input="handleSingleTextInput" />`
  - 其他缺 `:cursor-spacing` 的弹窗输入框：
    - `miniprogram/src/pages/index/components/FolderFormModal.vue:11-16`
    - `miniprogram/src/pages/profile/components/ProfileEditModal.vue:13-18`
    - `miniprogram/src/subpackages/report/components/GradingActionModal.vue:35-40`（`type="digit"`）
- **编译产物对照**：
  - `miniprogram/dist/dev/mp-weixin/subpackages/practice/components/PracticeQuestionBody.wxml:1`：
    `<input class="fill-blank-input ..." placeholder="{{val.b}}" value="{{val.c}}" bindinput="{{val.d}}"/>`、`<textarea class="essay-input ..." value="{{x}}" maxlength="{{1000}}" bindinput="{{y}}"/>`（均无 `cursor-spacing`）。
- **官方规范与根因分析**：
  - `practiceSession.ts:145-148` 的 `joinFillBlankAnswers` 会在全为空白字符时返回 `''`，并把 `;`/`；`/`\n` 替换为空格；`handleMultiBlankInput` 触发 `emit('input-answer', ...)` -> `practiceStore.setLocalAnswer` -> 经 `props.userAnswer` 同步回流 `setData` 更新 `<input value="{{val.c}}">`。
  - 按微信小程序 `<input>`/`<textarea>` 官方文档，`bindinput` 处理函数中**不应通过异步/同步 `setData` 改写正在输入的 `value`**（如需清洗输入应直接从 `bindinput` 回调 `return` 替换字符串，或在 `blur`/提交时清洗）；每次击键都经父组件重算并 `setData` 回写 `value`，在真机中文拼音 IME 组合输入或键入前导空格/分号时极易触发**光标跳至末尾、拼音重复或吞字**。
  - `session/index.vue` 底部存在固定 `.bottom-bar`，但 `PracticeQuestionBody.vue` 3 个输入框及 3 个表单弹窗均未配置 `:cursor-spacing`，小屏真机上键盘易紧贴或遮挡输入框与底部操作栏。
- **修复建议**：
  1. `PracticeQuestionBody.vue` 内部维护本地非受控/按 `question.id` 同步的草稿副本（仅在切换题目 `watch(() => props.question.id)` 时从 `props.userAnswer` 同步），避免每次击键经 store 回环触发 `setData` 覆盖 `value`；分号清洗放到保存/提交层而非击键回写。
  2. 为所有 `<input>` / `<textarea>` 补充合理的 `:cursor-spacing="24"`（在固定底栏上方可设 `48`~`80`）。

---

### [P1-3] 页面生命周期竞态：`onLoad`（async）与 `onShow` / `onMounted` 时序冲突导致状态覆盖与冷启重复请求

- **源码位置 A（状态覆盖风险）**：`miniprogram/src/subpackages/material/pages/questions/index.vue:126-155` + `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts:381-394`
  - 微信小程序页面冷启顺序为 `onLoad` -> `onShow` -> `onReady`（对应 Vue `onMounted`）。
  - `questions/index.vue:126` 的 `onLoad` 为 `async` 函数：当携带 `?view=generated&batch_id=...` 进入时，L132 先置 `compose.viewMode.value = 'ready'`，在 L138 `await compose.loadScopeKnowledgePoints(...)` 让出执行权。
  - **此时 `onShow`（L153-155）立即同步触发**，执行 `await compose.attachActiveJobForScope()`。而 `useQuestionCompose.ts:387-393` 一旦在 `taskStore.questionJobs` 中发现同 scope 存在在途任务，就会**无条件将 `viewMode.value = 'generating'`**，直接覆盖 `view === 'generated'` 的就绪视图意图；即便普通进入，`attachActiveJobForScope()` 也会在冷启时被连续调用最多 **3 次**（L135、L154、L149）。
- **源码位置 B（冷启重复请求与隐藏 Tab 预加载）**：`miniprogram/src/pages/review/index.vue:113-119, 157-163` + `miniprogram/src/pages/review/components/QuestionBankSection.vue:122` + `miniprogram/src/pages/review/composables/useReviewCenter.ts:156-184`
  - 经 `miniprogram/dist/dev/mp-weixin/common/vendor.js:7555-7560` 实证，UniApp 在小程序 `lifetimes.ready()` 中才派发 `this.$vm.$callHook("mounted")`，因此**页面 `onShow` 先于 `onMounted` 触发**。
  - `pages/review/index.vue` 同时在 `onShow`（L161）和 `onMounted`（L157）调用 `review.refreshAll`：冷启时 `onShow` 先发出一轮 5 并发请求并置 `bankDirty = true`（`useReviewCenter.ts:176-178`）；若请求在 `onReady` 前返回，`onMounted` 会再次触发完整 `refreshAll`。
  - 同时 `QuestionBankSection` 包裹在 `v-show`（`pages/review/index.vue:113`，编译产物 `pages/review/index.wxml:1` 为 `<view class="data-v-18d3cbe4" hidden="{{!M}}">`）中，导致其 `onMounted(loadBatches)`（`QuestionBankSection.vue:122`）在默认 `mastery` Tab 即立即发请求，而用户首次切到 `bank` Tab 时又因 `bankDirty === true` 再次拉取。
- **对照良好实践**：`miniprogram/src/pages/index/index.vue:206, 224-235` 已使用 `hasCompletedInitialLoad` 跳过冷启首次 `onShow`；`subpackages/material/pages/course/index.vue:93-100` 因 `loadDetail` 同步将 `isLoading.value = true`（`useCourseDetail.ts:94`），冷启 `onShow` 被正确短路。
- **修复建议**：
  1. `questions/index.vue` 使用 `hasLoaded` 标志跳过首次 `onShow`，且在 `view === 'generated'` 显式查看历史批次时不主动切回 `generating`。
  2. `pages/review/index.vue` 去掉 `onMounted` 中与 `onShow` 重复的 `refreshAll`（统一由 `onShow` 驱动，或加冷启标志），并在 `QuestionBankSection` 首次展示前按需加载而非在 `v-show` 隐藏态预拉取。

---

### [P1-4] `manifest.json` -> `app.json` 核心配置缺陷：`networkTimeout` 超微信 60s 上限、`appid` 为占位符且缺隐私合规声明

- **源码位置**：`miniprogram/src/manifest.json:11-24`
- **编译产物对照**：
  - `miniprogram/dist/dev/mp-weixin/app.json:55-58`：
    ```json
    "networkTimeout": {
      "request": 90000,
      "uploadFile": 120000
    }
    ```
  - `miniprogram/dist/dev/mp-weixin/project.config.json:16`：`"appid": "wx5357****6077"`（已打码），与源码 `manifest.json:12` 的 `"appid": "touristappid"` **不一致**（说明系在微信开发者工具中手动修改了 `dist/`）。
- **官方规范依据**：
  1. **超时上限**：微信小程序全局配置 `app.json` 官方文档规定 `networkTimeout` 下 `request` / `uploadFile` 默认值与**常规上限均为 `60000` 毫秒（60 秒）**。源码 `manifest.json:19-22` 与 `src/utils/request.ts:431`（`UPLOAD_REQUEST_TIMEOUT_MS` 120s）依赖超过 60s 的全局超时，存在被客户端静默截断为 60s 的风险。
  2. **AppID 漂移**：每次执行 `pnpm run build:mp-weixin` 或清理 `dist/` 重建，UniApp 都会用 `manifest.json` 中的 `"touristappid"` 覆写 `project.config.json`，导致真机预览、`wx.login` 与真机调试失效。
  3. **隐私保护合规**：代码中调用了微信敏感隐私接口——`uni.chooseImage`（`pages/profile/index.vue:110`）、`uni.setClipboardData`（`components/CoachMessageList.vue:108`）、`chooseMessageFile`（`pages/index/composables/useMaterialUpload.ts`），但 `manifest.json` 未声明 `"__usePrivacyCheck__": true`（旧基础库兼容），且全仓无 `wx.onNeedPrivacyAuthorization` / `<button open-type="agreePrivacyAuthorization">` 兜底处理；若微信公众平台未申报对应隐私类目或用户未授权，真机将报 `api scope is not declared in the privacy agreement`（详见 `01-js-runtime-and-api-compat.md` 对应 API 审计）。
- **修复建议**：
  1. 将 `manifest.json` 中 `networkTimeout` 调整回合规值 `60000`（长耗时解析/出题本身已走后台异步任务，上传大文件需确保 60s 内完成或评估分片）。
  2. 通过环境变量或本地配置规范管理 `mp-weixin.appid`，避免手工改 `dist/project.config.json` 后被构建覆盖。
  3. 补齐 `mp-weixin.__usePrivacyCheck__: true` 并在公众平台《用户隐私保护指引》申报「选中的照片或视频信息」「剪贴板」「聊天记录文件」。

---

### [P2-1] `<scroll-view scroll-x :show-scrollbar="false">` 缺少 `enhanced` 属性，在微信端静默失效

- **源码位置（3 处）**：
  - `miniprogram/src/pages/index/components/FolderFilterBar.vue:8`
  - `miniprogram/src/pages/review/index.vue:10`
  - `miniprogram/src/pages/review/components/WrongBookSection.vue:8-9`（且 L8 外层 `<view class="group-scroll">` 与 L9 `<scroll-view class="group-scroll">` 重复复用同名类）
- **编译产物对照**：
  - `dist/dev/mp-weixin/pages/index/components/FolderFilterBar.wxml:1`：`<scroll-view scroll-x class="folders-scroll data-v-3ce9fc08" show-scrollbar="{{false}}">`
  - `dist/dev/mp-weixin/pages/review/index.wxml:1`：`<scroll-view scroll-x class="folder-filter-scroll data-v-18d3cbe4" show-scrollbar="{{false}}">`
  - `dist/dev/mp-weixin/pages/review/components/WrongBookSection.wxml:1`：`<scroll-view scroll-x class="group-scroll data-v-d6d46a51" show-scrollbar="{{false}}">`
- **官方规范依据**：微信小程序 `<scroll-view>` 文档明确要求 `show-scrollbar` **必须同时开启 `enhanced="{{true}}"`（基础库 >= 2.12.0）才生效**，且官方注明其主要作用于垂直滚动条，横向 `scroll-x` 隐藏滚动条还需配合 WXSS `::-webkit-scrollbar` 规则。
- **修复建议**：补齐 `enhanced`（`:enhanced="true"`），并配合 WXSS 隐藏横向滚动条；清理 `WrongBookSection.vue:8-9` 重复类名。

---

### [P2-2] `CoachMessageList.vue` 使用 `nextTick` 置空重赋同一 `scroll-into-view` ID，真机易被合并导致不滚动到底部

- **源码位置**：`miniprogram/src/components/CoachMessageList.vue:3-8, 67, 93-104`
- **编译产物对照**：`dist/dev/mp-weixin/components/CoachMessageList.wxml:1`：`<scroll-view scroll-y scroll-into-view="{{g}}" scroll-with-animation class="chat-body data-v-b30beb16">...<view id="{{...}}" class="bottom-anchor ..."/>`
- **根因分析**：`watch` 回调内执行 `scrollTargetId.value = ''; await nextTick(); scrollTargetId.value = 'coach-bottom-anchor'`。在微信逻辑层/渲染层双线程通信下，微任务内的两次 `setData` 可能在同一渲染帧内合并，或当新旧值最终同为 `'coach-bottom-anchor'` 时 `<scroll-view>` 不触发滚动。
- **修复建议**：为每条消息绑定唯一 ID（如 `id="msg-{{msg.id}}"`），滚动目标直接切换为最后一条消息 ID（或 `thinking` 占位节点 ID），无需置空再重赋。

---

### [P2-3] `manifest.json` 缺少 `"lazyCodeLoading": "requiredComponents"`（按需注入）

- **源码位置**：`miniprogram/src/manifest.json:11-24`
- **编译产物对照**：`miniprogram/dist/dev/mp-weixin/app.json` 未包含 `lazyCodeLoading`。
- **官方规范依据**：微信小程序官方文档与开发者工具体验评分（Audits）强烈建议配置 `"lazyCodeLoading": "requiredComponents"`，以开启按需注入、降低冷启动 JS 注入耗时与内存占用。
- **修复建议**：在 `manifest.json` 的 `mp-weixin` 节点添加 `"lazyCodeLoading": "requiredComponents"`（注意添加后需在微信开发者工具验证所有页面/组件 `usingComponents` 正常加载）。

---

### [P2-4] `virtualHost: true` 与页面卸载钩子使用不统一；2 个多根组件无 `virtualHost`

- **源码位置**：
  - 仅 4 个组件启用了 `defineOptions({ options: { virtualHost: true } })`：`BackgroundTaskBar.vue:29`、`CoachMessageList.vue:78`、`RichContent.vue:11-15`、`KnowledgePointPickerDrawer.vue:92`；其余 25 个活跃组件均未启用（包括同属底部抽屉的 `AiCoachDrawer.vue`、`KnowledgeSnippetModal.vue`、`AnswerCardDrawer.vue`）。
  - 2 个多根（Fragment）组件未启用 `virtualHost: true`：
    - `miniprogram/src/subpackages/report/components/AdaptivePracticeCard.vue:1-45`（4 个并列根 `<view>`，当全部 `v-if` 为 `false` 时，WXML 中仍残留空的 `<adaptive-practice-card>` 宿主节点）
    - `miniprogram/src/subpackages/report/components/ReportSummaryCard.vue:1-61`（2 个根块）
  - 页面卸载钩子不统一：
    - `miniprogram/src/subpackages/material/pages/course/index.vue:107` 使用 Vue `onUnmounted`（经 `common/vendor.js:7563-7567` 实证，页面 `detached()` 会调 `$destroyComponent` 触发 `onUnmounted`，故非 P0/P1，但 UniApp 官方推荐页面级清理优先用 `onUnload`）
    - `miniprogram/src/subpackages/practice/pages/session/index.vue:189-195` 同时写了 `onUnload` 与 `onBeforeUnmount`
    - `miniprogram/src/subpackages/report/pages/detail/index.vue:128` 使用 `onUnload`
- **修复建议**：在 `.trellis/spec/frontend/mp-weixin-compatibility.md` 中统一约定：页面级销毁清理统一用 `onUnload`；参与父级 Flex/Grid 布局或多根条件渲染的组件统一启用 `virtualHost: true`。

---

### [P2-5] 构建与资产卫生：34 个产物 `.js` 残留 `??`、2 个死 `.vue` 组件未清理、共享 SCSS 导致 review WXSS 重复

- **源码与产物实证**：
  1. **空值合并 `??` 残留**：在 `dist/dev/mp-weixin` 中，`?.` 已被 Vite/esbuild 转译为 `== null ? void 0 : ...`，但 34 个业务 `.js` 文件（如 `QuestionBankSection.js` 8 处、`MasteryOverviewCard.js` 7 处、`GradingActionModal.js` 3 处、各类 adapters 等）仍保留 ES2020 `??` 运算符，强依赖 `project.config.json` 的 `es6: true` 二次转译或较高版本基础库（与 `01-js-runtime-and-api-compat.md` 交叉印证）。
  2. **2 个未引用死组件**：`miniprogram/src/subpackages/material/components/QuestionPreviewCard.vue` 与 `QuestionPreviewPanel.vue` 仅二者互引，无任何页面引用，未编入 `dist/dev/mp-weixin`（同时 `.trellis/spec/frontend/index.md` 与 `component-guidelines.md` 所记组件数/文件数已过期）。
  3. **分包体积与 WXSS 重复**：
     - 体积现状（远低于微信 2MB 单包 / 20MB 总包上限，合规）：
       - `dist/dev/mp-weixin`：总计 **1,085.37 KB**（主包 721.76 KB；`material` 202.25 KB；`practice` 48.54 KB；`report` 112.81 KB）
       - `dist/build/mp-weixin`：总计 **641.20 KB**（主包 372.95 KB；`material` 151.19 KB；`practice` 31.86 KB；`report` 85.20 KB）
     - 但 `pages/review/components/` 下 6 个组件各自 `@import '../review.scss'`，在 `dist/dev/mp-weixin` 中生成 6 份 `15.67 KB` 的重复 WXSS（合计 **94 KB**，详交 `03-wxss-layout-and-spec-gaps.md` 样式专项评估）。

---

## 3. 全量 40 个 `.vue` 文件审计矩阵（覆盖证明）

- **入口与页面（9 个）**：
  - `App.vue`：`onLaunch`/`onShow`/`onHide` 正常。
  - `pages/auth/login.vue`：单根，纯 `@tap`，合规。
  - `pages/index/index.vue`：`onMounted` + `onShow`（有 `hasCompletedInitialLoad` 防重）+ `onPullDownRefresh`，合规。
  - `pages/profile/index.vue`：`onShow` + `onPullDownRefresh`；`<image mode="aspectFill">`，合规（注：调用 `uni.chooseImage` 涉及隐私声明，见 P1-4）。
  - `pages/review/index.vue`：见 **P1-3**（`onShow` vs `onMounted` + `v-show` 包裹 `QuestionBankSection`）、**P2-1**（`<scroll-view :show-scrollbar="false">`）。
  - `subpackages/material/pages/course/index.vue`：`onLoad` + `onShow` + `onPullDownRefresh` + `onUnmounted`（见 **P2-4**）。
  - `subpackages/material/pages/questions/index.vue`：见 **P1-3**（async `onLoad` 与 `onShow` 竞态）。
  - `subpackages/practice/pages/session/index.vue`：`onLoad` + `onUnload` + `onBeforeUnmount`（见 **P2-4**）。
  - `subpackages/report/pages/detail/index.vue`：`onLoad` + `onPullDownRefresh` + `onUnload`，合规。
- **共享组件（4 个）**：
  - `components/AiCoachDrawer.vue`：见 **P1-1**（`<textarea>` 缺 `fixed`、`@confirm`/`show-confirm-bar` 冲突、`auto-height`）。
  - `components/BackgroundTaskBar.vue`：`virtualHost: true`，`onMounted`，`:style="{ width }"` 编译合规。
  - `components/CoachMessageList.vue`：`virtualHost: true`，见 **P2-2**（`scroll-into-view`）、**P1-4**（`setClipboardData` 隐私声明）。
  - `components/RichContent.vue`：`virtualHost: true`，`<rich-text :nodes="nodes" user-select />`，AST 标签全部在微信白名单内，合规。
- **主包业务组件（13 个）**：
  - `FolderFilterBar.vue`（**P2-1**）、`FolderFormModal.vue`（**P1-2** 缺 `cursor-spacing`）、`MaterialItemCard.vue`（4 处 `@tap.stop` -> `catchtap` 合规）、`LearningStatisticsCard.vue`（合规）、`ProfileEditModal.vue`（**P1-2** 缺 `cursor-spacing`）、`MasteryOverviewCard.vue`（合规）、`MasteryPointList.vue`（合规）、`PracticeEntryCard.vue`（合规）、`QuestionBankSection.vue`（**P1-3** `v-show` 下 `onMounted` 预拉取）、`QuestionBatchRow.vue`（`Map` prop 与命名插槽经实证合规）、`QuestionBankQuestionRow.vue`（`<slot name="action">` 经 `vendor.js` 实证合规）、`WrongBookSection.vue`（**P2-1**）、`WrongRecordCard.vue`（合规）。
- **分包业务组件（14 个，含 2 个死组件）**：
  - `KnowledgePointList.vue`（3 处 `@tap.stop` -> `catchtap` 合规）、`KnowledgePointPickerDrawer.vue`（`virtualHost: true`，`catchtap` 在 `<scroll-view>` 内不影响滚动，箭头函数已编入 JS 合规）、`KnowledgeSnippetModal.vue`（`structured_content` 经 `adapters/knowledge.ts:66-68` 归一化为数组，安全）、`MaterialCourseHeader.vue`（合规）、`QuestionConfigPanel.vue`（`<slider>` 与 `@update:compose-mode` 经 `vendor.js` 实证合规）、`QuestionReadyCard.vue`（合规）、`QuestionPreviewCard.vue` & `QuestionPreviewPanel.vue`（**P2-5** 死组件）、`AnswerCardDrawer.vue`（合规，独立 `.modal-backdrop`）、`PracticeQuestionBody.vue`（**P1-2**）、`AdaptivePracticeCard.vue`（**P2-4** 4 根无 `virtualHost`）、`AttemptResultCard.vue`（合规）、`GradingActionModal.vue`（**P1-1**、**P1-2**）、`ReportSummaryCard.vue`（**P2-4** 2 根无 `virtualHost`）。

---

## 4. 已排除的误报清单（经编译产物与 `common/vendor.js` 实证安全）

| 疑似风险点 | 实证依据（消除误报） |
| --- | --- |
| 不支持的 Vue 3 模板特性（`v-html` / `<component :is>` / `<Teleport>` / `<Transition>` / `<KeepAlive>` / `<Suspense>` / `v-bind="obj"` / `v-on="obj"`） | 全仓 40 个 `.vue` 扫描命中数为 **0**。 |
| 模板中 `?.` / `??` / 箭头函数 `=>` 编入 WXML 报错 | UniApp Vue 3 将模板表达式统一编入 `.js` 渲染函数，全仓 `.wxml` 仅含简单绑定（`{{a}}`、`catchtap="{{group.f}}"`），无非法 WXML 表达式。 |
| `QuestionBankQuestionRow.vue:23` `<slot name="action" />` 未显式声明 `multipleSlots: true` | `dist/dev/mp-weixin/common/vendor.js:7377` 在 `parseComponent` 中自动为所有组件注入 `multipleSlots: true`。 |
| `QuestionBankSection.vue` 向 `QuestionBatchRow` 传递 ES6 `Map` props（`wrongMarks` / `questionDetails` / `detailErrors`）是否会被 `setData` 序列化破坏 | `common/vendor.js:6605-6622` 实证 UniApp 通过内存 `propsCaches` + `u-p` 索引传递 props（不走 `setData` 序列化），且 `useBatchQuestionsCache.ts` 与 `useWrongMarking.ts` 每次更新均创建 `new Map(...)` 触发引用变更。 |
| `QuestionConfigPanel.vue` `emit('update:composeMode')` 与父级 `@update:compose-mode` 大小写不匹配 | `common/vendor.js:181-184, 7488-7491` 通过 `customizeEvent` 将 `:` 转 `-` 并驼峰化为 `updateComposeMode`，与 `questions/index.wxml` 的 `bindupdateComposeMode` 完全一致。 |
| `pages/review/index.vue:115` `ref="bankSection"` + `defineExpose` 在小程序端失效 | `pages/review/index.wxml:1` 编译为 `u-r="bankSection"`，`index.js:149` 编译为 `common_vendor.sr(bankSection, ...)`，`QuestionBankSection.js:48` 生成 `__expose({ refresh, loadBatches })`，机制完整。 |
| `v-show` 直接作用于自定义组件导致失效 | 全仓仅 1 处 `v-show`（`pages/review/index.vue:113`），写在原生 `<view>` 上且该 `<view>` 无 `display: flex`，编译为 `<view hidden="{{!M}}">`，生效正常。 |
| `pages.json` `tabBar` 未配置 `iconPath` / `selectedIconPath` | 微信官方文档确认 `iconPath` 与 `selectedIconPath` 为选填项，纯文字 tabBar 合法。 |
| 组件递归自引用导致 WXML 死循环或 props 丢失 | 检查全部编译产物 `*.json` 的 `usingComponents`，无任何自引用或循环引用；知识树已在 `useCourseDetail.ts` 中扁平化。 |
| `<rich-text :nodes>` 生成非白名单 HTML 标签被微信整节点丢弃 | `src/utils/richText*.ts` 仅产出 13 种标签（`blockquote`/`br`/`code`/`div`/`em`/`p`/`span`/`strong`/`table`/`tbody`/`td`/`th`/`thead`/`tr`），全部在微信官方受信任标签白名单内。 |
| 组件误用页面级生命周期（`onLoad` / `onShow` / `onUnload`） | 全仓 31 个组件 + `composables/**/*.ts` 均未调用页面级生命周期钩子。 |

---

## 5. 发现的 `.trellis/spec/` 关联文档（供后续 `implement.jsonl` / `check.jsonl` 编排参考）

- `D:/code/Workspace/zhilian/.trellis/spec/frontend/index.md`（需同步更新 `.vue` 实际文件数与新增 `mp-weixin-compatibility.md` 索引）
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/component-guidelines.md`（历史快照停留在 2026-09-29，组件清单与实际严重脱节，需注意区分事实源）
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/network-contract.md`（与 `manifest.json` 60s `networkTimeout` 上限直接相关）
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/directory-structure.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/quality-guidelines.md`
