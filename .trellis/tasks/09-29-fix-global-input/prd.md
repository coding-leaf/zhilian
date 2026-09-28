# 输入框全局失效：定位与修复

## Goal

消除「所有文本输入框输入即消失」这一全局阻断现象，并让输入在这些页面上**在被修复前后都可判定**——
即先做实验把根因钉死在具体一条上，再改代码；不允许靠猜改一处试试看。

## 现象（2026-09-29 用户实测）

在微信开发者工具中，**凡是需要输入文字的地方都无法输入**，键入的字符随即消失：

| 输入点 | 文件 | 承载容器 | 绑定方式 |
| --- | --- | --- | --- |
| 工作台「+ 新建课程」弹窗 | `src/pages/index/index.vue:164` | `.modal-overlay` | `v-model="newFolderName"` |
| 工作台 AI 助教抽屉 | `src/components/AiCoachDrawer.vue:63` | `.coach-drawer-overlay` | `v-model="inputQuery"` |
| 资料页 AI 助教（同一组件） | `src/subpackages/material/pages/course/index.vue:144` | 同上 | 同上 |
| 个人中心昵称弹窗 | `src/pages/profile/index.vue:72` | `.modal-overlay` | `v-model="editNickname"` |
| 判题/自评弹窗 | `src/subpackages/report/components/GradingActionModal.vue:15,27,34` | 待核实 | `v-model="reason" / "scoreInput"` |

用户同时报告「无法创立新课程」——这与输入框失效是同一现象（名称进不去，创建自然失败），
**不另立需求**。用户保留判断：「不排除是微信开发者助手的问题」，因此本任务必须把
「环境问题」与「代码缺陷」分开定案。

## 已确认事实（本次侦察证据）

1. **编译期与运行时版本错配（已坐实，非推测）**
   - `package.json:17` 写 `"vue": "^3.4.21"`，`pnpm-lock.yaml` 实际解析到 **`vue@3.5.43`**，
     `miniprogram/node_modules/vue/package.json` 实装 `3.5.43`。
   - 小程序打包产物 `dist/build/mp-weixin/common/vendor.js` 中 **只有 `3.4.21`、零个 `3.5.43`**：
     运行时来自 `@dcloudio/uni-mp-vue@3.0.0-4020920240930001`（其依赖 `@vue/shared@3.4.21`）。
   - 即：**SFC 由 `@vue/compiler-sfc@3.5.43` 编译，跑在 3.4.21 的运行时上**。
     uni-app 该 alpha 版本发布于 2024-09-30，官方对 Vue 3.5 的支持在其后。
2. **`backdrop-filter` 与输入点 100% 重合**：全项目 5 处 `backdrop-filter`，4 处是浮层遮罩，
   而项目里**每一个输入框都恰好位于这些浮层内**（`AiCoachDrawer.vue:185`、`index/index.vue:798`、
   `profile/index.vue:351`、`course/index.vue:562,594`）。项目内不存在「不在浮层里的输入框」可用作对照。
3. **全局 401 处理会销毁页面**：`src/utils/request.ts:9-20` 的 `handleUnauthorized()` 在**任何** 401 上
   执行 `uni.reLaunch('/pages/auth/login')`。`reLaunch` 关闭全部页面再开新页——页面被销毁时，
   输入框里的内容必然清零。若后台有轮询在跑，该动作可反复触发。
   （旁证：`course/index.vue` 的解析轮询与 `materialStore.pollMaterialStatus` 会以 1.5s 间隔连发 20 次请求。）

**尚未确认**：三条中哪一条是本次实测的真凶。三者都足以单独造成「输入即消失」。

## 判定实验（先做这个，再动代码）

按**代价从低到高**排列，每条都给出「结果 → 结论」的判定规则。实验 1 是分水岭。

