# PRD: 微信小程序 / UniApp 语法与 API 兼容性专项修复与规范沉淀

> **任务目录**：`.trellis/tasks/11-24-mp-weixin-compat-audit`
> **优先级**：P1
> **范围模式**：完整 mp-weixin 规范沉淀（含自动化静态门禁测试）+ 全部 P0 与核心 P1 真机兼容缺陷修复（P2 如 46 处 Sass `@import` 留作后续清理）

---

## 1. 目标与用户价值

对照微信官方小程序文档、UniApp Vue 3（`mp-weixin`）规范与真实编译产物 `miniprogram/dist/dev/mp-weixin/**`，消除会在微信真机（iOS/Android）崩溃、静默失效或交互错乱的语法/API/样式缺陷，并将全部微信小程序红线沉淀为可执行规范（`.trellis/spec/frontend/mp-weixin-compatibility.md`）与自动化静态回归门禁（`miniprogram/tests/mpWeixinCompatGuard.spec.ts`）。

---

## 2. 需求清单与实证缺陷映射

### R1：P0 真机必崩 / 不可用缺陷修复

| ID | 级别 | 精确代码与产物锚点 | 修复目标 |
|---|---|---|---|
| **R1.1** | P0 | `miniprogram/src/utils/request.ts` 动态 `import('@/stores/auth')` 编译为 `"../stores/auth.js".then(...)`（已在工作区热修） | 保持 `getActivePinia()` 同步查找零动态 `import()`，补充真机兼容回归测试并纳入静态门禁。 |
| **R1.2** | P0 | `miniprogram/src/api/modules/folders.ts:26` + `request.ts:233,271` 发送 `PATCH`，`wx.request` 官方不支持 `PATCH` 必报 `invalid method`；后端 `backend/app/api/v1/folders.py:202` 仅注册 `@router.patch` | 后端 `folders.py` 为重命名端点增加 `@router.put("/{folder_id}")` 别名（保留 `@router.patch` 向后兼容）；前端 `folders.ts` 改用 `PUT`，`request.ts` 类型彻底移除 `'PATCH'` 与 `as any` 绕过。 |
| **R1.3** | P0 | `miniprogram/src/manifest.json` 缺 `__usePrivacyCheck__`；`useMaterialUpload.ts:68` & `pages/profile/index.vue:110` 调停维护的 `uni.chooseImage`；`useMaterialUpload.ts:78,97` `fail: () => {}` 静默吞错 | `manifest.json` 补齐 `__usePrivacyCheck__: true`；两处图片选择迁移至 `uni.chooseMedia`（保留异常兜底）；`useMaterialUpload.ts` 仅忽略用户主动取消（`errMsg` 含 `cancel`），对权限/隐私拦截给出清晰可读提示。 |

### R2：P1 构建目标、`manifest.json`、JS 运行时与平台 API 兼容

| ID | 级别 | 精确代码与产物锚点 | 修复目标 |
|---|---|---|---|
| **R2.1** | P1 | `manifest.json:19-22` `networkTimeout` 设 `90000`/`120000` 超出微信 60000ms 上限；缺 `enhance: true` 与 `lazyCodeLoading: "requiredComponents"`；`vite.config.ts` 未设 `build.target` 导致产物残留 `??`/`catch {}`；`richTextMath.ts:134` 用 `\p{M}` 正则；`useMaterialUpload.ts:107` 未判空 `globalThis.wx` | `manifest.json` 收敛 `networkTimeout` 为 `{ request: 60000, uploadFile: 60000 }`、补齐 `enhance: true` 与 `lazyCodeLoading: "requiredComponents"`；`vite.config.ts` 配置兼容旧基础库的 `build.target`（如 `es2019`）；`richTextMath.ts` 将 `\p{M}` 替换为标准组合音标范围 `[\u0300-\u036f]`；`useMaterialUpload.ts` 改用 `typeof wx !== 'undefined'` 安全探测。 |
| **R2.2** | P1 | 24 处裸 `uni.showToast` 绕过 `loadingGuard.ts::safeShowToast`；带图标 Toast 超 7 汉字截断（`useMaterialUpload.ts:55-58`、`questions/index.vue:117,213`、`useReportDetail.ts:142`）；13 处 `catch` 把含完整 URL 的 `RequestError.message` 塞进 Toast；Toast 后同步跳转闪灭（`request.ts:177-181`、`useMaterialUpload.ts:55-59`）；`CoachMessageList.vue:108-110` 剪贴板二次弹窗 | 扩展 `loadingGuard.ts` 提供统一 `safeShowToast`（超 7 字自动降级 `icon: 'none'`、兼容 loading 互斥）与 `extractUserErrorMessage(err, fallback)`（优先读 `RequestError.userMessage`，禁止把 URL 塞进 Toast）；高风险站点统一替换；Toast 后跳转加短延迟或交由目标页处理；移除 `CoachMessageList.vue` 剪贴板重复 Toast。 |
| **R2.3** | P1 | 21 处 `uni.navigateTo` 零页面栈守卫（闭环压栈会撞穿 10 层/5 层上限）；`stores/auth.ts:131` `loginWithWechat` 无单飞锁；`pages/auth/login.vue:6` 等多处 `<button :loading>` 未同时绑 `:disabled` | 新增 `miniprogram/src/utils/navigation.ts::safeNavigateTo`（`getCurrentPages().length >= 9` 自动降级 `uni.redirectTo`）并接入核心闭环跳转；`stores/auth.ts::loginWithWechat` 加单飞复用锁；全仓 `<button :loading="...">` 补齐对应 `:disabled`。 |

