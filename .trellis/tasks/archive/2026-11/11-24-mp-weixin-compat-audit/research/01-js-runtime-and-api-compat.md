# 微信小程序 JS 运行时、编译产物与平台 API 兼容性专项审计报告

> **审计角色**：`audit-mp-js-runtime`（只读审计）
> **审计范围**：`miniprogram/src/**`（全部 `.ts`/`.js`/`.vue` 及工程配置）+ 实际编译产物 `miniprogram/dist/dev/mp-weixin/**`（全部 105 个业务 `.js` 文件、`common/vendor.js`、`app.json`、`project.config.json`）
> **基准依据**：微信小程序官方开发文档（`developers.weixin.qq.com`）与 UniApp Vue 3（`@dcloudio/uni-mp-weixin@3.0.0-4020920240930001` / Vite 5.2.8）官方规范
> **审计日期**：2026-11-24

---

## 1. 审计总览与严重度统计

| 严重度 | 数量 | 核心问题摘要 |
| --- | :---: | --- |
| **P0（真机必崩 / 核心功能不可用）** | **2** | ① `wx.request` 不支持 `PATCH`（课程重命名真机必败）；② 隐私合规配置/弹窗全缺失 + `uni.chooseImage` 停止维护 + `fail` 静默吞错 |
| **P1（真机交互降级 / 高危运行时故障）** | **5** | ① 产物残留 198 处 `??` / 25 处 `catch {}` / `\p{M}` / `globalThis`；② Toast 截断、URL 泄露与路由秒杀 Toast；③ 21 处 `navigateTo` 零页面栈守卫（可撞穿 10 层上限）；④ 24 处裸 `uni.showToast` 绕过 `loadingGuard` 槽位保护；⑤ 登录无单飞锁且 `<button :loading>` 未绑定 `:disabled` |
| **P2（脆弱性 / 隐患 / 未来防护）** | **4** | ① `setStorageSync` 缺 `try/catch` 及草稿无 LRU（1MB/10MB 配额风险）；② `uploadFile` 透传 `formData: undefined`；③ `tsconfig.json` 引入 `"DOM"` 掩盖 Web API 误用；④ 头像/昵称未采用微信原生能力 + 1 处 query 未 `encodeURIComponent` |

### 已实证通过（零误报核验项）

1. **打包器与模块产物（`dist/dev/mp-weixin` 全量 105 个业务 JS 静态扫描）**：
   - `request.ts` 热修已生效：`dist/dev/mp-weixin/utils/request.js:99` 编译为 `common_vendor.getActivePinia()`，全仓产物 **0 处** `.js".then` 非法动态导入、**0 处** `import(`、**0 处** 残留 `import.meta`（`VITE_API_BASE_URL` 已正常内联替换）。
   - 全量 `require()` 路径 **0 处**断裂、模块依赖图 **0 个**循环引用环（`CYCLES: NONE`）。
2. **Web-only 全局对象**：
   - 扫描 `window`、`document`、`navigator`、`location`、`localStorage`、`sessionStorage`、`URL`、`URLSearchParams`、`AbortController`、`AbortSignal`、`fetch`、`FormData`、`Blob`、`File`、`TextEncoder`、`TextDecoder`、`atob`、`btoa`、`crypto`、`structuredClone`、`Intl`、`performance`、`queueMicrotask`、`requestAnimationFrame`、`CustomEvent`、`HTMLElement`、`MouseEvent`、`XMLHttpRequest`、`WebSocket`、`alert`、`confirm`、`prompt`：
   - `miniprogram/src/**` 与 `miniprogram/dist/dev/mp-weixin/**`（除框架 `common/vendor.js`）均 **0 处误用**。
