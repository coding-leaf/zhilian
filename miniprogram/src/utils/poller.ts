export type PollerRunResult<T> =
  | { status: 'completed'; value: T }
  | { status: 'timeout'; lastValue: T | undefined }
  | { status: 'stopped'; lastValue: T | undefined }

export interface PollerRunOptions<T> {
  maxAttempts: number
  intervalMs: number | ((attempt: number) => number)
  isDone: (value: T) => boolean
  onAttempt?: (value: T) => void
  /** 连续瞬时异常容忍上限（默认 3）；达到上限后才向外抛出终止轮询。 */
  maxConsecutiveErrors?: number
  /** 单次 tick 捕获瞬时异常时的可选回调。 */
  onError?: (error: unknown, consecutiveErrors: number) => void
}

export interface PollerHandle {
  run: <T>(fetcher: () => Promise<T>, options: PollerRunOptions<T>) => Promise<PollerRunResult<T>>
  stop: () => void
  dispose: () => void
  readonly isDisposed: boolean
}

interface RunToken {
  cancelled: boolean
}

const DEFAULT_MAX_CONSECUTIVE_ERRORS = 3

/**
 * 创建可显式取消与销毁的轮询器。
 *
 * - `stop()` 会立即清除等待定时器并唤醒挂起中的 sleep，避免页面卸载后留下悬空 Promise；
 * - `dispose()` 在 `stop()` 基础上永久阻止后续 `run()` 再发起轮询；
 * - 对单次 tick 的瞬时网络异常具备容错能力：在 `maxConsecutiveErrors`（默认 3）以内自动按计划重试，
 *   任意一次成功 tick 均重置连续失败计数，避免一次网络抖动永久杀死判题/任务轮询。
 */
export function createPoller(): PollerHandle {
  let disposed = false
  let activeRun: RunToken | null = null
  let activeTimer: ReturnType<typeof setTimeout> | null = null
  let cancelSleep: (() => void) | null = null

  const clearWaiter = () => {
    if (activeTimer !== null) {
      clearTimeout(activeTimer)
      activeTimer = null
    }
    if (cancelSleep) {
      const wake = cancelSleep
      cancelSleep = null
      wake()
    }
  }

  const stop = () => {
    if (activeRun) activeRun.cancelled = true
    clearWaiter()
  }

  const dispose = () => {
    disposed = true
    stop()
  }

  const waitInterval = (ms: number, token: RunToken): Promise<void> => {
    if (disposed || token.cancelled) return Promise.resolve()
    if (ms <= 0) return Promise.resolve()
    return new Promise((resolve) => {
      cancelSleep = resolve
      activeTimer = setTimeout(() => {
        activeTimer = null
        cancelSleep = null
        resolve()
      }, ms)
    })
  }

  const run = async <T>(
    fetcher: () => Promise<T>,
    options: PollerRunOptions<T>,
  ): Promise<PollerRunResult<T>> => {
    if (disposed) return { status: 'stopped', lastValue: undefined }
    stop()
    const token: RunToken = { cancelled: false }
    activeRun = token
    let lastValue: T | undefined
    const maxConsecutiveErrors = Math.max(
      1,
      options.maxConsecutiveErrors ?? DEFAULT_MAX_CONSECUTIVE_ERRORS,
    )
    let consecutiveErrors = 0

    try {
      for (let attempt = 0; attempt < options.maxAttempts; attempt += 1) {
        if (disposed || token.cancelled) return { status: 'stopped', lastValue }
        let value: T
        try {
          value = await fetcher()
          consecutiveErrors = 0
        } catch (error) {
          if (disposed || token.cancelled) return { status: 'stopped', lastValue }
          consecutiveErrors += 1
          options.onError?.(error, consecutiveErrors)
          console.error(
            `[poller] tick failed (${consecutiveErrors}/${maxConsecutiveErrors}):`,
            error,
          )
          if (consecutiveErrors >= maxConsecutiveErrors) {
            throw error
          }
          if (attempt < options.maxAttempts - 1) {
            const delayMs =
              typeof options.intervalMs === 'function'
                ? options.intervalMs(attempt)
                : options.intervalMs
            await waitInterval(delayMs, token)
            if (disposed || token.cancelled) return { status: 'stopped', lastValue }
          }
          continue
        }

        lastValue = value
        if (disposed || token.cancelled) return { status: 'stopped', lastValue }
        if (options.isDone(value)) return { status: 'completed', value }
        options.onAttempt?.(value)
        if (attempt < options.maxAttempts - 1) {
          const delayMs =
            typeof options.intervalMs === 'function' ? options.intervalMs(attempt) : options.intervalMs
          await waitInterval(delayMs, token)
          if (disposed || token.cancelled) return { status: 'stopped', lastValue }
        }
      }
      return { status: 'timeout', lastValue }
    } finally {
      if (activeRun === token) {
        clearWaiter()
        activeRun = null
      }
    }
  }

  return {
    run,
    stop,
    dispose,
    get isDisposed() {
      return disposed
    },
  }
}