| # | 实验 | 观测 | 判定 |
| --- | --- | --- | --- |
| E1 | 真机预览（同一个包，不打开发者工具） | 输入是否正常 | 正常 → **环境侧**，转 E1b；异常 → **代码侧**，转 E2 |
| E1b | 开发者工具「清缓存 → 全部清除」后重开，并检查 Console 是否有 `[request]` 报错 / 是否出现登录页 | 是否复现 | 复现 → 环境侧需给出规避步骤；不复现 → 记录为工具态问题 |
| E2 | 临时移除两处浮层的 `backdrop-filter`（`AiCoachDrawer.vue:185`、`index/index.vue:798`）后重编译 | 输入是否正常 | 正常 → 锁定 `backdrop-filter`，按 R3 修；异常 → 转 E3 |
| E3 | 新建一个**裸页面**（无浮层、无 `backdrop-filter`、无网络请求），只放一个 `v-model` 输入框 | 输入是否正常 | 异常 → **全局层**，按 R1 修；正常 → 输入框本身没问题，转 E4 |
| E4 | 临时把输入框改成 `:value` + `@input` 手动赋值（避开 `v-model` 代码生成） | 输入是否正常 | 正常 → 锁定代码生成（R1）；异常 → 转 E5 |
| E5 | 在输入同时观察 Console 是否出现 401/`reLaunch`，以及页面是否被重建 | 页面是否重建 | 重建 → 锁定 R2 |

E3 的裸页面是**一次性诊断产物**，定案后删除，不留在仓库里。

## Change Boundary

### In scope

按实验结论**只做命中的那一条**，不做「三条一起上」的防御性改动：

- **R1（命中编译/运行时错配）**：把 `vue` 锁到与 `@dcloudio/uni-mp-vue` 一致的 `3.4.21`（去掉 `^`），
  重新安装并重编译。**只锁版本，不升级 uni-app**——升级是另一类决策（见 Out of scope）。
- **R2（命中全局 401）**：收敛 `handleUnauthorized()`——仅在「确实无 token 且已确认鉴权失败」时跳登录页；
  有 token 的 401 走静默重登一次，失败再跳。**不得**在后台轮询的失败路径上销毁用户正在操作的页面。
- **R3（命中 `backdrop-filter`）**：移除输入框所在浮层的 `backdrop-filter`，改用不透明的 `rgba` 底色
  达到同等视觉分层。按 `docs/DESIGN.md` 的纸质阅读风，视觉差异需肉眼可接受。

### Out of scope（明确不做）

- **不升级 uni-app 到新版**（如 `3.0.0-40xxx` 后续版本）。锁版本能在本任务内闭环；
  升级会牵动 `vite`、`@dcloudio/*` 全家桶与全部 9 个测试文件，必须单独立项。
- **不重写输入框为自定义组件**。在根因未定案前做封装，等于把结论埋进代码里。
- **不改 `pages/index/index.vue` 的静默自动登录**（`onMounted` 里 `loginWithWechat()` 忽略返回值）。
  该行为已被 `09-29-login-request-hardening` 明确列为待决项，本任务不顺手改。

## Requirements

### R0 — 先定案，再修

- 执行上表实验，把结论写进本任务 `design.md` 的「结论」一节，**包含判定依据（命令/截图/Console 输出）**。
- 只实现命中的那一条 R。若实验显示多条同时成立，逐条登记并全部实现，但**每条都要有自己的判定证据**。

### R1/R2/R3 — 见上「In scope」，各自的可验证标准见 Acceptance Criteria。

### R4 — 回归覆盖

- 四处输入点（工作台新建课程、AI 助教抽屉、资料页助教、个人中心昵称）逐个验证，
  验收标准见父任务 XAC-3。
- 若命中的是 R2，必须同时验证「无 token 时仍会正确跳登录页」——修 401 不能把登录兜底修坏。

## Acceptance Criteria

