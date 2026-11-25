# 微信小程序（mp-weixin）兼容性规范

> **适用范围**：`miniprogram/src/**`、`miniprogram/vite.config.ts`、`miniprogram/src/manifest.json`、`backend/app/api/v1/**`（跨层 HTTP 方法契约）
> **最后核对**：2026-11-24（对照微信官方小程序文档、UniApp Vue 3 规范及 `dist/build/mp-weixin` 实测编译产物）
> **自动门禁**：[mpWeixinCompatGuard.spec.ts](../../../miniprogram/tests/mpWeixinCompatGuard.spec.ts)（随 `pnpm run test:unit` / `task verify-frontend` 自动执行）

---

## 1. Scope / Trigger

在以下任一改动前**必读本规范**：
- 新增或修改前端网络请求、HTTP 方法、模块导入、正则/JS 运行时工具函数；
- 调用 `uni.*` / `wx.*` 平台 API（媒体选择、隐私授权、路由跳转、Toast/Loading、剪贴板）；
- 编写或修改 `.vue` 模板、`<input>`/`<textarea>`/`<button>`/`<scroll-view>` 或页面生命周期钩子；
- 编写或修改 `.scss`/`.vue` 样式、吸顶定位或 `manifest.json`/`vite.config.ts`。

> **核心教训**：Vitest 运行在 Node/jsdom 下，无法暴露微信小程序 CJS 编译、WXML/WXSS 裁剪及 iOS/Android 原生组件差异。改动必须以 `pnpm run build:mp-weixin` 产物与本规范为准。

---

## 2. Signatures & Config Contracts

```json
// miniprogram/src/manifest.json -> "mp-weixin"
{
  "__usePrivacyCheck__": true,
  "lazyCodeLoading": "requiredComponents",
  "setting": { "urlCheck": false, "es6": true, "enhance": true, "postcss": true, "minified": true, "ignoreDevUnusedFiles": false, "ignoreUploadUnusedFiles": false }, // 避免 lazyCodeLoading 下微信静态分析误剔除共享组件间接 require 的工具模块（如 utils/katexRichText.js）
  "networkTimeout": { "request": 60000, "uploadFile": 60000 }
}
```

```ts
// miniprogram/vite.config.ts
build: { target: 'es2018' } // 同时降级 ?? / ?. 与 ES2019 optional catch {}

// miniprogram/src/utils/request.ts
method?: 'GET' | 'POST' | 'PUT' | 'DELETE' // 严禁 PATCH（wx.request 不支持）

// miniprogram/src/utils/navigation.ts
export function safeNavigateTo(url: string, options?: SafeNavigateOptions): void // >=9 层自动降级 redirectTo

// miniprogram/src/utils/loadingGuard.ts
export function safeShowToast(titleOrOptions: string | ToastOptions): void // icon 带图标超 7 字自动降级 none
export function extractUserErrorMessage(err: unknown, fallback?: string): string // 优先 RequestError.userMessage，不泄 URL
```

---

## 3. Executable Compatibility Contracts

### 3.1 JS 运行时与 `@dcloudio/vite-plugin-uni` 编译产物红线
1. **严禁动态 `import()`**：UniApp `mp-weixin` CJS 编译器会把 `import('@/stores/auth')` 编译为非法字符串 `"../stores/auth.js".then(...)`，真机运行时当场抛 `TypeError`。跨模块解耦避免循环依赖时，使用 `getActivePinia()` 同步查找（见 `utils/request.ts::getActiveAuthStore`）。
2. **严禁使用 Web-only 全局对象**：微信小程序 JSCore/V8 无 DOM/BOM，禁止使用 `window`、`document`、`localStorage`、`sessionStorage`、`URLSearchParams`、`AbortController`、`structuredClone`、`fetch`、`FormData`、`Blob`。
3. **编译目标与正则兼容**：`vite.config.ts` 固定 `build.target: 'es2018'`（确保产物零残留 `??`、`?.`、`catch {}`）；禁止使用 `\p{...}` Unicode 属性转义正则（如用 `[\u0300-\u036f]` 替代 `\p{M}`）；探测微信宿主对象使用 `typeof wx !== 'undefined'` 而非裸 `globalThis.wx`。

