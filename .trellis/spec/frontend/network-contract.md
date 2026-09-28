# Network Contract（小程序网络层契约）

> **事实源**：`miniprogram/src/utils/request.ts`、`miniprogram/src/utils/requestError.ts`、`miniprogram/src/api/index.ts`、`miniprogram/src/stores/auth.ts`、`miniprogram/tests/requestFailure.spec.ts`、`miniprogram/tests/loginFailure.spec.ts`
> **最后核对**：2026-09-29
> **核对方式**：逐条对照源码 + 实跑 `pnpm run lint` / `type-check` / `test:unit`（9 文件 / 62 用例全绿）+ 核对 `dist/dev/mp-weixin` 编译产物

---

## 1. Scope / Trigger

凡涉及以下任一项，必须先读本文件再动手：

- 新增/修改任何 `src/api/index.ts` 里的 HTTP 调用（超时选择、错误语义）
- 修改 `src/utils/request.ts` / `requestError.ts`
- 新增依赖网络层失败分类的 store 或页面（尤其登录链路）
- 后端新增同步调用大模型（LLM）的接口

**背景（2026-09-29 实测）**：登录页点击后按钮转圈 60 秒，最终只弹「网络连接异常，请重试」，
Console 唯一线索是 `request:fail timeout`。事后证实根因在本地微信开发者工具的网络层
（请求字节从未到达后端：TCP 已 ESTABLISHED，但后端无访问日志、库中无新建用户），
**但代码把一次失败放大成了 60 秒无信息空白期**，这才是本契约要消除的东西。

---

## 2. Signatures

```typescript
// src/utils/requestError.ts
export type RequestErrorKind = 'timeout' | 'network' | 'http' | 'unauthorized'
export const DEFAULT_REQUEST_TIMEOUT_MS = 15000
export const LONG_REQUEST_TIMEOUT_MS = 90000

export class RequestError extends Error {
  readonly kind: RequestErrorKind
  readonly url: string
  readonly method: string
  readonly userMessage: string      // 短，给 toast
  readonly statusCode?: number
  readonly errMsg?: string
  readonly errno?: number | string
  readonly detail?: string
  describe(): string                // 含 url/errMsg/statusCode，给 console
}

export function classifyTransportFailure(
  errMsg?: string,
  timeoutMs?: number,               // 默认 DEFAULT_REQUEST_TIMEOUT_MS
): { kind: RequestErrorKind; userMessage: string }

// src/utils/request.ts
export interface RequestOptions {
  url: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS'
  data?: any
  header?: Record<string, string>
  timeout?: number                  // 覆盖默认；LLM 接口传 LONG_REQUEST_TIMEOUT_MS
}
export function request<T = any>(options: RequestOptions): Promise<T>   // 失败 reject(RequestError)
export function uploadFile<T = any>(filePath, name?, formData?, endpoint?): Promise<T>

// src/stores/auth.ts
export type LoginFailureReason = 'wechat' | 'timeout' | 'network' | 'http'
export type LoginOutcome = { ok: true } | { ok: false; reason: LoginFailureReason; message: string }
export function classifyLoginFailure(err: unknown): { reason: LoginFailureReason; message: string }
// loginWithWechat(): Promise<LoginOutcome>
```

---

## 3. Contracts

### 超时分两档

| 档位 | 值 | 适用 |
| --- | --- | --- |
| `DEFAULT_REQUEST_TIMEOUT_MS` | `15000` | 认证、CRUD、列表、详情、交卷、异步派发类接口 |
| `LONG_REQUEST_TIMEOUT_MS` | `90000` | **请求路径内同步调 LLM** 的接口 |

**带长超时的接口是白名单，只有 4 个**（改 `api/index.ts` 时请维持这个清单）：

| API 函数 | 端点 | 判定依据（后端事实源） |
| --- | --- | --- |
| `apiGenerateQuestions` | `POST /questions/generate` | `services/question.py` 走 `run_structured_agent_workflow` + 质检重试 |
| `apiAskQuestionCoach` | `POST /questions/{id}/ask-coach` | 助教答疑同步等大模型 |
| `apiAskScopedCoach` | `POST /coach/ask` | 范围级助教同步等大模型 |
| `apiRegradeAttempt` | `POST /grading/regrade` | `services/grading.py::regrade_attempt` docstring 标注「大模型重判调用失败」 |

**明确不需要长超时的**（勿凭感觉加）：