3. **`uni.request` 并发上限与超时治理**：
   - `MAX_CONCURRENT_REQUESTS = 6` FIFO 并发调度低于微信 10 并发硬上限；`manifest.json` 已显式声明 `networkTimeout: { request: 90000, uploadFile: 120000 }` 与 `DEFAULT_REQUEST_TIMEOUT_MS`/`LONG_REQUEST_TIMEOUT_MS`/`UPLOAD_REQUEST_TIMEOUT_MS` 对齐；无 `Content-Type` 大小写重复 Header 冲突。
4. **废弃登录/用户信息 API**：
   - 全仓 **0 处** 调用已废弃的 `uni.getUserProfile` / `wx.getUserProfile` / `wx.getUserInfo`。

---

## 2. P0 级别实证缺陷（真机崩溃 / 功能失效）

### [P0-1] `wx.request` 不支持 HTTP `PATCH` 方法，课程重命名真机必败

- **源码位置**：
  - `miniprogram/src/api/modules/folders.ts:23-29`（`apiRenameFolder` 使用 `method: 'PATCH'`）
  - `miniprogram/src/utils/request.ts:233`（`RequestOptions['method']` 允许 `'PATCH'`）及 `miniprogram/src/utils/request.ts:271`（`method: method as any` 强行绕过 `@dcloudio/types` 的类型校验）
  - 后端联动事实源：`backend/app/api/v1/folders.py:202`（目前仅注册了 `@router.patch`）
- **编译产物实证**：
  - `miniprogram/dist/dev/mp-weixin/api/modules/folders.js:16-22`：
    ```js
    function apiRenameFolder(folderId, name) {
      return utils_request.request({
        url: `/folders/${folderId}`,
        method: "PATCH",
        data: { name }
      });
    }
    ```
  - 经 `dist/dev/mp-weixin/utils/request.js` 原样透传给 `common_vendor.index.request({ method: "PATCH", ... })`。
- **官方规范依据**：
  - 微信小程序官方 `wx.request` 文档明确规定 `method` 合法值仅包含：`OPTIONS`、`GET`、`HEAD`、`POST`、`PUT`、`DELETE`、`TRACE`、`CONNECT`，**不支持 `PATCH`**。
  - 开发者工具模拟器有时会放行，但 iOS/Android 真机底层网络库会直接拒绝并触发 `fail`（`request:fail invalid method`），导致“课程重命名”功能在真机完全不可用。
- **修复建议**：
  1. 后端 `backend/app/api/v1/folders.py` 为重命名端点改为（或兼容新增）`@router.put("/{folder_id}")`；
  2. 前端 `apiRenameFolder` 改为 `method: 'PUT'`，同时从 `RequestOptions['method']` 中移除 `'PATCH'` 并去掉 `request.ts:271` 的 `as any` 强转，让 TypeScript 编译期即可拦截非法 HTTP 动词。

---

### [P0-2] 微信用户隐私合规链路完全缺失 + `uni.chooseImage` 已停止维护 + `fail` 静默吞错

- **源码位置**：
  - `miniprogram/src/manifest.json:11-24`：未配置 `"__usePrivacyCheck__": true`；全仓 **0 处** `wx.getPrivacySetting` / `wx.onNeedPrivacyAuthorization` / `wx.requirePrivacyAuthorize` 接入；
  - `miniprogram/src/pages/index/composables/useMaterialUpload.ts:68-79`：调用已停维护的 `uni.chooseImage`，且 `78` 行 `fail: () => {}` 静默吞错；
  - `miniprogram/src/pages/index/composables/useMaterialUpload.ts:87-98`：调用隐私接口 `wx.chooseMessageFile`，且 `97` 行 `fail: () => {}` 静默吞错；
  - `miniprogram/src/pages/profile/index.vue:110-127`：调用已停维护的 `uni.chooseImage` 选择头像，且**未提供 `fail` 回调**；
  - `miniprogram/src/components/CoachMessageList.vue:108-112`：调用隐私接口 `uni.setClipboardData`。
