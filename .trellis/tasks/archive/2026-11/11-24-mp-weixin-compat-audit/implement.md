# Implementation Plan: 微信小程序 / UniApp 兼容性修复与规范沉淀

> **推荐 Phase 2 执行编排**：**原生 `Swarm` 2 路无冲突并行开发（独立 `share` 工作区）+ 合并后补静态门禁测试、沉淀 `.trellis/spec/` 与全量双端门禁验证**，沿用用户指定的模型分工：
> - **Track M1**（后端 `PATCH→PUT` 别名 + 前端网络/构建/`manifest`/API/隐私/Toast/导航工具/Auth 单飞）→ `gemini-4-neon-high`
> - **Track M2**（前端 Vue/WXML 原生输入/浮层穿透、WXSS `[disabled]`/`button::after`/双 `sticky`、生命周期竞态、`<button :loading :disabled>`）→ `gemini-4-hydrogen-high`
> - 合并后在主工作区补齐 `mpWeixinCompatGuard.spec.ts` + 沉淀 `.trellis/spec/frontend/mp-weixin-compatibility.md` + 跑全量 `task verify-backend`、`task verify-frontend` 与 `pnpm run build:mp-weixin` 产物实测。

---

## 1. 无冲突文件边界（File Ownership）

### Track M1 (`impl-mp-api-runtime`, `gemini-4-neon-high`, `workspace: "share"`)
- `backend/app/api/v1/folders.py` + `backend/tests/unit/api/` 相关测试（新增 `@router.put("/{folder_id}")` 别名）
- `miniprogram/vite.config.ts`
- `miniprogram/src/manifest.json`
- `miniprogram/src/utils/request.ts`（含工作区已热修的 `getActivePinia()` 改动，同步保留并移除 `'PATCH'`）
- `miniprogram/src/utils/requestError.ts`（`UPLOAD_REQUEST_TIMEOUT_MS = 60_000`）
- `miniprogram/src/utils/loadingGuard.ts`（升级 `safeShowToast` + 新增 `extractUserErrorMessage`）
- NEW `miniprogram/src/utils/navigation.ts`（`safeNavigateTo`）
- `miniprogram/src/utils/richTextMath.ts`（`\p{M}` → `[\u0300-\u036f]`）
- `miniprogram/src/api/modules/folders.ts`（`PATCH` → `PUT`）
- `miniprogram/src/stores/auth.ts`（`loginWithWechat` 单飞锁）
- `miniprogram/src/composables/useMaterialUpload.ts`（`chooseMedia`、`typeof wx !== 'undefined'`、非 cancel 错误可见提示、跳转防闪灭）
- `miniprogram/src/pages/profile/index.vue`（`chooseMedia` + `extractUserErrorMessage`/`safeShowToast`）
- 相关单测：`miniprogram/tests/{requestResilience,requestFailure,loadingGuard,loginFailure,materialAndFolderStore,richText}.spec.ts` + 新增 `navigation.spec.ts`

### Track M2 (`impl-mp-vue-wxss`, `gemini-4-hydrogen-high`, `workspace: "share"`)
- `miniprogram/src/components/AiCoachDrawer.vue`（`:fixed="true"`、`confirm-type="send"`、`:cursor-spacing="24"`）
- `miniprogram/src/components/CoachMessageList.vue`（去剪贴板重复 Toast、修 `scroll-into-view` 同 ID 合并）
- `miniprogram/src/components/BackgroundTaskBar.vue`（使用 `safeNavigateTo` / 吸顶 z-index 协调）
- `miniprogram/src/components/FolderFormModal.vue`、`ProfileEditModal.vue`（`:cursor-spacing="24"`、`:disabled` 配对）
- `miniprogram/src/subpackages/report/components/GradingActionModal.vue`（`:fixed="true"`、`:cursor-spacing="24"`、`:disabled`）
- `miniprogram/src/subpackages/report/composables/useReportDetail.ts`、`report.scss`（`safeShowToast`、`extractUserErrorMessage`、`.reinforce-bar-btn::after`）
- `miniprogram/src/subpackages/practice/pages/session/index.vue`、`components/PracticeQuestionBody.vue`、`session.scss`（浮层打开隐藏底层输入、`:cursor-spacing="24"`、填空本地缓冲防光标跳动、`.draft-retry-btn::after`）
- `miniprogram/src/subpackages/material/pages/questions/index.vue`、`questions.scss`、`components/QuestionPreviewPanel.vue`、`components/MaterialCourseHeader.vue`、`pages/course/index.vue`（`onLoad`/`onShow` 守卫、`.start-btn.is-disabled`、`::after`、Toast 截断与 `safeNavigateTo`）
- `miniprogram/src/pages/index/components/MaterialItemCard.vue`、`pages/index/index.vue`（`.manual-parse-btn::after`、`safeNavigateTo`）
- `miniprogram/src/pages/review/index.vue`、`review.scss`、`composables/useReviewCenter.ts`、`components/QuestionBankSection.vue`（双 `sticky` 修复、冷启 `onShow`/`onMounted` 去重、`safeNavigateTo`/`safeShowToast`）
- `miniprogram/src/pages/auth/login.vue`（`<button :loading :disabled>`）
- `miniprogram/src/styles/common.scss`（按钮通用 `::after { border: none; }` 基线）
- 相关组件/流程单测

> **M1 ↔ M2 约定接口**（精确签名，零歧义）：
> - `safeNavigateTo(url: string): void` from `@/utils/navigation`
> - `safeShowToast(titleOrOptions: string | { title: string; icon?: 'success' | 'error' | 'loading' | 'none'; duration?: number; mask?: boolean }): void` from `@/utils/loadingGuard`
> - `extractUserErrorMessage(err: unknown, fallback?: string): string` from `@/utils/loadingGuard`

---

## 2. 合并与验证门禁

1. 将 M1、M2 合入主工作区并清理 `share` 工作区。
2. 新增 `miniprogram/tests/mpWeixinCompatGuard.spec.ts` 自动化静态门禁测试。
3. 编写 `.trellis/spec/frontend/mp-weixin-compatibility.md` 并更新 `.trellis/spec/frontend/{index,network-contract,component-guidelines}.md`。
4. 在宿主 Windows PowerShell 运行全量门禁与构建实测：
   ```powershell
   task verify-backend
   task verify-frontend
   cd miniprogram && pnpm run build:mp-weixin
   ```
5. 检查 `dist/build/mp-weixin` 实测产物确认 0 处非法动态 `import()` / `PATCH` / `[disabled]` / `\p{M}` 且 `app.json` 正确；确认后按需部署 `aliyun`（后端新增 `PUT /folders/{id}`）并推送 GitHub。
