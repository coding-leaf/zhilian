# 登录请求链路加固：超时收敛、失败可诊断、原因透传

## Goal

把小程序网络层"60 秒静默卡死 + 一句无信息量 toast"的失败形态，改成"快速失败 + 可定位原因"。

起因（2026-09-29 实测）：点击登录后按钮转圈 60 秒，最终仅弹出「网络连接异常，请重试」。
开发者工具 Console 里能看到的唯一线索是 `auth.js:30 Login error: {errMsg: "request:fail timeout", errno: "<Undefined>"}`，
无法判断是网络不通、后端拒绝、还是 `wx.login` 失败。事后排查证实该次失败是本地开发者工具网络层问题
（请求字节从未到达后端），但**即使根因在环境，代码也不该把一次失败呈现成 60 秒空白期**。

## Change Boundary

### In scope

| 文件 | 改动 | 必要性 |
| --- | --- | --- |
| `src/utils/request.ts` | 显式 `timeout`；失败时抛出携带 `kind/url/method/statusCode/errMsg/errno/detail` 的结构化错误；toast 改为具体原因 | 需求 1、2 |
| `src/utils/requestError.ts`（新增） | `RequestError` 类与 `RequestErrorKind`；传输层失败的纯函数分类 | 需求 2、3 的共享契约，且避免 `stores/*` 依赖 `utils/request`（`state-management.md` 明令 store 不得 import `request.ts`） |
| `src/api/index.ts` | 给同步 LLM 接口显式标注长超时 | 需求 1 的必然代价：默认 15s 会打断出题/重判 |
| `src/stores/auth.ts` | `loginWithWechat` 返回判别式结果而非裸 boolean；`fetchProfile` 不再 `catch {}` 静默吞错 | 需求 3；后者违反 `quality-guidelines.md`「静默吞错」禁令 |
| `src/pages/auth/login.vue` | 按失败原因给出可见提示；成功后的 `uni.switchTab` 补 `fail` 兜底 | 需求 3；缺 `fail` 已被规范列为已知例外 |

### Out of scope（明确不做）

- **不改 `API_BASE_URL` 的 `localhost` 默认值**。前端规范把它记录为既定默认（`http://localhost:8000/api/v1`），
  改成 `127.0.0.1` 属于另一类决策（见 Notes），需单独授权。
- **不改 `pages/index/index.vue` 的静默自动登录行为**。它 `await authStore.loginWithWechat()` 后忽略返回值；
  改返回类型后它仍能编译、行为不变。若在此处加失败 toast，会给每个未登录用户**打开即弹错**，是 UX 回归而非修复。
  单独记为待决项。
- **不加 `manifest.json` 的 `networkTimeout`**。逐请求 `timeout` 已覆盖；改构建配置扩大风险面且收益重复。
- **不给 `uploadFile` 加超时**：`wx.uploadFile` 无 `timeout` 参数（平台限制）。但其失败分支的错误信息**要**一并结构化。

## Requirements

### R1 — 超时收敛

- 传输层默认超时 **15000ms**，取代当前吃 `wx.request` 默认的 60s。
- `RequestOptions` 提供 `timeout?: number` 覆盖位。
- 同步 LLM 接口必须显式标注长超时（**90000ms**）：`/questions/generate`、`/questions/{id}/ask-coach`、
  `/coach/ask`、`/grading/regrade`。
- 依据：后端 `app/services/question.py`（`run_structured_agent_workflow`）、`grading.py`
  （`regrade_attempt` docstring 标注「大模型重判调用失败」）确认为请求路径内同步调用 LLM；
  `/grading/self-evaluate`、`/materials/{id}/parse`、`/practices/{id}/submit` 与 `/regrade` 分别经
  无 LLM 错误类型与队列派发确认不在慢路径，保持默认 15s。

### R2 — 失败可诊断

- 失败时抛出的错误必须携带：`kind`、`url`、`method`、`statusCode?`、`errMsg?`、`errno?`、`detail?`。
- **toast 给短且可行动的结论**（如「请求超时（15秒），后端未响应」）；**完整技术细节进 `console.error`**。
  理由：小程序 toast 会被截断，把 URL 塞进 toast 既看不全又污染终端用户界面；而本次排查的真实观测点在 Console。
- `kind` 判定：`errMsg` 含 `timeout` → `timeout`；`fail` 其它情况 → `network`；HTTP 非 2xx → `http`；401 → `unauthorized`。
- HTTP 错误的 `detail` 取后端 `detail`/`message` 字段（沿用现有取值口径）。

### R3 — 失败原因透传

- `loginWithWechat` 由 `Promise<boolean>` 改为返回判别式联合
  `{ ok: true } | { ok: false; reason: LoginFailureReason; message: string }`，
  `LoginFailureReason = 'wechat' | 'timeout' | 'network' | 'http'`，覆盖用户点名的三类原因（网络不通／后端拒绝／`wx.login` 失败）。