- `POST /grading/self-evaluate` —— 用户自评覆盖，无 LLM 错误类型
- `POST /materials/{id}/parse` —— 队列派发（`failed_stage="queue_dispatch"`），不是同步解析
- `POST /practices/{id}/submit`、`POST /practices/{id}/regrade` —— 派发判题任务（`action="retry_grading_dispatched"`）
- `POST|GET /practices/{id}/diagnosis` —— `services/diagnosis.py` 不 import LLM，是掌握度聚合

### toast 与 console 分工

| 受众 | 载体 | 内容 |
| --- | --- | --- |
| 终端用户 | `uni.showToast` | 仅 `userMessage`：短、可行动。**不放 URL**（小程序 toast 会截断） |
| 开发者 | `console.error` | `[request] ${error.describe()}`：`kind` + method + url + status + errMsg + errno + detail |

**设计决策：为什么 URL 只进 console 不进 toast。** 排查时真正的观测点在 Console（本次故障的唯一线索就来自
`auth.js` 的 console 输出）。把 URL 塞进 toast 既看不全，又会污染终端用户界面。两者分工而非二选一。

### `errno` 占位串

> **Warning**：小程序平台拿不到 errno 时回填字面量字符串 `"<Undefined>"`（注意是字符串，不是 `undefined`）。
> `describe()` 会过滤它。**不要**把它当成有效值写进判断条件。

---

## 4. Validation & Error Matrix

| 触发条件 | `kind` | `success`/`fail` | toast 文案 | 附加字段 |
| --- | --- | --- | --- | --- |
| `errMsg` 含 `timeout` | `timeout` | `fail` | `请求超时（N秒），请检查后端是否可达` | `errMsg`、`errno` |
| `fail` 其它情况 | `network` | `fail` | `网络连接失败，请检查网络后重试` | `errMsg`、`errno` |
| HTTP 401 | `unauthorized` | `success` | 不重复弹（`handleUnauthorized` 负责） | `statusCode=401` |
| HTTP 其它非 2xx | `http` | `success` | 后端 `detail` / `message` / `请求失败 (status)` | `statusCode`、`detail` |
| 2xx（`{code,message,data}`） | — | `success` | — | 解构出 `data` |
| 2xx（裸对象） | — | `success` | — | 原样返回 |

登录结果映射（`classifyLoginFailure`）：

| 输入 | `reason` | `message` |
| --- | --- | --- |
| `RequestError('timeout')` | `timeout` | `err.userMessage` |
| `RequestError('network')` | `network` | `err.userMessage` |
| `RequestError('http')` | `http` | `err.userMessage`（通常是后端 detail） |
| `RequestError('unauthorized')` | `http` | `err.userMessage` |
| `wx.login` 失败 / `res.code` 缺失 | `wechat` | `微信登录失败，请重试` / `未取得微信登录凭证，请重试` |
| 其它任何抛出（含非 Error） | `network` | `登录失败，请重试`（**保证非空**） |

---

## 5. Good/Base/Bad Cases

- **Good**：后端不可达 → 15 秒内弹「请求超时（15秒），请检查后端是否可达」，Console 有
  `[request] kind=timeout POST http://localhost:8000/api/v1/auth/login errMsg=request:fail timeout`。
  用户知道该去看后端，开发者知道是哪个请求。
- **Base**：出题接口因大模型慢，第 40 秒才返回 → 因为挂了 90 秒长超时，不被误杀。
- **Bad**：默认 15 秒一刀切 → 出题/重判在正常慢响应下被误杀，用户看到「请求超时」但后端其实成功了。
  **这是本契约最容易被改坏的地方。**

---

## 6. Tests Required

`tests/requestFailure.spec.ts`（12 例）与 `tests/loginFailure.spec.ts`（9 例）。新增网络行为时必须补的断言点：

| 断言点 | 位置 |
| --- | --- |
| 默认请求把 `DEFAULT_REQUEST_TIMEOUT_MS` 传给 `uni.request` | `requestFailure` |
| 单次调用可覆盖 `timeout` | `requestFailure` |
| 4 个 LLM 端点拿到 `LONG_REQUEST_TIMEOUT_MS`，非 LLM 端点拿到默认值 | `requestFailure` |
| `request:fail timeout` → `kind='timeout'`，且 `describe()` 含 url 与 errMsg | `requestFailure` |
| 超时 toast 含「超时」与秒数 | `requestFailure` |
| 普通传输失败 → `kind='network'`，toast 不含「超时」 | `requestFailure` |
| HTTP 4xx → `kind='http'` + `statusCode` + `detail` | `requestFailure` |
| 401 → `kind='unauthorized'` 且 `access_token` 被清 | `requestFailure` |
| `errno="<Undefined>"` 不出现在 `describe()` | `requestFailure` |
| `uploadFile` 失败走同一套契约 | `requestFailure` |
| 6 条 `classifyLoginFailure` 映射 | `loginFailure` |
| `loginWithWechat` 返回 `{ ok: true }` 而非裸 boolean | `loginFailure` |
| `fetchProfile` 失败不抛、不清 token，但留下含 url 与 kind 的 console 记录 | `loginFailure` |

