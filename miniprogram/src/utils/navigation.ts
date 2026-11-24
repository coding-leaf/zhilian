import { safeShowToast } from './loadingGuard'

/** 微信小程序页面栈硬上限为 10 层，达到 9 层时改用 `redirectTo` 避免 `webview count limit exceed`。 */
export const SAFE_PAGE_STACK_LIMIT = 9

export interface SafeNavigateOptions {
  fail?: (err: unknown) => void
  /** 默认在导航失败时弹出兜底提示；传入 `false` 或自定义 `fail` 回调时由调用方接管。 */
  failMessage?: string
}

/**
 * 带页面栈深度守卫的安全跳转：
 * 当 `getCurrentPages().length >= 9` 时自动降级为 `uni.redirectTo`，防止闭环压栈撞穿 10 层上限。
 */
export function safeNavigateTo(url: string, options?: SafeNavigateOptions): void {
  const stackDepth = typeof getCurrentPages === 'function' ? getCurrentPages().length : 0
  const handleFail =
    options?.fail ??
    (() => {
      safeShowToast(options?.failMessage || '页面跳转失败，请重试')
    })

  if (stackDepth >= SAFE_PAGE_STACK_LIMIT) {
    uni.redirectTo({
      url,
      fail: handleFail,
    })
    return
  }

  uni.navigateTo({
    url,
    fail: handleFail,
  })
}
