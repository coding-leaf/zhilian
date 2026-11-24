# Technical Design: 微信小程序 / UniApp 兼容性修复与可执行静态门禁

> **对应 PRD**：`prd.md`
> **调研报告**：`research/01-js-runtime-and-api-compat.md`、`02-vue-wxml-and-config-compat.md`、`03-wxss-layout-and-spec-gaps.md`

---

## 1. 跨层契约：课程重命名 `PATCH -> PUT`（R1.2）

- **后端**（`backend/app/api/v1/folders.py`）：
  - 在 `rename_folder` 路由处理器上同时挂载 `@router.put("/{folder_id}", response_model=FolderResponse)` 与既有 `@router.patch("/{folder_id}", response_model=FolderResponse)`（向后完全兼容既有后端单测、CLI 与外部调用，零破坏）。
- **前端**（`miniprogram/src/api/modules/folders.ts` & `miniprogram/src/utils/request.ts`）：
  - `apiRenameFolder` 改为 `method: 'PUT'`；
  - `RequestOptions['method']` 收敛为 `'GET' | 'POST' | 'PUT' | 'DELETE'`（微信 `wx.request` 官方白名单子集），移除 `request.ts` 内的 `as any` 方法强制转换。

---

## 2. 构建目标、`manifest.json` 与 JS 运行时兼容（R1.1, R1.3, R2.1）

1. **`miniprogram/src/manifest.json`**：
   - `mp-weixin` 配置：
     - `"__usePrivacyCheck__": true`
     - `"lazyCodeLoading": "requiredComponents"`
     - `"setting": { "urlCheck": false, "es6": true, "enhance": true, "postcss": true, "minified": true }`
     - `"networkTimeout": { "request": 60000, "uploadFile": 60000 }`（符合微信官方 60,000ms 硬上限；同步调整 `requestError.ts::UPLOAD_REQUEST_TIMEOUT_MS = 60_000`）。
2. **`miniprogram/vite.config.ts`**：
   - 在 `build` 中显式设置 `target: 'es2019'`（esbuild 降级 `??`、optional catch binding `catch {}`、`?.`），确保低版本微信基础库与旧 iOS JSCore 不出现语法白屏。
3. **运行时安全替换**：
   - `miniprogram/src/utils/richTextMath.ts`：用 `[\u0300-\u036f]` 替代 `\p{M}` Unicode 属性转义，零行为变化且不依赖高版本正则引擎。
   - `miniprogram/src/composables/useMaterialUpload.ts` & `miniprogram/src/pages/profile/index.vue`：
     - 将停维护的 `uni.chooseImage` 替换为 `uni.chooseMedia({ count: 1, mediaType: ['image'], sourceType: [...] })`（并在 `tempFiles[0].tempFilePath` 取路径；针对旧测试 mock 兼容 `chooseMedia`）；
     - `useMaterialUpload.ts` 使用 `typeof wx !== 'undefined' && typeof wx.chooseMessageFile === 'function'` 替代未判空 `globalThis.wx`；
     - `fail` 回调检查 `errMsg` 包含 `cancel` 时静默返回，否则通过 `safeShowToast` 清晰提示权限/隐私授权失败原因。

---

## 3. Toast / Loading 互斥、安全路由栈与登录单飞（R2.2, R2.3）

1. **`miniprogram/src/utils/loadingGuard.ts`**：
   - 导出 `extractUserErrorMessage(err: unknown, fallback: string): string`：若 `err instanceof RequestError` 返回 `err.userMessage`（绝不包含 `[METHOD URL]` 调试尾巴）；否则返回 `err?.message`（剥离潜在 URL 片段）或 `fallback`。
   - 升级 `safeShowToast(options)`：
     - 当 `icon` 为 `'success' | 'error' | 'loading'` 且标题长度 `> 7` 时自动降级为 `icon: 'none'`（避免微信强截断）；
     - 先确认清理遮罩态后再弹 Toast，避免 `hideLoading()` 误杀刚弹出的 Toast。
   - 跳转前 Toast：在 `useMaterialUpload.ts` / `request.ts` 等弹 Toast 后立即跳转处，避免同步同帧被页面销毁冲掉（如 `request.ts` 在 `reLaunch` 后延迟微任务/短定时或交由跳转后提示，`useMaterialUpload.ts` 短延迟 `300ms` 再 `navigateTo`）。
2. **`miniprogram/src/utils/navigation.ts`**（新建，约 25 行）：
   - `safeNavigateTo(url: string): void`：检测 `typeof getCurrentPages === 'function' && getCurrentPages().length >= 9` 时自动降级 `uni.redirectTo({ url })`，否则 `uni.navigateTo({ url })`，彻底杜绝 `course ↔ questions ↔ AiCoachDrawer/BackgroundTaskBar` 闭环撞穿微信 10 层页面栈上限。