- 登录页按 `reason` 呈现原因，不再是"成功有 toast、失败什么都不说"。
- `fetchProfile` 的 `catch {}` 改为记录失败（含结构化细节），消除规范明令禁止的静默吞错。

## Acceptance Criteria

全部以 `task verify`（退出码 0：后端 ruff/mypy/lint-imports/pytest 1378 passed；前端 eslint/vue-tsc/vitest 9 文件 62 用例）
与 `dist/dev/mp-weixin` 编译产物核对。

- [x] AC-1 传输层默认超时 15000ms，且请求确实把它传给 `uni.request`（以 mock 捕获的 `options.timeout` 为准）。
      证据：`tests/requestFailure.spec.ts`「passes the converged default timeout…」。
      `vue-tsc` 通过同时证明 `timeout` 是 `uni.request` 的合法字段。
- [x] AC-2 `/questions/generate`、`/coach/ask`、`/questions/{id}/ask-coach`、`/grading/regrade` 四类请求的
      `timeout` 为 90000ms；其余接口为 15000ms。证据：单测断言四个函数 + 编译产物中 `LONG_REQUEST_TIMEOUT_MS`
      恰好 4 处，且 `apiGetKnowledgePointSnippets` 确认**未**携带（排除滑动窗口假阳性）。
- [x] AC-3 `errMsg: 'request:fail timeout'` 归一为 `kind='timeout'`，toast 文案含「超时」与秒数，`console.error` 输出含 url 与 errMsg。
- [x] AC-4 非超时的传输失败归一为 `kind='network'`，并与 `timeout` 文案可区分。
- [x] AC-5 HTTP 4xx/5xx 归一为 `kind='http'`，携带 `statusCode` 与后端 `detail`；401 仍走既有 `handleUnauthorized`
      （断言 `access_token` 被清且不重复 toast）。
- [x] AC-6 `loginWithWechat` 在 `wx.login` 失败（含 `res.code` 缺失）时返回 `reason='wechat'`。
      **覆盖度说明：已实现，但无单测覆盖。** `#ifdef MP-WEIXIN` 条件编译在 vitest 下不生效
      （`vitest.config.ts` 不加载 uni 插件），`#ifndef` 分支同步 `resolve` 会抢在 `uni.login` 异步回调之前完成，
      登录失败路径在单测里不可达。因此只把分类逻辑抽成纯函数测了 6 条映射，`wechat` 两条分支需在真机/开发者工具验证。
- [x] AC-7 `loginWithWechat` 在登录请求超时/网络失败/后端拒绝时分别返回 `timeout`/`network`/`http`，且 `message` 非空
      （含非 Error 抛出也保证非空）。
- [x] AC-8 登录页在失败时按 `reason` 弹出可见提示；成功后跳转带 `fail` 兜底。
      证据：编译产物 `dist/dev/mp-weixin/pages/auth/login.js` 含 `outcome.ok` 分支与 `switchTab` 的 `fail`。
- [x] AC-9 `fetchProfile` 失败不再静默：不 rethrow、不清 token，但记录含 url 与 kind 的结构化错误。
- [x] AC-10 三条门禁全绿，且既有用例零回归（新增 21 例，41 → 62；原件数比规范记录多 2 例，为本次之前既存漂移）。

**未纳入验收但须留档的风险**：本次故障的**根因不在本仓库代码**（微信开发者工具网络层未把请求字节发出：
TCP 两端 ESTABLISHED 静默 140+ 秒，但后端无访问日志、库中无新建用户）。本任务只消除其「不可诊断」的放大效应，
环境侧的 `xray_tun` 回环广播路由问题仍未解决，实测时仍可能复现失败——届时 Console 会直接给出 `kind` 与 url。

## Notes

- **登录失败分类逻辑必须可单测**：`stores/auth.ts` 使用 `#ifdef MP-WEIXIN` 条件编译，而 vitest 不处理条件编译，
  两条分支都会执行，`#ifndef` 分支同步 `resolve` 会先于 `uni.login` 回调完成 —— 即测试环境**永远走 mock 分支**。
  因此 `loginWithWechat` 内部无法在单测里触达失败路径，分类逻辑须抽成纯函数后直接测试（符合
  `quality-guidelines.md`「优先把逻辑下移到纯函数再测」）。
- **`localhost` vs `127.0.0.1` 待决**：本次故障环境里 `xray_tun` 在回环广播地址 `127.255.255.255/32` 上装了路由。
  把默认值换成字面量 `127.0.0.1` 可消掉域名解析这一环，但会偏离前端规范记录的值，需单独决策。
- 本次根因（开发者工具网络层未把请求字节发出）**不属于本仓库代码缺陷**，本任务只消除其"不可诊断"的放大效应。