- **编译产物实证**：
  - `miniprogram/dist/dev/mp-weixin/app.json:1-60`：无 `"__usePrivacyCheck__"` 声明；
  - `miniprogram/dist/dev/mp-weixin/pages/index/composables/useMaterialUpload.js:51-64, 71-84`：原样输出 `common_vendor.index.chooseImage` 与空 `fail: () => {}`。
- **官方规范依据**：
  - 微信官方文档明确标注：**自基础库 `2.21.0` 起 `wx.chooseImage` 停止维护**，请统一迁移为 `wx.chooseMedia`（`mediaType: ['image']`）。
  - 微信《小程序用户隐私保护指引》强制合规规范：`wx.chooseMedia` / `wx.chooseImage`（选中的照片或视频信息）、`wx.chooseMessageFile`（选中的文件）、`wx.setClipboardData`（剪贴板）均为隐私相关接口。未在 MP 后台声明隐私项或用户未同意隐私协议时，真机调用将直接进入 `fail`（`errno: 104` 拒绝授权 / `errno: 112` 未在隐私协议声明）。
  - 当前上传与头像路径将 `fail` 静默吞掉或忽略，真机被隐私拦截或系统相机/相册权限被拒时，用户点击按钮后**界面无任何反应、无任何提示**。
- **修复建议**：
  1. 在 `manifest.json` 的 `mp-weixin` 下显式补充 `"__usePrivacyCheck__": true`，并在 MP 后台配置「选中的照片或视频信息」「选中的文件」「剪贴板」隐私声明；
  2. 讲义图片上传由 `uni.chooseImage` 迁移至 `#ifdef MP-WEIXIN` 下的 `uni.chooseMedia({ count: 1, mediaType: ['image'], ... })`（其他端回退 `uni.chooseImage`）；
  3. 禁止空 `fail: () => {}`：仅对 `errMsg` 含 `cancel`（用户主动取消）静默，对其余错误（权限拒绝、隐私未授权 `errno: 104/112`）记录 `console.error` 并给出可行动提示（必要时引导 `uni.openSetting` 或触发 `wx.requirePrivacyAuthorize`）。

---

## 3. P1 级别实证缺陷（真机交互降级 / 跨机型兼容风险）

### [P1-1] 编译产物残留大量未降级 ES2018–ES2020 语法与运行时内建对象（`??` / `catch {}` / `\p{M}` / `globalThis` / `Promise.allSettled`）

- **源码与配置位置**：
  - `miniprogram/vite.config.ts:7-20`：未配置 `build.target`（默认按高版本 esbuild 目标输出，仅转译了 `?.` 而未转译 `??` 与 `catch {}`）；
  - `miniprogram/src/manifest.json:13-18`：仅开启 `es6: true`，未配置 `enhance: true`，且未在工程配置/发布基线中约束最低基础库版本；
  - `miniprogram/src/utils/richTextMath.ts:134`：`/[^\s\p{M}]/gu`（ES2018 Unicode 属性转义正则）；
  - `miniprogram/src/pages/index/composables/useMaterialUpload.ts:107`：`const wxAny = (globalThis as any).wx || (typeof wx !== 'undefined' ? wx : null)`（直接访问 `globalThis` 属性未先 `typeof globalThis !== 'undefined'` 判空）；
  - `miniprogram/src/utils/draftQueue.ts:142`：`Promise.allSettled(...)`（ES2020）；
  - `miniprogram/src/api/adapters/practice.ts:87`：`Object.fromEntries(...)`（ES2019）；
  - `miniprogram/src/api/adapters/question.ts:61` 与 `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts:480`：`.flatMap(...)`（ES2019）。