### 3.2 微信平台 API 与跨层 HTTP 契约
1. **HTTP 方法白名单（禁止 `PATCH`）**：`wx.request` 仅支持 `OPTIONS/GET/HEAD/POST/PUT/DELETE/TRACE/CONNECT`，真机发送 `PATCH` 必报 `invalid method`。前后端更新类端点统一用 `PUT`（后端若兼容既有调用可同时挂 `@router.put` + `@router.patch`，见 `backend/app/api/v1/folders.py`）。
2. **隐私合规与媒体 API**：`manifest.json` 必须开启 `__usePrivacyCheck__: true`；严禁调用已停维护的 `uni.chooseImage`（统一改用 `uni.chooseMedia`）；`fail` 回调仅允许静默忽略用户取消（`errMsg.includes('cancel')`），权限/隐私拒绝必须弹可读提示。
3. **Toast 与 Loading 互斥 + 7 汉字截断**：
   - 微信真机上 `hideLoading` 与 `showToast` 共享单槽位，统一通过 `loadingGuard.ts::safeShowToast` 与 `extractUserErrorMessage` 弹窗；
   - 带 `icon: 'success' | 'error' | 'loading'` 超过 7 个汉字会被强截断，`safeShowToast` 自动降级为 `icon: 'none'`；
   - 禁止把含 `[METHOD http://...]` 的 `RequestError.message` 直接塞进 Toast；
   - `uni.setClipboardData` 微信原生自带「内容已复制」提示，成功后不要叠加第二次 Toast；
   - 弹 Toast 后需要跳转页面时留短延迟或先跳转再提示，避免同帧跳转冲掉 Toast。
4. **页面栈深度与单飞防重**：
   - 微信页面栈上限 10 层（测试号 5 层），可能形成闭环的跳转统一调用 `safeNavigateTo`（`>= 9` 层自动降级 `uni.redirectTo`）；
   - 微信 `<button :loading="busy">` **不会阻止 `@tap` 再次触发**，每个 `:loading` 按钮**必须同时绑定 `:disabled`**；
   - `authStore.loginWithWechat` 通过单飞 Promise 防止并发 `uni.login` 抢码失效。

### 3.3 Vue 3 / WXML 原生组件与页面生命周期红线
1. **浮层内原生输入与穿透防护**：
   - 位于 `position: fixed` 弹窗/抽屉内的 `<textarea>` 必须显式绑定 `:fixed="true"`；绑定 `@confirm` 时须配 `confirm-type="send"`；所有 `<input>`/`<textarea>` 应配 `:cursor-spacing="24"`（`textarea` 配 `:show-confirm-bar="false"`）。
   - 页面包含底层 `<input>`/`<textarea>` 且上方可能弹出抽屉/弹窗时（如 `session/index.vue`），浮层打开期间用 `v-if="!overlayOpen"` 隐藏底层原生输入并展示静态草稿预览，防止同层渲染降级机型穿透。
   - 多空受控输入（如填空题）需在组件内本地缓冲，避免每次击键经父级重组字符串通过 `setData` 写回导致光标跳动与输入法断裂。
2. **生命周期时序差异**：微信小程序中页面 **`onShow` 早于 `onMounted` 触发**，且会在异步 `onLoad` `await` 期间触发。凡有异步 `onLoad` 初始化或首屏拉取的页面（如 `questions/index.vue`、`review/index.vue`），必须加 `isInitialLoading` / `hasCompletedInitialLoad` 守卫防止双拉或状态覆盖。
3. **`scroll-into-view` 同 ID 合并**：连续滚动到同一锚点 ID 时，需先清空 `scrollTargetId` 再在 `nextTick` 赋新 ID（或递增锚点序号）。

### 3.4 WXSS 与样式红线
1. **禁用选择器**：WXSS 不支持属性选择器（如 `[disabled]`）、通配符 `*`、`:deep()`/`::v-deep`、本地资源 `url(...)`（仅允许 `https://` 或 `data:`）。禁用态一律用语义类（如 `.is-disabled`）。
2. **自定义 `<button>` 默认边框重置**：微信小程序 `<button>` 自带 `button::after` 灰框与默认 `margin`/`line-height`，所有自定义按钮样式必须写 `&::after { border: none; }` 与 `margin: 0`。
3. **多吸顶元素层级冲突**：同页存在 `BackgroundTaskBar`（`z-index: calc(var(--z-sticky) + 5)`）与其他 `position: sticky; top: 0` 区块时，禁止同级同 `z-index` 互相遮挡。

---

## 4. Validation & Error Matrix

| 场景 | 违背后果 | 自动化拦截 / 兜底 |
|---|---|---|
| 源码出现动态 `import(...)` | 编译成 `"./x.js".then(...)`，真机 `TypeError` | `mpWeixinCompatGuard.spec.ts` 拦截 |
| 请求发 `PATCH` | `wx.request` 真机报 `invalid method` | TS 类型 + `mpWeixinCompatGuard.spec.ts` 拦截 |
| 样式写 `[disabled]` / `*` / `:deep(` | WXSS 静默忽略，禁用态失效 | `mpWeixinCompatGuard.spec.ts` 拦截 |
| `<button :loading>` 缺 `:disabled` | 加载中双击重复提交 | `mpWeixinCompatGuard.spec.ts` 拦截 |
| `networkTimeout > 60000` | 被微信平台静默截断，超时提示失真 | `mpWeixinCompatGuard.spec.ts` 拦截 |
| 闭环页面连续 `navigateTo` >= 10 次 | `webview count limit exceed` 跳转失效 | `safeNavigateTo` >= 9 层自动 `redirectTo` |

