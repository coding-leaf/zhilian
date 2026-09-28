# 输入框全局失效：技术设计

## 结论（**由判定实验填充，动手改代码前必须非空**）

| 项 | 值 |
| --- | --- |
| 定案根因 | _待填：R1 / R2 / R3 / 环境侧_ |
| 判定实验编号 | _待填：E1…E5_ |
| 判定依据 | _待填：命令输出 / Console 片段 / 真机截图说明_ |
| 真机结论 | _待填_ |
| 开发者工具结论 | _待填_ |

> 本表为空时**不得**进入 Phase 2。缺了它，本任务就退化成「三处都改一遍试试看」，
> 而每一处改动都有独立的回归面（R1 动依赖树、R2 动鉴权跳转、R3 动视觉）。

## 假设空间与各自的机制

三条假设不是并列的「可能性」，它们的**机制完全不同**，因此判定实验能干净地区分它们。

### H1｜编译期 3.5.43 / 运行时 3.4.21 错配

- **已坐实的事实**：`node_modules/vue@3.5.43`（编译器）＋ `dist/build/mp-weixin/common/vendor.js`
  仅含 `"3.4.21"`（运行时，来自 `@dcloudio/uni-mp-vue@3.0.0-4020920240930001` → `@vue/shared@3.4.21`）。
- **已排除的部分**：干净产物里 `<input>` 编译为 `placeholder="{{B}}" value="{{C}}" bindinput="{{D}}"`
  —— `v-model` 在原生组件上的代码生成**是正常的**，不存在「v-model 被编译没了」这种情况。
- **因此 H1 若要成立，机制只能是**：3.5 编译器产出的**脚本层**（`<script setup>` 编译结果、
  渲染函数、`withDirectives`/`vModelText` 之类的运行时辅助）引用了 3.4 运行时不存在或行为不同的符号，
  导致 `bindinput` 回调写入的 state 没能正确回流到 `value` 绑定，或回流时用陈旧快照覆盖。
- **判定**：E3（裸页面）异常 + E4（`:value`/`@input` 手写绑定）异常 → 落在 H1。

### H2｜浮层 `backdrop-filter` 的合成层问题

- **相关性证据**：项目内 5 处 `backdrop-filter`，其中 4 处是浮层遮罩；而**项目里不存在任何
  位于浮层之外的输入框**，四处输入点全部落在 `backdrop-filter: blur()` 的容器内。
  用户在四处**独立页面**上报同一现象，浮层是它们唯一的共同结构。
- **机制**：小程序原生 `input` 是独立于 WebView 的原生组件层。带 `backdrop-filter` 的容器会创建
  独立的合成/层叠上下文，在开发者工具的模拟层下，原生组件层的重建会让输入内容回退到绑定的旧值。
- **为什么用户会怀疑是工具**：这个机制天然「工具里明显、真机上未必复现」，与用户的直觉一致。
- **判定**：E1（真机正常、工具异常）＋ E2（移除 `backdrop-filter` 后正常）→ 落在 H2。

### H3｜全局 401 处理销毁页面

- **证据**：`src/utils/request.ts:9-20` 的 `handleUnauthorized()` 在**任何** 401 上执行
  `uni.reLaunch('/pages/auth/login')`。`reLaunch` 关闭全部页面——页面销毁，输入内容必然清零。
- **放大因素**：`materialStore.pollMaterialStatus`（`stores/material.ts:63`）以 1.5s 间隔连发 20 次请求；
  任一次返回 401 就会触发跳转。若 token 失效但 `uni.getStorageSync('access_token')` 仍非空，
  `authStore.isLoggedIn()` 为真，工作台不会重新登录（`pages/index/index.vue:226`），于是**持续 401**。
- **判定**：E5 观测到页面重建 / Console 出现 401 与登录页跳转 → 落在 H3。

### 为什么不用「三条一起改」收尾

每条的影响面是**不同**的：R1 动依赖树（`task verify-frontend` 全量回归）、R2 动鉴权跳转
（修坏会把登录兜底弄丢）、R3 动视觉（`docs/DESIGN.md` 有约束）。
在没有判定证据的情况下一起改，等于把三个回归面绑成一次提交，出问题时无法二分定位。

## 各分支的改动设计

### R1｜锁定 vue 版本

- `package.json`：`"vue": "^3.4.21"` → `"vue": "3.4.21"`（去掉 caret）。**只改这一处**。
- `pnpm install` 重装 → 断言 `node_modules/vue/package.json` 为 `3.4.21`。
- 重编译 → 断言 `dist/build/mp-weixin/common/vendor.js` 的版本标识与 `node_modules` 一致。
- **风险**：`@vue/compiler-sfc@3.4.21` 对当前 SFC 语法的支持——项目用了 `<script setup lang="ts">`、
  泛型 `defineProps<{...}>()`、`v-model:visible`，均为 3.4 已有能力，预期无阻力。
- **回滚点**：`package.json` + `pnpm-lock.yaml` 两文件。

### R2｜收敛全局 401

改动集中在 `src/utils/request.ts` 的 `handleUnauthorized()`，目标是把「销毁当前页面」
降级为「先尝试静默恢复，确实无救再跳转」：

- **有 token 的 401**：清 token → 调一次 `loginWithWechat()` 重取 →
  - 成功：**不跳转**，仅记录日志；本次请求仍以 401 拒绝（不自动重放，避免请求重放风险与无限递归）。
  - 失败：走跳转分支。
- **无 token 的 401**：直接走跳转分支（保持现有行为，这是登录兜底，不能弄丢）。
- **必须新增一个「本次会话已尝试过重登」的抑制位**，否则后台轮询会以每 1.5s 一次的速度连打登录接口。
- **依赖方向**：`utils/request.ts` 已经用动态 `import('@/stores/auth')` 规避了循环依赖，
  沿用该口径（`state-management.md` 禁止 store 反向 import `request.ts`，但此处是 request → store，方向合法）。
- **可测性**：判定逻辑须抽成纯函数（如 `shouldRedirectAfterUnauthorized(hasToken, alreadyRetried)`），
  按 `09-29-login-request-hardening` 已确立的先例——条件编译与 `uni.*` 在 vitest 下不可用，逻辑必须下移到纯函数。
- **风险**：把「登录过期」的提示体验改弱。约束：**无 token 时必须仍然跳转**，AC-5 覆盖。

### R3｜移除浮层 `backdrop-filter`

- 移除 `AiCoachDrawer.vue:185`、`index/index.vue:798`、`profile/index.vue:351`、
  `course/index.vue:562,594` 的 `backdrop-filter`。
- 遮罩底色由 `rgba(0, 0, 0, 0.45)` / `rgba(0, 0, 0, 0.4)` 适当加深补偿模糊的视觉分层。
- **取舍**：视觉上会少一层毛玻璃质感，换来输入可用。按 `docs/DESIGN.md` 的纸质阅读风，
  遮罩本就只是压暗背景，`backdrop-filter` 属锦上添花，可接受。

## 兼容性与不做的事

- 三处改动**互不依赖**，若实验显示多条成立，可分三次独立提交，各自可回滚。
- **不做**输入框封装组件：根因未定案前封装会把结论埋进代码，且四处输入点的 props 需求差异大。