- **编译产物实证**：
  - `miniprogram/dist/dev/mp-weixin/project.config.json:6-15`：`"es6": true`，无 `"enhance"`，`"libVersion": ""`；
  - 对 `dist/dev/mp-weixin` 全部 105 个业务 `.js` 产物实测扫描结果：
    - **`??`（ES2020 空值合并）**：**198 处** 原样保留（如 `dist/dev/mp-weixin/api/adapters/diagnosis.js:4-24` 等 35+ 文件）；
    - **`catch {`（ES2019 可选 catch 绑定）**：**25 处** 原样保留（如 `dist/dev/mp-weixin/utils/request.js:104,129,161,343,369`、`composables/useCoachChat.js` 等 12 文件）；
    - **`/[^\s\p{M}]/gu`**：`dist/dev/mp-weixin/utils/richTextMath.js:87` 原样保留；
    - **`Promise.allSettled`**：`dist/dev/mp-weixin/utils/draftQueue.js:77` 原样保留；
    - **`globalThis.wx`**：`dist/dev/mp-weixin/pages/index/composables/useMaterialUpload.js:89` 编译为：
      ```js
      const wxAny = globalThis.wx || (typeof common_vendor.wx$1 !== "undefined" ? common_vendor.wx$1 : null);
      ```
      （注：经核对 `common/vendor.js:1485-1496`，`initWx()` 确实把所有 `typeof wx[key] === 'function'` 复制到 `newWx` 并挂载 `globalThis.wx`（含 `chooseMessageFile`），且做了 `typeof globalThis !== "undefined"` 防护；但业务源码第 107 行没有该防护，低版本环境下会在 `||` 之前直接抛出 `ReferenceError: globalThis is not defined`）。
- **官方规范依据**：
  - 微信开发者工具中单独 `es6: true`（旧 Babel 6 路径）不支持转译 ES2020 `??` 与 ES2019 `catch {}`，且在 UniApp Vite 工程下官方推荐由 Vite `build.target` 完成语法降级（而非依赖微信工具二次 Babel 编译导致体积膨胀或冲突）。
  - 微信官方文档：旧版 iOS JSCore 解析 `??` / `catch {}` 会直接 `SyntaxError` 白屏；`\p{M}` 在部分旧 iOS JSCore 上会抛出 `Invalid property name`；`globalThis` 需基础库 `>= 2.10.4`、`Promise.allSettled` 需 `>= 2.11.2`（且 iOS 15 及以下 Promise 基于 `setTimeout` 宏任务实现）。
- **修复建议**：
  1. 在 `miniprogram/vite.config.ts` 显式配置 `build: { target: 'es2015' }`（或 `'es6'`），并在 `build:mp-weixin` 后校验产物无 `??` 和 `catch {`；
  2. `richTextMath.ts:134` 将 `\p{M}` 替换为显式 Unicode 组合音标区间（如 `/[^\s\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]/gu`），彻底规避旧 iOS JSCore 正则崩毁；
  3. `useMaterialUpload.ts:107` 改为 `const wxAny = (typeof globalThis !== 'undefined' && (globalThis as any).wx) || (typeof wx !== 'undefined' ? wx : null)`（或直接通过 `#ifdef MP-WEIXIN` 下 `typeof wx !== 'undefined' ? wx : null`）；
  4. `draftQueue.ts:142` 的 `Promise.allSettled` 可替换为 `Promise.all(workers.map((p) => p.catch(() => undefined)))`（当前本就不读取 settled 返回值！），并统一在 MP 后台将最低基础库设定为 `>= 2.21.0`（与 `wx.chooseMedia` 对齐）。

---

### [P1-2] `uni.showToast` 多处触发真机文案截断、URL 泄露、路由秒杀 Toast 与剪贴板双 Toast

