# 输入框全局失效：技术设计

## 结论（**已定案**）

| 项 | 值 |
| --- | --- |
| 定案根因 | **H4（新增，见下）——`@tap.self` 在小程序产物中被编译器丢弃** |
| 判定实验编号 | 无（原 E1–E5 未执行；由**编译产物静态证据**直接定案，见下） |
| 判定依据 | 见「定案证据」一节：`currentTarget` 在**整个小程序包中 0 次出现** |
| 真机结论 | 未做（用户的 AppID 处于游客态，真机预览被微信拒绝：`游客id不允许真机`）。**定案不依赖真机**——这是代码缺陷，全平台一致 |
| 开发者工具结论 | 用户实测「点击输入框或者输入框相关内容，直接关闭页面了」 |

**原 H1/H2/H3 全部降级为「已排除」**，理由见「为什么原假设全不成立」。

## 定案证据

`@tap.self="closeX"` 的语义是「仅当点击落在元素自身（非子元素）时触发」。
在 Web 端由 Vue 的 `withModifiers(fn, ['self'])` 实现；**在小程序端，该修饰符被静默丢弃**：

| 证据 | 观测 |
| --- | --- |
| 编译后的遮罩 | `<view wx:if="{{y}}" class="modal-overlay data-v-d18a8845" bindtap="{{I}}">` ——**裸 `bindtap`，无任何附加判定** |
| `'self'` / `"self"` 字面量 | `pages/index/index.js`、`components/AiCoachDrawer.js`、`common/vendor.js` 中均为 **0 次** |
| `withModifiers` | `common/vendor.js` 中 **0 次** |
| **`currentTarget`** | **整个 `dist/build/mp-weixin` 包中 0 次**——任何 self 判定都必然要用 `target`/`currentTarget` 比较，它的完全缺席即为「运行时不存在 self 检查」的充分证据 |
| 编译器对修饰符的处理 | `@dcloudio/uni-mp-compiler` 只显式映射 `capture` → `capture-bind`、`stop`/`prevent` → `catch`；**没有 `self` 的分支** |

**后果**：`@tap.self="closeFolderModal"` 的实际行为等同 `@tap="closeFolderModal"`——
**点击浮层内的任何位置（包括输入框）都会关闭浮层。**

**与用户报告完全吻合**：

- 用户原话「点击输入框或者输入框相关内容，直接关闭页面了」——浮层被关掉，而非页面崩溃。
- 先前描述的「想输入文字，结果会自动消失」是同一事件的另一种说法：手刚点上输入框，浮层连同里面的内容一起消失。
- 全项目 **6 处 `@tap.self`**，其中 **4 处含输入框**，而**全项目所有输入框无一例外都在这些浮层内**——这解释了为什么现象是「所有输入框都不能用」而不是某一处。

## 为什么原假设全不成立

| 原假设 | 为何排除 |
| --- | --- |
| **H1 编译期 3.5.43 / 运行时 3.4.21 错配** | 错配确实存在（干净产物仅含 `"3.4.21"`），但**不足以定罪**：干净产物里 `<input>` 编译为 `value="{{C}}" bindinput="{{D}}"`，`v-model` 代码生成正常；且组件 `v-model:visible` 工作正常（浮层能打开）。它是一条**真实存在的独立隐患**，但不是本现象的成因 |
| **H2 浮层 `backdrop-filter`** | 相关性是假象：真正与输入框 100% 重合的是 `@tap.self`（6 处浮层里 4 处有输入框），`backdrop-filter` 只是恰好被这些浮层共用 |
| **H3 全局 401 `reLaunch` 销毁页面** | 页面销毁需要一次 401；而**点击输入框本身不发起任何请求**（四处输入点的 input 均无 focus/click 请求）。H3 仍是真实隐患（见下「顺带修」），但不是本现象成因 |