---

## 5. Good / Base / Bad Cases

- **Good**：`apiRenameFolder` 调 `PUT /folders/{id}`；浮层 `<textarea :fixed="true" :cursor-spacing="24" confirm-type="send" />`；弹窗打开时底层输入切为静态预览；按钮写 `.is-disabled` + `&::after { border: none; }`。
- **Bad**：`void import('@/stores/auth').then(...)`；`method: 'PATCH' as any`；`uni.chooseImage({ fail: () => {} })`；`.start-btn[disabled]`；`<button :loading="busy">` 不写 `:disabled`。

---

## 6. Tests Required

- `miniprogram/tests/mpWeixinCompatGuard.spec.ts`：静态扫描全部 `miniprogram/src/**`、`manifest.json`、`vite.config.ts`；
- `miniprogram/tests/navigation.spec.ts` & `loadingGuard.spec.ts`：断言 9 层页面栈降级 `redirectTo`、>7 字 Toast 自动降级 `icon: 'none'`、`extractUserErrorMessage` 不含 URL；
- `miniprogram/tests/mpVueWxssCompat.spec.ts`：断言浮层隐藏底层输入、填空本地缓冲、生命周期防抢跑与按钮 `:disabled` 配对；
- `backend/tests/unit/api/test_folder_router.py`：断言 `PUT /api/v1/folders/{folder_id}` 正常重命名。

---

## 7. Wrong vs Correct

#### Wrong
```ts
// 1. mp-weixin 编译断裂
void import('@/stores/auth').then(({ useAuthStore }) => useAuthStore().clearAuth())
// 2. wx.request 真机报 invalid method
request({ url: `/folders/${id}`, method: 'PATCH' as any, data })
// 3. 微信 loading 不阻断点击
// <button :loading="submitting" @tap="submit">提交</button>
```

#### Correct
```ts
// 1. 同步 Pinia 查找，零动态 import()
const auth = getActivePinia()?._s?.get('auth') as { clearAuth?: () => void } | undefined
auth?.clearAuth?.()
// 2. 使用 wx.request 白名单方法
request({ url: `/folders/${id}`, method: 'PUT', data })
// 3. loading 必须配对 disabled
// <button :loading="submitting" :disabled="submitting" @tap="submit">提交</button>
```


---

## Scenario: KaTeX 公式渲染器与自有字体托管（2026-11-24）

- **渲染架构**：由 `katex@0.16.21` + [katexRichText.ts](../../../miniprogram/src/utils/katexRichText.ts)（`katex.__renderToDomTree` → `<rich-text>` `RichTextNode[]`）替代旧手写正则转换器（已退役 `richTextMath.ts`/`latexSymbols.ts`），`<RichContent />` 外部 Props 保持不变且设置 `styleIsolation: 'apply-shared'`。
- **定界符规则**：[richText.ts](../../../miniprogram/src/utils/richText.ts) 数学解析优先级高于 Markdown `_`/`*`，统一支持块级 `$$...$$`、`\[...\]`（含尾部标点 `\]。`）、裸 `\begin{env}...\end{env}`、`` ```latex `` 围栏，以及行内 `$...$`（支持 `\$` 转义、货币防误判与跨软换行合并）与 `\(...\)`。
- **WXSS 与零第三方 CDN 字体**：[katex-mp.scss](../../../miniprogram/src/styles/katex-mp.scss) 全局引入于 `App.vue`，零 `@font-face`、零非法 WXSS 选择器、零裸 Hex；40 个 `.woff2`/`.ttf` 字体文件由 FastAPI `GET /static/fonts/katex/{font_path}` 只读托管（带 `immutable` 缓存与 CORS），前端 [katexFonts.ts](../../../miniprogram/src/utils/katexFonts.ts) 在 `App.vue::onLaunch` 通过 `wx.loadFontFace({ global: true })` 静默加载（非 HTTPS/测试环境静默跳过）。
- **超时与未登录守卫**：`LONG_REQUEST_TIMEOUT_MS` 收敛至 `60000ms`（严格对齐微信硬上限）；`review/index.vue`、`BackgroundTaskBar.vue`、`useMaterialUpload.ts` 发起鉴权请求前必须校验 `useAuthStore().isLoggedIn()`。