### R3：P1 Vue/WXML 原生组件、生命周期与 WXSS 样式兼容

| ID | 级别 | 精确代码与产物锚点 | 修复目标 |
|---|---|---|---|
| **R3.1** | P1 | `AiCoachDrawer.vue:40-51`、`GradingActionModal.vue:23,42` 在 `position: fixed` 内 `<textarea>` 缺 `:fixed="true"`；`AiCoachDrawer` `@confirm` 缺 `confirm-type="send"`；`session/index.vue:25-54` 开浮层未隐藏底层 `<input>`/`<textarea>`；全仓输入缺 `cursor-spacing`；`PracticeQuestionBody.vue:92-124` 填空题每次击键经 `setData` 改写受控值 | 浮层内 `<textarea>` 补齐 `:fixed="true"` 与 `cursor-spacing`；`AiCoachDrawer` 补 `confirm-type="send"`；`session/index.vue` 任一浮层/抽屉打开时隐藏底层原生输入（防同层降级穿透）；模态框 `<input>`/`<textarea>` 补 `cursor-spacing`；填空题输入本地缓冲避免每击键重排覆盖输入法光标。 |
| **R3.2** | P1 | `subpackages/material/questions.scss:139` `.start-btn[disabled]` 属性选择器被 WXSS 忽略；全仓 65 处 `<button>` 缺 `::after { border: none; }` 及部分按钮缺 UA 重置；`pages/review/index.vue:43` 双 `sticky; top: 0; z-index: 20` 遮挡 `BackgroundTaskBar` | `.start-btn[disabled]` 改为 `.start-btn.is-disabled` 类绑定；统一清理自定义按钮 `::after { border: none; }` 与 `margin: 0` / `line-height`；修复 `pages/review/index.vue` 吸顶层级/偏移使 `BackgroundTaskBar` 不被 `.segment-bar` 遮挡。 |
| **R3.3** | P1 | `questions/index.vue:126-155` `onShow` 在 `onLoad` 异步期间抢跑覆盖 `viewMode`；`pages/review/index.vue:113,157-163` 冷启 `onShow` 早于 `onMounted` 造成重复拉取 | `questions/index.vue` 增加初始化守卫防止 `onShow` 在 `onLoad` 完成前覆盖 `viewMode`；`pages/review/index.vue` 合并冷启动加载，消除 `onShow`/`onMounted` 双拉。 |

### R4：可执行规范沉淀与自动化静态检查门禁

- 新建 `.trellis/spec/frontend/mp-weixin-compatibility.md`（覆盖 JS/编译产物、Vue/WXML、WXSS、微信平台 API 契约与 Wrong vs Correct 对照）并更新 `.trellis/spec/frontend/{index,network-contract,component-guidelines}.md`。
- 新增 `miniprogram/tests/mpWeixinCompatGuard.spec.ts` 自动化静态扫描测试（随 `pnpm run test:unit` / `task verify-frontend` 自动执行），拦截：动态 `import(`、HTTP `PATCH`、`uni.chooseImage`、`[disabled]`/`*`/`:deep(`/`url(` 非法 WXSS、Web-only 全局对象、`<button :loading` 缺 `:disabled`、`networkTimeout > 60000`、`\p{` 正则。

---

## 3. 验收标准

1. `backend`：`PUT /api/v1/folders/{folder_id}` 与 `PATCH /api/v1/folders/{folder_id}` 均通过单测，`task verify-backend` 全绿。
2. `miniprogram`：
   - `task verify-frontend` 全绿（含新增 `mpWeixinCompatGuard.spec.ts` 及所有兼容修复单测）；
   - `pnpm run build:mp-weixin` 产出的 `dist/build/mp-weixin` 实测：**0 处 `.js".then(`、0 处 `method: "PATCH"`、0 处 `[disabled]` WXSS、0 处 `\p{M}`、`app.json` 含 `__usePrivacyCheck__: true` 与 `networkTimeout <= 60000`、`es2019` 降级无裸 `??` 语法报错**；
   - 全部触碰 `.vue` 文件维持 `<= 300` 行、零裸 Hex、零 Emoji。
3. `.trellis/spec/frontend/mp-weixin-compatibility.md` 落盘并挂入 `.trellis/spec/frontend/index.md`。

---

## 4. 不在范围（P2 留作后续清理）

- 46 处 Sass `@import` 迁 `@use` 及 `pages/review/components/` 重复 `.wxss` 拆包瘦身
- 2 个历史未使用 SFC 清理（`QuestionPreviewCard.vue`、`QuestionPreviewPanel.vue`）
- `manifest.json` 正式 AppID 替换（目前开发阶段保留占位或由开发者按需填写）
