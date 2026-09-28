export type DraftSaver = (questionId: string, answer: unknown) => Promise<void>

export interface DraftFailure {
  questionId: string
  error: unknown
}

export interface DraftQueueState {
  isPending: boolean
  failures: DraftFailure[]
}

export interface DraftQueue {
  /** 记录一次作答：同题快速输入会被合并为「最后值 + 串行写」。 */
  enqueue(questionId: string, answer: unknown): void
  /** 等待所有在途与待写草稿落库；返回 false 表示仍有失败未恢复。 */
  flush(): Promise<boolean>
  /** 针对失败题目用最后一次作答重试。 */
  retry(questionId: string): Promise<void>
  retryAll(): Promise<void>
  /** 清空队列与失败记录（交卷成功或切换练习时调用）。 */
  reset(): void
  hasFailures(): boolean
  state(): DraftQueueState
}

/**
 * 逐题草稿写入队列：
 * - 同题串行：写入期间的新输入只保留最后值，避免乱序与丢失；
 * - 失败可见：错误进入 failures，由调用方展示重试入口，不静默吞错；
 * - flush 保证交卷前所有待写草稿已成功落库。
 */
export function createDraftQueue(
  save: DraftSaver,
  onChange?: (state: DraftQueueState) => void,
): DraftQueue {
  const latest = new Map<string, unknown>()
  const lastAnswer = new Map<string, unknown>()
  const workers = new Map<string, Promise<void>>()
  const failures = new Map<string, unknown>()

  const snapshot = (): DraftQueueState => ({
    isPending: workers.size > 0 || latest.size > 0,
    failures: Array.from(failures.entries()).map(([questionId, error]) => ({ questionId, error })),
  })

  const notify = () => onChange?.(snapshot())

  const run = async (questionId: string): Promise<void> => {
    while (latest.has(questionId)) {
      const answer = latest.get(questionId)
      latest.delete(questionId)
      notify()
      try {
        await save(questionId, answer)
        failures.delete(questionId)
      } catch (error) {
        failures.set(questionId, error)
      }
    }
  }

  const startWorker = (questionId: string) => {
    if (workers.has(questionId)) return
    const worker = run(questionId).finally(() => {
      workers.delete(questionId)
      notify()
      // 关闭“worker 退出瞬间新输入被漏派发”的窗口
      if (latest.has(questionId)) startWorker(questionId)
    })
    workers.set(questionId, worker)
  }

  const enqueue = (questionId: string, answer: unknown) => {
    latest.set(questionId, answer)
    lastAnswer.set(questionId, answer)
    startWorker(questionId)
    notify()
  }

  const flush = async (): Promise<boolean> => {
    // 反复收敛：等待在途 worker，同时把等待期间新入队的题目继续派发。
    for (let guard = 0; guard < 1000; guard += 1) {
      if (workers.size === 0 && latest.size === 0) break
      for (const questionId of Array.from(latest.keys())) startWorker(questionId)
      await Promise.allSettled(Array.from(workers.values()))
    }
    return failures.size === 0
  }

  const retry = async (questionId: string) => {
    if (!failures.has(questionId) || !lastAnswer.has(questionId)) return
    failures.delete(questionId)
    enqueue(questionId, lastAnswer.get(questionId))
    await flush()
  }

  const retryAll = async () => {
    for (const questionId of Array.from(failures.keys())) {
      if (lastAnswer.has(questionId)) {
        failures.delete(questionId)
        enqueue(questionId, lastAnswer.get(questionId))
      }
    }
    await flush()
  }

  const reset = () => {
    latest.clear()
    lastAnswer.clear()
    failures.clear()
    workers.clear()
    notify()
  }

  return {
    enqueue,
    flush,
    retry,
    retryAll,
    reset,
    hasFailures: () => failures.size > 0,
    state: snapshot,
  }
}
