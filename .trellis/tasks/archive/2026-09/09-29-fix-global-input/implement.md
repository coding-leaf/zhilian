# 输入框全局失效：执行计划

> 顺序是**硬约束**：定案（S1–S3）不完成就不进 S4。三条改动的回归面互不相同，
> 未定案就动手等于把三个风险绑成一次提交。

## 审查门禁

- **G1（进 Phase 2 前）**：`design.md` 顶部「结论」表五格全非空，且给出实验编号与判定依据。
- **G2（提交前）**：`task verify-frontend` 退出码 0；若命中 R1，还须 `task verify`（后端不受影响，跑一次确认无连带）。

## 执行清单

### S0 — 建立干净基线

- [ ] S0.1 确认 `pnpm run build:mp-weixin` 退出码 0（本次侦察已跑过一次，产物 `dist/build/mp-weixin`）。
- [ ] S0.2 记录基线证据：`dist/build/mp-weixin/common/vendor.js` 的版本标识（当前仅 `"3.4.21"`）、
      `node_modules/vue/package.json` 版本（当前 `3.5.43`）。
- [ ] S0.3 在开发者工具中导入 `dist/build/mp-weixin`，复现现象并**截取 Console 全文**（含 `[request]` 前缀日志）。
      —— 这份 Console 是后续判定的主要素材，必须在改动前拿到。

### S1 — E1：真机对照（分水岭）

- [ ] S1.1 用同一个包做真机预览（不使用开发者工具模拟器）。
- [ ] S1.2 四处输入点各测一次，记录是否复现。
- [ ] S1.3 判定：
      - 真机正常 → 记入「环境侧」，执行 S1.4 后跳到 S3 的收尾分支。
      - 真机异常 → 转 S2。
- [ ] S1.4 （仅真机正常时）在开发者工具里「清缓存 → 全部清除」后重开，确认是否仍复现；
      把现象、判定依据、规避步骤整理成父任务 Notes 的条目（父任务 XAC-6）。

### S2 — E2/E3/E4/E5：代码侧逐层隔离

按代价从低到高，**命中即停**：

- [ ] S2.1 **E2**：临时注释 `AiCoachDrawer.vue:185` 与 `index/index.vue:798` 的 `backdrop-filter`，
      重编译，测这两处输入点。正常 → 定案 **R3**，跳到 S4。
- [ ] S2.2 **E3**：新增一次性裸页面（无浮层、无 `backdrop-filter`、无网络请求，只放一个 `v-model` 输入框），
      在 `pages.json` 注册后重编译测试。异常 → 定案 **R1**，跳到 S4。
- [ ] S2.3 **E4**：把工作台新建课程弹窗的输入框临时改为 `:value="newFolderName"` + `@input="e => newFolderName = e.detail.value"`，
      重编译测试。正常 → 定案 **R1**（落在代码生成/运行时层），跳到 S4。
- [ ] S2.4 **E5**：输入同时观察 Console 是否出现 401 与登录页跳转、页面是否被重建。
      重建 → 定案 **R2**，跳到 S4。
- [ ] S2.5 四条实验全部落空 → **回 Plan**：假设空间不完整，回到 `design.md` 补假设，
      **不得**在无假设的情况下随机改代码。

### S3 — 一次性诊断产物的清理（不管定案是哪条都要做）

- [ ] S3.1 删除 S2.2 建立的裸页面及其在 `pages.json` 的注册。
- [ ] S3.2 还原 S2.1/S2.3 的临时改动（若定案不是它所对应的 R）。
- [ ] S3.3 `git status` 确认工作区只剩定案 R 的改动（对应父任务 AC-7）。

### S4 — 实现命中的 R

- [ ] S4.1 按 `design.md` 对应分支的「改动设计」实现，**不夹带**其他两条。
- [ ] S4.2 若命中 **R2**：先写纯函数 `shouldRedirectAfterUnauthorized(...)` 的单测（红），
      再实现到绿——判定逻辑必须可在 vitest 下覆盖（条件编译与 `uni.*` 在测试环境不可用）。
- [ ] S4.3 若命中 **R1**：只改 `package.json` 的 vue 版本号（去掉 `^`），
      重装后断言 `node_modules` / `pnpm-lock.yaml` / 打包产物三处一致。

### S5 — 复验（改完必须重跑一遍全部实验）

- [ ] S5.1 重编译，**真机 + 开发者工具各测一次**四处输入点（父任务 XAC-3）。
- [ ] S5.2 关键回归项：打开弹窗 → 输入 → 等后端列表请求返回 → 内容仍在。
      （专门针对 H3：页面被重建会清空输入，所以必须在请求周期内测。）
- [ ] S5.3 若命中 R2：另测「无 token 时仍正确跳登录页」，确认登录兜底没被修坏。
- [ ] S5.4 若命中 R3：浮层改动前后的截图对照，确认视觉可接受。

### S6 — 门禁与收尾

- [ ] S6.1 `task verify-frontend`（eslint / vue-tsc / vitest）；命中 R1 时补跑 `task verify-backend`。
- [ ] S6.2 把定案结论与实验观测回填 `design.md` 的「结论」表与 PRD 的 AC 勾选。
- [ ] S6.3 若结论为环境侧：不提交代码改动，直接登记父任务 Notes 后关闭本任务。

## 回滚点

| 步骤 | 回滚方式 |
| --- | --- |
| S2.1 / S2.2 / S2.3 的临时改动 | `git checkout -- <file>`；裸页面为新增文件，直接删 |
| S4.3 的版本锁定 | `git checkout -- package.json pnpm-lock.yaml && pnpm install` |
| S4.2 的 401 收敛 | 单文件 `src/utils/request.ts`，`git checkout` 即回滚 |

## 验证命令

```bash
# 前端门禁
cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit

# 或走 task runner
task verify-frontend

# 重编译（每次改完 .vue / 依赖后都要跑，产物才会同步）
cd miniprogram && pnpm run build:mp-weixin

# 版本一致性断言
node -e "console.log(require('./miniprogram/node_modules/vue/package.json').version)"
grep -oE '\"3\.(4|5)\.[0-9]+\"' miniprogram/dist/build/mp-weixin/common/vendor.js | sort -u
```