**教训留档**：三条原假设都建立在「静态相关性 + 合理机制」上，而真正定案靠的是
**直接检查编译产物**。这个项目里 `.vue` 到小程序的编译会**静默丢弃**一部分 Vue 修饰符语义，
凡「修饰符行为与 Web 端不一致」的现象，第一步就该去产物里查它有没有被编译进去。

## 修复设计

### 为什么不复用 `.self`

不能改用别的修饰符替代：`stop`/`prevent` 虽被编译器支持（映射为 `catch`），
但**依赖事件传播路径**——若点击原生 `input` 时事件目标直接落在遮罩容器上（原生组件层的
点击穿透到 WebView 层），内容元素上的 `catchtap` 根本不在传播路径上，挡不住。

### 选中方案：把「点击关闭」的目标拆成独立的背景元素

```html
<view v-if="showX" class="x-overlay">
  <view class="x-backdrop" @tap="closeX" />   <!-- 只负责关闭，覆盖全屏，位于内容之下 -->
  <view class="x-sheet">...内容...</view>      <!-- 不绑定任何 tap -->
</view>
```

```css
.x-overlay { position: fixed; /* 原有 flex 布局保持不变 */ }
.x-backdrop { position: absolute; top: 0; bottom: 0; left: 0; right: 0; z-index: 0; }
.x-sheet { position: relative; z-index: 1; }   /* 显式压过 backdrop */
```

**为什么这个方案对两种事件机制都成立**：

- 若点击目标落在内容元素上：内容**根本没绑 tap**，无事发生 → 输入框可用。
- 若原生组件的点击穿透到 WebView 层：命中的是内容元素（它就在该点正下方且 DOM 靠后），
  同样不绑 tap → 无事发生。
- 点击浮层外的空白：命中的是 `backdrop` → 关闭，**保留「点外部关闭」这一交互**。

**代价**：每个浮层多一个元素 + 两条 CSS 规则。`z-index` 必须显式写——backdrop 是绝对定位，
内容是不定位的流内元素，不显式提升会画在 backdrop 之下。

### 实施范围：6 处全覆盖

| 文件 | 浮层 | 含输入框 | 处理 |
| --- | --- | --- | --- |
| `components/AiCoachDrawer.vue:2` | 助教抽屉 | ✓ | 本次修 |
| `pages/index/index.vue:157` | 新建课程弹窗 | ✓ | 本次修 |
| `pages/profile/index.vue:63` | 昵称弹窗 | ✓ | 本次修 |
| `subpackages/report/components/GradingActionModal.vue:2` | 判题/自评弹窗 | ✓ | 本次修 |
| `subpackages/material/pages/course/index.vue:97` | 考点详情弹窗 | ✗ | 本次修（同一缺陷，点内容即关闭同样错） |
| `subpackages/practice/pages/session/index.vue:91` | 答题卡抽屉 | ✗ | 本次修（同上） |

后两处不含输入框，因此**不是阻断项**，但缺陷机理与修法完全相同，一并处理避免留下两处同类坏味道。

## 顺带修（**不属本任务，登记不实现**）

- **H3 的全局 401 `reLaunch`**（`src/utils/request.ts:9-20`）：任何 401 都会销毁当前页面并跳到登录页。
  它不解释本现象，但**是真的**——后台轮询期间一旦 401，用户正在填的表单会被整页丢弃。
  登记为本批次的候选缺陷，需单独评估（收敛为「有 token 时静默重登一次，无 token 才跳转」）。
- **H1 的版本错配**（`vue@3.5.43` 编译 / `3.4.21` 运行时）：同样是真实隐患，与本次现象无关，
  保留为独立待决项。

## 验证方式

本仓库无组件挂载测试基建（`vitest.config.ts` 不加载 uni 插件，页面依赖 `@dcloudio/uni-app` 的 `onLoad`），
因此验证落在**编译产物**上，这是本次定案所用的同一手段：

- 6 个浮层容器在编译产物中**不得再出现 `bindtap`**；
- 每个浮层必须出现 `-backdrop` 元素且它带 `bindtap`；
- 用户实机/开发者工具复测四处输入点。


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
