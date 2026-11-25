/**
 * 原生阻断型 Loading 引用计数卫士。
 *
 * 微信小程序的 `wx.showLoading` 与 `wx.showToast` 共用同一个原生弹窗槽位：
 * 1. 并发或嵌套调用若直接成对调用 `showLoading`/`hideLoading`，先结束者会提前关闭浮层，
 *    后结束者再调 `hideLoading` 触发「showLoading 与 hideLoading 必须配对使用」告警；
 * 2. 请求失败时若先弹 `showToast` 再进 `finally { hideLoading() }`，不仅触发不配对告警，
 *    还会把刚弹出的错误 Toast 瞬间关掉。
 *
 * 本模块通过引用计数保证 1:1 严格配对，并在 `finally` 内优先关闭 Loading 后再抛错或弹 Toast。
 */

import { RequestError } from './requestError'

let activeLoadingCount = 0
let isNativeLoadingVisible = false

export type SafeToastIcon = 'none' | 'success' | 'error' | 'loading'

export interface SafeToastOptions {
  title: string
  icon?: SafeToastIcon
  duration?: number
  mask?: boolean
}

const WECHAT_ICON_TOAST_MAX_CHARS = 7

/**
 * 提取面向终端用户的安全错误提示文案：
 * - 优先读取 `RequestError.userMessage`，绝不把 `[METHOD http://...]` 等内部调试 URL 泄露到 Toast；
 * - 对普通 Error / 字符串也会剥离潜在的 URL 片段；
 * - 为空时回落至 `fallback`。
 */
export function extractUserErrorMessage(
  err: unknown,
  fallback: string = '操作失败，请重试',
): string {
  if (err instanceof RequestError) {
    return err.userMessage || fallback
  }

  let raw = ''
  if (err && typeof err === 'object') {
    const maybeUserMessage = (err as { userMessage?: unknown }).userMessage
    if (typeof maybeUserMessage === 'string' && maybeUserMessage.trim()) {
      return maybeUserMessage.trim()
    }
    const maybeMessage = (err as { message?: unknown }).message
    if (typeof maybeMessage === 'string') {
      raw = maybeMessage
    }
  } else if (typeof err === 'string') {
    raw = err
  }

  const sanitized = raw
    .replace(/\s*\[[A-Z]+\s+https?:\/\/[^\]]+\]\s*$/i, '')
    .replace(/https?:\/\/\S+/gi, '')
    .trim()

  return sanitized || fallback
}

export function isBlockingLoadingActive(): boolean {
  return isNativeLoadingVisible
}

/**
 * 若当前存在通过本卫士展示的原生 Loading，先将其安全关闭（保证 1:1 配对状态一致）。
 * 可在 `showToast` 前调用，避免微信单槽位抢占导致误关 Toast 或配对告警。
 */
export function dismissBlockingLoading(): void {
  if (!isNativeLoadingVisible) return
  isNativeLoadingVisible = false
  uni.hideLoading()
}

/**
 * 安全弹出 Toast：
 * 1. 若 Loading 仍在展示中，先关闭 Loading 再弹 Toast，防止单槽位相互顶掉；
 * 2. 微信小程序带图标（`success`/`error`/`loading`）Toast 最多显示 7 个汉字，
 *    超过 7 字时自动降级为 `icon: 'none'`（支持 2 行完整展示）以防真机强截断。
 */
export function safeShowToast(
  titleOrOptions: string | SafeToastOptions,
  icon: SafeToastIcon = 'none',
): void {
  const options: SafeToastOptions =
    typeof titleOrOptions === 'string'
      ? { title: titleOrOptions, icon }
      : titleOrOptions

  const title = options.title || ''
  const requestedIcon: SafeToastIcon = options.icon ?? 'none'
  const resolvedIcon: SafeToastIcon =
    requestedIcon !== 'none' && Array.from(title.trim()).length > WECHAT_ICON_TOAST_MAX_CHARS
      ? 'none'
      : requestedIcon

  dismissBlockingLoading()

  const toastPayload: UniApp.ShowToastOptions = {
    title,
    icon: resolvedIcon,
  }
  if (options.duration !== undefined) {
    toastPayload.duration = options.duration
  }
  if (options.mask !== undefined) {
    toastPayload.mask = options.mask
  }
  uni.showToast(toastPayload)
}

/**
 * 用引用计数包裹异步阻塞操作：
 * - 外层仅在 0 -> 1 跃迁时调用一次 `uni.showLoading({ title, mask: true })`；
 * - 无论成功或失败，仅当计数归零（1 -> 0）且 Loading 仍可见时调用 `uni.hideLoading()`；
 * - 保证在 Promise reject / rethrow 给调用方前已完成 `hideLoading()`。
 */
export async function withBlockingLoading<T>(
  title: string,
  fn: () => Promise<T>,
): Promise<T> {
  activeLoadingCount += 1
  if (activeLoadingCount === 1 && !isNativeLoadingVisible) {
    isNativeLoadingVisible = true
    uni.showLoading({ title, mask: true })
  }

  try {
    return await fn()
  } finally {
    activeLoadingCount = Math.max(0, activeLoadingCount - 1)
    if (activeLoadingCount === 0 && isNativeLoadingVisible) {
      isNativeLoadingVisible = false
      uni.hideLoading()
    }
  }
}

/** 仅用于测试重置内部引用计数状态。 */
export function resetLoadingGuardForTest(): void {
  activeLoadingCount = 0
  isNativeLoadingVisible = false
}
