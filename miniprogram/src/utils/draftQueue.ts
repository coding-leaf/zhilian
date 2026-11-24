export type DraftSaver = (
  questionId: string,
  answer: unknown,
  practiceId?: string,
) => Promise<void>

export interface DraftFailure {
  questionId: string
  error: unknown
}

export interface DraftQueueState {
  isPending: boolean
  failures: DraftFailure[]
}

export interface DraftQueueOptions {
  /** 同时在途的草稿保存上限（默认 2），防止快速切题或重试撞上微信 10 并发上限。 */
  maxConcurrent?: number
}

export interface DraftQueue {
  /** 记录一次作答：同题快速输入会被合并为「最后值 + 串行写」，静态绑定 practiceId。 */
  enqueue(questionId: string, answer: unknown, practiceId?: string): void
  /** 等待所有在途与待写草稿落库；返回 false 表示仍有失败未恢复或队列已被切换重置。 */
  flush(): Promise<boolean>
  /** 针对失败题目用最后一次作答重试。 */
  retry(questionId: string): Promise<void>
  /** 串行重试全部失败草稿，避免弱网下瞬时并发雪崩。 */
  retryAll(): Promise<void>
  /** 清空队列与失败记录并递增代际号 epoch，使旧在途任务静默作废。 */
  reset(): void
  hasFailures(): boolean
  state(): DraftQueueState
}

interface DraftTaskPayload {
  questionId: string
  answer: unknown
  practiceId?: string
}

const DEFAULT_MAX_CONCURRENT_DRAFTS = 2

/**
 * 逐题草稿写入队列：
 * - 同题串行：写入期间的新输入只保留最后值，避免乱序与丢失；
 * - 全局限流：同时最多 `maxConcurrent`（默认 2）道题在途保存，不挤占全局并发配额；
 * - 代际隔离：每次 `reset()` 递增 `epoch`，旧练习在途请求无论成功/失败均静默丢弃，
 *   绝不写入新练习的 `failures` 或触发 `notify()`，根治切题死锁交卷（P0-5）；
 * - 静态绑定：每个入队载荷绑定当时的 `practiceId`，避免动态读取已切换的全局会话。
 */
export function createDraftQueue(
  save: DraftSaver,
  onChange?: (state: DraftQueueState) => void,
  options?: DraftQueueOptions,
): DraftQueue {
  const maxConcurrent = Math.max(1, options?.maxConcurrent ?? DEFAULT_MAX_CONCURRENT_DRAFTS)

  let epoch = 0
  let activeWorkers = 0
  const latest = new Map<string, DraftTaskPayload>()
  const lastEntry = new Map<string, DraftTaskPayload>()
  const workers = new Map<string, Promise<void>>()
  const failures = new Map<string, unknown>()
  const readyQueue: string[] = []

  const snapshot = (): DraftQueueState => ({
    isPending: workers.size > 0 || latest.size > 0,
    failures: Array.from(failures.entries()).map(([questionId, error]) => ({ questionId, error })),
  })

  const notify = () => onChange?.(snapshot())

  const enqueueReady = (questionId: string) => {
    if (!workers.has(questionId) && !readyQueue.includes(questionId)) {
      readyQueue.push(questionId)
    }
  }

  const run = async (questionId: string, myEpoch: number): Promise<void> => {
    while (myEpoch === epoch && latest.has(questionId)) {
      const payload = latest.get(questionId)!
      latest.delete(questionId)
      notify()
      try {
        await save(payload.questionId, payload.answer, payload.practiceId)
        if (myEpoch !== epoch) return
        failures.delete(questionId)
      } catch (error) {
        if (myEpoch !== epoch) return
        failures.set(questionId, error)
      }
    }
  }

  const schedule = (expectedEpoch: number) => {
    if (expectedEpoch !== epoch) return
    while (activeWorkers < maxConcurrent && readyQueue.length > 0) {
      const nextId = readyQueue.shift()!
      if (workers.has(nextId) || !latest.has(nextId)) continue
      startWorker(nextId, expectedEpoch)
    }
  }

  const startWorker = (questionId: string, myEpoch: number) => {
    if (myEpoch !== epoch || workers.has(questionId)) return
    activeWorkers += 1
    const worker = run(questionId, myEpoch).finally(() => {
      if (myEpoch !== epoch) return
      activeWorkers = Math.max(0, activeWorkers - 1)
      workers.delete(questionId)
      if (latest.has(questionId)) {
        enqueueReady(questionId)
      }
      schedule(myEpoch)
      notify()
    })
    workers.set(questionId, worker)
  }

  const enqueue = (questionId: string, answer: unknown, practiceId?: string) => {
    const payload: DraftTaskPayload = { questionId, answer, practiceId }
    latest.set(questionId, payload)
    lastEntry.set(questionId, payload)
    enqueueReady(questionId)
    schedule(epoch)
    notify()
  }

  const flush = async (): Promise<boolean> => {
    const myEpoch = epoch
    // 反复收敛：等待在途 worker，同时把等待期间新入队的题目继续按并发上限派发。
    for (let guard = 0; guard < 1000; guard += 1) {
      if (myEpoch !== epoch) return false
      if (workers.size === 0 && latest.size === 0) break
      for (const questionId of Array.from(latest.keys())) {
        enqueueReady(questionId)
      }
      schedule(myEpoch)
      if (workers.size === 0) break
      await Promise.allSettled(Array.from(workers.values()))
    }
    return myEpoch === epoch && failures.size === 0
  }

  const retry = async (questionId: string) => {
    const myEpoch = epoch
    const entry = lastEntry.get(questionId)
    if (!failures.has(questionId) || !entry) return
    failures.delete(questionId)
    enqueue(entry.questionId, entry.answer, entry.practiceId)
    await flush()
    if (myEpoch !== epoch) return
  }

  const retryAll = async () => {
    const myEpoch = epoch
    const failedIds = Array.from(failures.keys())
    for (const questionId of failedIds) {
      if (myEpoch !== epoch) return
      const entry = lastEntry.get(questionId)
      if (!entry) continue
      failures.delete(questionId)
      enqueue(entry.questionId, entry.answer, entry.practiceId)
      await flush()
    }
  }

  const reset = () => {
    epoch += 1
    activeWorkers = 0
    latest.clear()
    lastEntry.clear()
    failures.clear()
    workers.clear()
    readyQueue.length = 0
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