**实际路径与计划不同**：原计划的判定实验 E1–E5 **未执行**。
按 systematic-debugging 的顺序，先做的是「把现象翻译成可观测事实」——
用户补充的关键观测「点击输入框直接关闭页面了」把问题从「文字消失」改写为「浮层被关闭」，
再直接检查编译产物即定案（见 `design.md`「定案证据」）。E1（真机对照）反而因为用户的
AppID 处于游客态（微信拒绝真机预览：`游客id不允许真机`）而不可执行，但它已不必要：
这是代码缺陷，全平台一致。

- [x] AC-1 根因定案为**唯一一条**，且给出可复现的静态证据。
      证据：`currentTarget` 在整个 `dist/build/mp-weixin` 中 **0 次出现**；
      `'self'`/`withModifiers` 在页面产物与 `vendor.js` 中均 0 次；
      编译器源码只映射 `capture`/`stop`/`prevent`，无 `self` 分支。见 `design.md`。
- [x] AC-2 给出「改之前 / 改之后」的对照证据（**在编译产物层**，这是本次定案的同一手段，
      比真机截图更可复核）：
      | | 容器 | backdrop |
      | --- | --- | --- |
      | 改前 | `<view class="modal-overlay data-v-d18a8845" bindtap="{{I}}">` | 不存在 |
      | 改后 | `<view wx:if="{{y}}" class="modal-overlay data-v-ec2aacb9">`（**无 bindtap**） | `<view class="modal-backdrop data-v-ec2aacb9" bindtap="{{z}}"/>` |
      6 个浮层逐一核对通过（AiCoachDrawer / 工作台弹窗 / 个人中心弹窗 / GradingActionModal /
      讲义考点弹窗 / 答题卡抽屉）。
- [x] AC-3 相应 CSS 进入产物：`.X-backdrop{position:absolute;...;z-index:0}` 与
      `.X-sheet|.modal-content|.point-sheet{position:relative;z-index:1}`（均已 grep 确认）。
- [ ] AC-4 **四处输入点实机/开发者工具复测待用户执行**（工作台新建课程、AI 助教抽屉、
      资料页助教、个人中心昵称）。**代码侧已无可再验的部分**——本仓库无组件挂载测试基建，
      产物层证据已到顶。
- [x] AC-5 全项目 `@tap.self` 归零（grep 命中仅剩 6 行解释性注释，无属性残留）。
- [x] AC-6 `task verify-frontend` 全绿：eslint 无输出、`vue-tsc --noEmit` 无输出、
      vitest **9 文件 69 用例全过**；`pnpm run build:mp-weixin` 退出码 0。
- [x] AC-7 无一次性诊断产物残留：原计划 E3 的裸页面**未创建**（走的是产物静态定案路径）。
- [x] AC-8 结论**不是环境侧**，故无需登记父任务 Notes；但用户「怀疑是开发者助手」的直觉
      已被证伪，这一条本身值得留档——留档在 `design.md` 的「教训留档」段。

## 顺带登记（**不在本任务实现**）

| 项 | 位置 | 为何不属本任务 |
| --- | --- | --- |
| 全局 401 `uni.reLaunch` 销毁当前页 | `src/utils/request.ts:9-20` | 不解释本现象（点击输入框不发请求），但是真实隐患：后台轮询期间一次 401 会丢弃用户正在填的表单 |
| 编译期 3.5.43 / 运行时 3.4.21 错配 | `package.json` / `pnpm-lock.yaml` | 已核实产物无 `v-model` 代码生成问题，与本现象无关；升级需单独立项 |

两项均需在父任务收口时决定是否立项。


## Notes

- 本任务的价值一半在**定案**：这套环境已留档过一次「非本仓库故障」（开发者工具网络层不发字节），
  若这次又是环境问题，必须留下可复用的判定路径，否则下次实测会当成新 bug 重查一遍。
- 侦察期间发现 `dist/build/mp-weixin` 的产物与 `src` **不同步**（编译产物里 `placeholder` 是静态字面量，
  而当前源码是动态绑定 `:placeholder`）。因此**所有从旧产物得出的结论都要用一次干净构建复核**；
  本任务开头已触发一次 `pnpm run build:mp-weixin`。