3. **`miniprogram/src/stores/auth.ts`**：
   - `loginWithWechat` 增加 `inFlightLoginPromise` 单飞锁，并发触发共享同一个登录 Promise。

---

## 4. Vue/WXML 原生组件、WXSS 与生命周期修复（R3.1–R3.3）

1. **原生输入与浮层穿透**：
   - `AiCoachDrawer.vue`：`<textarea>` 增加 `:fixed="true"`、`confirm-type="send"`、`:cursor-spacing="24"`；
   - `GradingActionModal.vue`：两处 `<textarea>` 增加 `:fixed="true"`、`:cursor-spacing="24"`，`<input>` 增加 `:cursor-spacing="24"`；
   - `FolderFormModal.vue`、`ProfileEditModal.vue`：`<input>` 增加 `:cursor-spacing="24"`；
   - `subpackages/practice/pages/session/index.vue` + `PracticeQuestionBody.vue`：向 `PracticeQuestionBody` 传 `:overlay-open="showAnswerCard || showCoach"`，当任意浮层打开时用 `v-if="!overlayOpen"` 隐藏底层 `<input>`/`<textarea>`（改为静态只读占位文本回显草稿），杜绝真机原生输入穿透；`<textarea>`/`<input>` 补 `:cursor-spacing="24"` 与 `:show-confirm-bar="false"`；填空题每个空维护本地 `blankDrafts` ref，仅在切题/外部 reset 时同步，不因每次击键经父级 `joinFillBlankAnswers` 回写触发光标跳动。
2. **WXSS 兼容修复**：
   - `subpackages/material/questions.scss` + `QuestionPreviewPanel.vue`（及任何引用方）：将 `.start-btn[disabled]` 替换为 `.start-btn.is-disabled`。
   - `miniprogram/src/styles/common.scss` + `App.vue` + 重点按钮组件（`report.scss` `.reinforce-bar-btn`、`MaterialCourseHeader.vue` `.refresh-progress-btn`、`MaterialItemCard.vue` `.manual-parse-btn`、`session.scss` `.draft-retry-btn` 等）：为自定义按钮补齐 `&::after { border: none; }` 与 `margin: 0; line-height` 重置，彻底消除微信默认双层灰框。
   - `pages/review/index.vue` + `review.scss`：将 `BackgroundTaskBar` 所在容器 `z-index` 提升至 `calc(var(--z-sticky) + 5)`（或包在正常流顶部且仅给 `.segment-bar` 设 `sticky; top: 0; z-index: 20`，当存在活跃任务条时任务条位于更高层或独立吸顶区不互遮）。
   - `CoachMessageList.vue`：移除 `uni.setClipboardData` 成功后的重复 `uni.showToast`（微信原生已弹「内容已复制」）；修复 `scrollIntoViewId` 相同 ID 合并问题（先置空再 `nextTick` 赋值）。
3. **页面生命周期与按钮防重**：
   - `subpackages/material/pages/questions/index.vue`：新增 `isInitialLoading` 标志，`onLoad` 异步期间屏蔽 `onShow` 抢跑 `attachActiveJobForScope()`，避免覆盖 `?view=generated` 刚加载的 `ready` 状态。
   - `pages/review/index.vue`：用 `hasInitialized` 标志消除首次进入时 `onShow`（先于 `onMounted`）+ `onMounted` 触发的双重 `refreshAll()`，同时收敛 `QuestionBankSection` 仅在切到题库 Tab 时加载或去重。
   - `pages/auth/login.vue` 等全仓 `<button :loading="...">` 站点统一同时绑定 `:disabled="..."`。

---

## 5. 可执行规范与静态门禁（R4）

1. **新建 `.trellis/spec/frontend/mp-weixin-compatibility.md`**：按 7 节 Code-Spec 深度记录：
   - 1. JS/TS 运行时与编译产物红线（零动态 `import()`、`es2019` 目标、无 Web-only 全局、无 `\p{...}` 正则、无 `PATCH`）
   - 2. 微信平台 API 契约（`chooseMedia` 替代 `chooseImage`、`__usePrivacyCheck__`、`networkTimeout <= 60000`、`safeShowToast`/7 字图标限制、10 层路由栈 `safeNavigateTo`、`<button :loading>` 必配 `:disabled`、`loginWithWechat` 单飞）
   - 3. Vue 3 / WXML 模板与生命周期红线（浮层内 `<textarea :fixed="true">` + 隐藏底层输入、受控输入防光标跳动、`onShow` 早于 `onMounted` 竞态）
   - 4. WXSS 与样式红线（禁止 `[disabled]`/`*`/`:deep(`/`url(`、按钮 `::after { border: none; }`、吸顶层级管理）
   - 5. Wrong vs Correct 对照表 + 静态门禁测试说明
2. **新建 `miniprogram/tests/mpWeixinCompatGuard.spec.ts`**：直接扫描 `miniprogram/src/**` 与 `manifest.json`，把核心 P0/P1 红线固化为 Vitest 自动化门禁。