> **Warning：`loginWithWechat` 的失败路径在单测里不可达。**
> `stores/auth.ts` 用 `#ifdef MP-WEIXIN` 条件编译，而 `vitest.config.ts` **不加载 uni 插件**
> （只挂 `@vitejs/plugin-vue`）—— 条件编译注释在测试里只是普通注释，两条分支都会执行。
> `#ifndef` 分支同步 `resolve`，永远先于 `uni.login` 的异步回调完成，因此测试环境**恒定走 mock 分支**
> （且 `tests/setup.ts` 的 `uniMock` 没有 `login` 方法，不补 mock 会直接 TypeError）。
> 结论：**失败分类逻辑必须留在可独立调用的纯函数里**，不要去测 `loginWithWechat` 的失败分支。

---

## 7. Wrong vs Correct

#### Wrong —— 让平台默认超时兜底，失败时只报「网络异常」

```typescript
// src/utils/request.ts（旧写法）
uni.request({
  url: fullUrl, method, data, header,
  // 没有 timeout：吃 wx.request 默认 60s
  fail: (err) => {
    uni.showToast({ title: '网络连接异常，请重试', icon: 'none' })  // 无 URL、无 errMsg、无 errno
    reject(err)                                                   // 抛裸 err，调用方无法分类
  },
})
```

后果：60 秒空白期；toast 无法区分超时/网络/后端拒绝；调用方只能拿到 `false`。

#### Correct —— 显式超时 + 带类别的结构化错误，toast 与 console 分工

```typescript
// src/utils/request.ts（现写法）
const timeout = options.timeout ?? DEFAULT_REQUEST_TIMEOUT_MS
uni.request({
  url: fullUrl, method, data, header, timeout,
  fail: (err) => {
    const { kind, userMessage } = classifyTransportFailure(err?.errMsg, timeout)
    const error = new RequestError(kind, fullUrl, method, userMessage, {
      errMsg: err?.errMsg, errno: err?.errno,
    })
    console.error(`[request] ${error.describe()}`)   // 开发者看清一切
    uni.showToast({ title: userMessage, icon: 'none' })  // 用户看到可行动的短结论
    reject(error)
  },
})
```

#### Wrong —— 把失败原因折叠成布尔值

```typescript
const loginWithWechat = async (): Promise<boolean> => {
  ...
  } catch (err) {
    console.error('Login error:', err)
    resolve(false)        // 调用方拿到 false，无法区分三类原因
  }
}
```

#### Correct —— 返回判别式结果，原因与文案一起透传

```typescript
export type LoginOutcome = { ok: true } | { ok: false; reason: LoginFailureReason; message: string }

} catch (err) {
  const failure = classifyLoginFailure(err)
  console.error(`Login error (${failure.reason}):`, err)
  resolve({ ok: false, ...failure })
}
```

---

## 已知偏离

- **`localhost` 仍是默认主机名**（`http://localhost:8000/api/v1`）。2026-09-29 的故障环境里
  `xray_tun` 在回环广播地址 `127.255.255.255/32` 上装了路由（v2rayN TUN 模式），
  换成字面量 `127.0.0.1` 可消掉域名解析这一环；但这属于独立决策，尚未采纳。
- **`uploadFile` 没有逐请求超时**：`uni.uploadFile` 无 `timeout` 参数（平台限制），
  超时只能靠 `app.json` 的 `networkTimeout`。其失败分支已统一到 `RequestError` 契约。
- **`pages/index/index.vue::onMounted` 的静默自动登录未改**：它 `await authStore.loginWithWechat()`
  后忽略返回值。改返回类型后行为不变（仍编译通过）。**故意不改**：在启动路径加失败 toast 会让
  每个未登录用户「打开即报错」，是 UX 回归。若将来要处理，应在页面内以非打扰方式（如横幅）呈现。