- **实证点 A — 带图标 Toast 超过 7 个汉字（真机必截断）**：
  - 官方规则：微信 `wx.showToast` 当 `icon` 为 `'success' | 'error' | 'loading'` 时，**`title` 最多显示 7 个汉字**，超出部分会被直接截断；仅当 `icon: 'none'` 时最多显示 2 行。
  - 违规位置：
    - `miniprogram/src/pages/index/composables/useMaterialUpload.ts:55-58`：`'上传成功，已开始后台解析'`（11 汉字）/ `'上传成功，可手动点击开始解析'`（13 汉字）+ `icon: 'success'`；
    - `miniprogram/src/subpackages/material/pages/questions/index.vue:117` & `213`：`` `试卷已就绪（${count} 题）` ``（9~10 字符）+ `icon: 'success'`；
    - `miniprogram/src/subpackages/report/composables/useReportDetail.ts:142`：`safeShowToast(res.message || '复查已完成', 'success')`（将不定长后端 `res.message` 传给 `icon: 'success'`）。
- **实证点 B — `RequestError.message` 携带完整 HTTP URL 被直接传入 Toast（超 2 行截断 + 违反 `network-contract.md`）**：
  - 根因：`miniprogram/src/utils/requestError.ts:72` 定义 `super(\`${summary} [${method} ${url}]\`)`，因此 `error.message` 包含 `[POST http://.../api/v1/...]`，而 `error.userMessage` 才是短文案。
  - 13 处违规调用（同时未过滤 `instanceof RequestError`，会在 `request.ts:251` 弹出短 Toast 后**立刻二次弹出带 URL 的超长 Toast 将前者覆盖**）：
    - `miniprogram/src/pages/index/composables/useFolderModal.ts:53`
    - `miniprogram/src/pages/profile/index.vue:137`
    - `miniprogram/src/pages/review/composables/useReviewCenter.ts:268, 307, 311, 326, 371, 403`
    - `miniprogram/src/subpackages/practice/pages/session/index.vue:185, 273`
    - `miniprogram/src/subpackages/report/composables/useReportDetail.ts:123, 150, 173`
- **实证点 C — `showToast` 后同步立刻跳转页面，真机 Toast 闪灭**：
  - 官方行为：`wx.showToast` 依附当前页面渲染层，紧跟 `wx.reLaunch` / `wx.navigateTo` 会因页面销毁或转场立即打断 Toast。
  - 违规位置：
    - `miniprogram/src/utils/request.ts:177-181`：`uni.showToast({ title: '登录已过期，请重新登录', icon: 'none' })` 紧接同步 `uni.reLaunch({ url: '/pages/auth/login' })`；
    - `miniprogram/src/pages/index/composables/useMaterialUpload.ts:55-59` + `miniprogram/src/pages/index/index.vue:191-196, 203`：`safeShowToast(...)` 后同步立刻 `deps.onUploaded(item)` 触发 `uni.navigateTo`。
- **实证点 D — `uni.setClipboardData` 触发系统原生 Toast 后叠加自定义 Toast**：
  - `miniprogram/src/components/CoachMessageList.vue:108-112`：微信 `wx.setClipboardData` 成功时客户端原生会自动弹出 1.5s「内容已复制」，随后 `success` 回调又调用 `uni.showToast({ title: '已复制解析', icon: 'success' })`，真机连续闪烁两个 Toast。

---

### [P1-3] 全仓 21 处 `uni.navigateTo` 零页面栈守卫，存在多条闭环路径撞穿 10 层页面栈上限

- **源码位置**：全仓 `getCurrentPages()` 调用次数为 **0**，且存在多条可循环压栈的 `uni.navigateTo` 链路：
  - `miniprogram/src/subpackages/material/pages/questions/index.vue:216-223`（`goBrowseMaterial` 从出题页去讲义详情页使用 `navigateTo`）↔ `miniprogram/src/subpackages/material/pages/course/index.vue:159, 172`（从讲义详情页去出题页使用 `navigateTo`）；
  - `miniprogram/src/components/AiCoachDrawer.vue:117-122`（`openSource` 在任意页面的助教抽屉里点击来源讲义，均使用 `navigateTo`）；
  - `miniprogram/src/components/BackgroundTaskBar.vue:53-68`、`course/index.vue:117, 125`、`questions/index.vue:190`（顶部后台任务条在任意深层页点击“查看讲义/进入练习”均使用 `navigateTo`）。
