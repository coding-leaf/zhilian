/**
 * 网络层失败的统一契约。
 *
 * 单独成模块（而非并入 `request.ts`）的原因：
 * - `@/stores/*` 需要按 `kind` 分类失败原因，而 `.trellis/spec/frontend/state-management.md`
 *   明令 store 不得 import `request.ts` 去绕开 `@/api`；
 * - `request.ts` 通过动态 import 反向引用 auth store 以避免环依赖，把这个契约
 *   下沉成叶子模块，两侧都能安全引用。
 */

/** 传输层失败类别。 */
export type RequestErrorKind = 'timeout' | 'network' | 'http' | 'unauthorized'

/**
 * 默认请求超时（毫秒）。
 *
 * 取代原先吃 `wx.request` 默认值的做法：那条路径下失败要在 60 秒后才暴露，
 * 期间界面只有一个转圈的按钮，且没有任何原因提示。
 */
export const DEFAULT_REQUEST_TIMEOUT_MS = 15000

/**
 * 同步调用大模型的接口所用超时（毫秒）。
 *
 * 出题质检、主观题重判与助教答疑都在请求路径内等大模型返回，15 秒不够用。
 * 事实源：`backend/app/services/question.py`（`run_structured_agent_workflow`）与
 * `backend/app/services/grading.py::regrade_attempt`（docstring 标注「大模型重判调用失败」）。
 */
export const LONG_REQUEST_TIMEOUT_MS = 90000

/** 小程序平台在拿不到 errno 时回填的占位串，不该混进日志。 */
const ERRNO_PLACEHOLDER = '<Undefined>'

export interface RequestErrorDetails {
  statusCode?: number
  /** `uni.request` fail 回调的原始 errMsg。 */
  errMsg?: string
  /** `uni.request` fail 回调的原始 errno。 */
  errno?: number | string
  /** 后端返回的 detail / message。 */
  detail?: string
}

/**
 * 网络层失败错误。
 *
 * 同时承载三种受众需要的信息：`userMessage` 给 toast（短、可行动），
 * `describe()` 给 console（含 url / errMsg / statusCode），结构化字段给调用方分类。
 */
export class RequestError extends Error {
  readonly kind: RequestErrorKind
  readonly url: string
  readonly method: string
  /** 可直接展示的短文案。小程序 toast 会被截断，故这里不放 URL。 */
  readonly userMessage: string
  readonly statusCode?: number
  readonly errMsg?: string
  readonly errno?: number | string
  readonly detail?: string

  constructor(
    kind: RequestErrorKind,
    url: string,
    method: string,
    userMessage: string,
    details: RequestErrorDetails = {},
  ) {
    const summary = userMessage || '请求失败'
    super(`${summary} [${method} ${url}]`)
    this.name = 'RequestError'
    this.kind = kind
    this.url = url
    this.method = method
    this.userMessage = summary
    this.statusCode = details.statusCode
    this.errMsg = details.errMsg
    this.errno = details.errno
    this.detail = details.detail
  }

  /** 面向开发者的一行摘要，用于 console.error。 */
  describe(): string {
    const parts = [`kind=${this.kind}`, `${this.method} ${this.url}`]
    if (this.statusCode !== undefined) parts.push(`status=${this.statusCode}`)
    if (this.errMsg) parts.push(`errMsg=${this.errMsg}`)
    if (this.errno !== undefined && String(this.errno) !== ERRNO_PLACEHOLDER) {
      parts.push(`errno=${this.errno}`)
    }
    if (this.detail) parts.push(`detail=${this.detail}`)
    return parts.join(' ')
  }
}

/**
 * 把 `uni.request` / `uni.uploadFile` 的 fail 回调归一为失败类别与用户文案。
 *
 * 纯函数，必须保持可独立调用：登录失败分类依赖它，而登录失败路径在 vitest 里不可达
 * （`#ifdef` 条件编译在测试环境下不生效，见 `tests/loginFailure.spec.ts` 顶部说明）。
 *
 * Args:
 *   errMsg: fail 回调的原始 errMsg。
 *   timeoutMs: 本次请求实际使用的超时，用于把等待时长写进文案。
 *
 * Returns:
 *   失败类别与可直接展示的文案。
 */
export function classifyTransportFailure(
  errMsg?: string,
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS,
): { kind: RequestErrorKind; userMessage: string } {
  if (typeof errMsg === 'string' && errMsg.includes('timeout')) {
    return {
      kind: 'timeout',
      userMessage: `请求超时（${Math.round(timeoutMs / 1000)}秒），请检查后端是否可达`,
    }
  }
  return { kind: 'network', userMessage: '网络连接失败，请检查网络后重试' }
}
