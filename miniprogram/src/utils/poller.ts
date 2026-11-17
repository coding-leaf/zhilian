export type PollerRunResult<T> =
  | { status: 'completed'; value: T }
  | { status: 'timeout'; lastValue: T | undefined }
  | { status: 'stopped'; lastValue: T | undefined }

export interface PollerRunOptions<T> {
  maxAttempts: number
  intervalMs: number | ((attempt: number) => number)
  isDone: (value: T) => boolean
  onAttempt?: (value: T) => void
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

/**
 * 创建可显式取消与销毁的固定间隔轮询器。
 *
 * `stop()` 会立即清除等待定时器并唤醒挂起中的 sleep，避免页面卸载后留下悬空 Promise；
 * `dispose()` 在 `stop()` 基础上永久阻止后续 `run()` 再发起轮询。
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

    try {
      for (let attempt = 0; attempt < options.maxAttempts; attempt += 1) {
        if (disposed || token.cancelled) return { status: 'stopped', lastValue }
        const value = await fetcher()
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