- **官方规范依据**：
  - 微信小程序页面栈硬上限为 **10 层**（在无合法 AppID / `touristappid` 调试或部分老版本基础库下甚至只有 **5 层**），超过后 `wx.navigateTo` 直接触发 `fail`：`navigateTo:fail webview count limit exceed`。
- **修复建议**：
  1. 封装统一的 `safeNavigateTo(url, options)` 工具函数：调用前检查 `getCurrentPages().length`，若 `>= 9`（接近上限）自动降级为 `uni.redirectTo`，避免死锁；
  2. `questions/index.vue::goBrowseMaterial` 若上一页已是同一 `materialId` 的 `course/index`，优先 `uni.navigateBack()` 或 `uni.redirectTo()`。

---

### [P1-4] 24 处裸 `uni.showToast` 绕过 `loadingGuard` 单槽位保护，且上传自动解析失败被吞并覆盖

- **源码位置**：
  - `miniprogram/src/utils/loadingGuard.ts:13-66` 已正确实现引用计数与 `isNativeLoadingVisible` 互斥状态，但以下文件绕过 `safeShowToast` 直接调用裸 `uni.showToast`（合计 24 处）：
    - `pages/auth/login.vue:25,29,35`、`pages/profile/index.vue:96,120,122,134,137,151`、`pages/profile/components/ProfileEditModal.vue:77`、`pages/index/composables/useFolderModal.ts:41,49,53,70`、`pages/index/composables/useMaterialDelete.ts:46,50`、`pages/review/composables/useBatchPracticeLaunch.ts:87,95,114,119,124`、`pages/review/composables/useWrongMarking.ts:103,112,117`、`subpackages/material/composables/useComposeConfig.ts:158`、`components/AiCoachDrawer.vue:120`、`components/BackgroundTaskBar.vue:57,65,71`、`components/CoachMessageList.vue:110,111`。
  - 另见 `miniprogram/src/pages/index/composables/useMaterialUpload.ts:47-59`：`withBlockingLoading` 内部依次执行 `uploadMaterial` -> `triggerAutoParse` -> `refreshList`。若 `triggerAutoParse` 失败，`request.ts:250-251` 会调 `dismissBlockingLoading()` 并弹错误 Toast，但 `triggerAutoParse` 吞错返回 `false`，随后 `55` 行再弹 `'上传成功，可手动点击开始解析'` 并立刻 `navigateTo`，导致 Loading 提前消失且错误 Toast 被覆盖。
- **官方规范依据**：
  - 微信原生 `wx.showLoading` 与 `wx.showToast` 共用同一个全局弹窗槽位。若在 `withBlockingLoading` 在途期间发生任意裸 `uni.showToast`，原生 Loading 会被顶掉而 `loadingGuard` 的 `isNativeLoadingVisible` 仍为 `true`，待 `withBlockingLoading` 结束执行 `uni.hideLoading()` 时将**瞬间关闭刚弹出的 Toast**并触发「showLoading 与 hideLoading 必须配对使用」告警。
- **修复建议**：
  - 全仓业务代码统一收口至 `safeShowToast()`（可在 ESLint 中通过 `no-restricted-syntax` 禁止除 `loadingGuard.ts` / `request.ts` 外直接调用 `uni.showToast` / `uni.showLoading` / `uni.hideLoading`）。

---

### [P1-5] 微信登录缺少单飞并发锁，且多处 `<button :loading>` 未同时绑定 `:disabled`

- **源码位置**：
  - `miniprogram/src/stores/auth.ts:131-164`：`loginWithWechat()` 无单飞锁（不同于 `request.ts:184` 的 `refreshAccessTokenSingleFlight`）；而 `miniprogram/src/pages/index/index.vue:225` 在冷启 `onMounted` 自动调用静默登录，若用户同期手动点「快捷登录」会并发发起多个 `uni.login()`。
  - `miniprogram/src/pages/auth/login.vue:6, 20-40`：`<button :loading="isLoading" @tap="handleLogin">` 未绑定 `:disabled="isLoading"` 且 `handleLogin` 入口未做 `if (isLoading.value) return` 防重。
  - 同类 `<button :loading>` 漏绑 `:disabled` 的位置：
    - `miniprogram/src/pages/index/components/FolderFormModal.vue:22`
    - `miniprogram/src/pages/profile/components/ProfileEditModal.vue:24, 35`
    - `miniprogram/src/subpackages/report/components/GradingActionModal.vue:53`
    - `miniprogram/src/subpackages/practice/pages/session/index.vue:76`
    - `miniprogram/src/pages/review/components/QuestionBankSection.vue:55, 67`（第 67 行只绑了 `selectedCount === 0` 未含 `isStarting`）
    - `miniprogram/src/subpackages/report/components/AdaptivePracticeCard.vue:32, 41`
    - `miniprogram/src/subpackages/material/components/QuestionPreviewPanel.vue:15, 39`
- **官方规范依据**：
  - 微信小程序原生 `<button loading>` 仅展示转圈动画，**不会禁用点击事件**；连击仍会重复触发 `@tap`。
  - 微信 `wx.login` 返回的 `code` 有效期 5 分钟且**单次有效**；重复并发触发会导致多路 `POST /auth/login` 竞争写本地 token 与重复 `fetchProfile`。
- **修复建议**：
  1. 在 `stores/auth.ts` 为 `loginWithWechat` 增加单飞 Promise 复用；
  2. 为所有带 `:loading` 的提交类 `<button>` 同步绑定 `:disabled` 并在事件处理器首行做重入守卫。

---

## 4. P2 级别实证缺陷（脆弱性 / 工程防护缺口）

### [P2-1] `uni.setStorageSync` 缺少 `try/catch` 异常防护与练习草稿无 LRU 淘汰（1MB / 10MB 配额风险）

- **源码位置**：
  - `miniprogram/src/utils/practiceHelpers.ts:19, 31, 36, 38, 43, 44`
  - `miniprogram/src/stores/auth.ts:99, 100, 107, 115, 117, 126, 127`
  - `miniprogram/src/utils/request.ts:170, 171, 204, 206, 335, 352, 387, 447, 474`
- **官方规范依据**：
  - 微信 `wx.setStorageSync` 单个 key 上限 **1MB**，小程序本地总缓存上限 **10MB**，超限或受限环境会**同步抛出异常**。
  - `useCoachChat.ts` 已做好全量 `try/catch` + 30 会话 LRU 淘汰；但 `practice_draft_*` / `practice_submit_key_*` 仅在交卷成功后移除，长期未交卷的草稿永久累积。一旦配额耗尽，`practiceStore.recordAnswer` 中未包裹 `try/catch` 的 `writePracticeDraft` 会同步抛错，**直接阻断后面的 `draftQueue.enqueue` 云端保存**！
- **修复建议**：
  - 封装 `safeStorage`（`safeGetStorageSync` / `safeSetStorageSync` / `safeRemoveStorageSync`）统一包裹 `try/catch`，并为 `practice_draft_*` 增加与 `useCoachChat` 类似的轻量 LRU 淘汰（如保留最近 20 场未交卷练习草稿）。

---

### [P2-2] `uni.uploadFile` 透传 `formData: undefined` 在严格 iOS 基础库上的参数风险

- **源码位置**：
  - `miniprogram/src/api/modules/auth.ts:28`：`uploadFile<UserProfile>(filePath, 'file', undefined, '/users/me/avatar')`
  - `miniprogram/src/utils/request.ts:453-458`：`uni.uploadFile({ url: fullUrl, filePath, name, formData, header, ... })`
- **编译产物与框架核实**：
  - 核对 `dist/dev/mp-weixin/common/vendor.js`，UniApp 未对 `uploadFile` 注册参数清洗协议 shim，调用参数直接透传至 `wx.uploadFile`。
- **官方规范依据**：
  - 微信 `wx.uploadFile` 要求 `formData` 为 plain object 且其属性值均为字符串；在严格参数校验的 iOS 客户端/基础库中，显式传入 `{ formData: undefined }` 或内部含 `undefined` 值可能触发 `uploadFile:fail` 异常。
- **修复建议**：
  - 在 `request.ts::uploadFile` 中清洗 `formData`：仅当 `formData` 存在且含非空键值时才写入 `uni.uploadFile` 参数对象，并将值统一转为 `String(val)`。

---

### [P2-3] `tsconfig.json` 包含 `"DOM"` lib，导致编译期无法拦截浏览器专属 API

- **源码位置**：`miniprogram/tsconfig.json:12`（`"lib": ["ESNext", "DOM"]`）。
- **影响分析**：虽然当前代码库实证零误用浏览器全局对象，但 `"DOM"` 让 `window` / `document` / `localStorage` / `fetch` / `URLSearchParams` / `AbortController` / `FormData` 在 `vue-tsc` 下全部“合法”，而 Vitest 运行在 `happy-dom` 下也会全部通过，形成典型的“本地全绿、真机即崩”盲区。
- **修复建议**：将 `tsconfig.json` 的 `lib` 收敛为 `["ES2019"]` 或 `["ESNext"]`（移除 `"DOM"`，并保留 `@dcloudio/types` / `@uni-helper/uni-app-types`），测试文件继续由 `tsconfig.test.json` 单独配置。

---

### [P2-4] 头像/昵称采集未采用微信官方最新组件能力 & 1 处 query 参数未转义

- **源码位置**：
  - `miniprogram/src/pages/profile/index.vue:110` 与 `miniprogram/src/pages/profile/components/ProfileEditModal.vue:13-28`：虽已正确避开废弃的 `wx.getUserProfile`，但头像仍走已停维护的 `uni.chooseImage`，昵称输入框未启用微信官方推荐的 `<input type="nickname">`（可一键填充微信昵称并触发微信内容安全校验），头像按钮未采用 `<button open-type="chooseAvatar">`（免相册隐私授权即可一键选用微信头像或拍照/选图）。
  - `miniprogram/src/api/modules/questions.ts:65`：`url: \`/questions?material_id=${materialId}\`` 未对 `materialId` 做 `encodeURIComponent`（同文件第 89、90、127 行均已转义）。

---

## 5. 已盘点的 `.trellis/spec/` 相关规范路径（供 `implement.jsonl` / `check.jsonl` 编排复用）

- `.trellis/spec/frontend/index.md`（前端规范总索引）
- `.trellis/spec/frontend/network-contract.md`（网络层契约：`userMessage` vs `message`、`silentToast`、超时、并发）
- `.trellis/spec/frontend/api-payload-contracts.md`（前后端请求体语义契约）
- `.trellis/spec/frontend/component-guidelines.md`（组件规范）
- `.trellis/spec/frontend/state-management.md`（Pinia Store 职责与边界）
- `.trellis/spec/frontend/type-safety.md`（类型安全与适配器归一化边界）
- `.trellis/spec/frontend/quality-guidelines.md`（前端质量门禁与错误处理要求）
- `.trellis/spec/frontend/directory-structure.md`（主包/分包目录架构）
- `.trellis/spec/frontend/hook-guidelines.md`（组合式函数规范）
- **建议新增**：`.trellis/spec/frontend/mp-weixin-compatibility.md`（沉淀本次审计的 P0/P1/P2 规则及对应静态检查门禁：禁止 `PATCH`、禁止动态 `import()`、禁止 Web-only 全局变量、禁止裸 `uni.showToast`/`uni.chooseImage`、强制 `build.target` 降级检查、强制页面栈守卫等）。
