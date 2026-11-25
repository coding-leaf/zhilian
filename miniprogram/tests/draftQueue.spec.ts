import { describe, expect, it, vi } from 'vitest'
import { createDraftQueue } from '../src/utils/draftQueue'

const flushMicrotasks = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('draft queue reliability', () => {
  it('serializes writes per question and keeps only the last rapid input', async () => {
    const calls: Array<[string, unknown]> = []
    const queue = createDraftQueue(async (questionId, answer) => {
      calls.push([questionId, answer])
      await flushMicrotasks()
    })

    queue.enqueue('q-1', 'A')
    queue.enqueue('q-1', 'AB')
    queue.enqueue('q-1', 'ABC')

    const saved = await queue.flush()

    expect(saved).toBe(true)
    expect(calls.filter(([id]) => id === 'q-1').map(([, answer]) => answer)).toEqual(['A', 'ABC'])
  })

  it('writes different questions in parallel without cross-contamination', async () => {
    const calls: string[] = []
    const queue = createDraftQueue(async (questionId) => {
      calls.push(questionId)
      await flushMicrotasks()
    })

    queue.enqueue('q-1', 'A')
    queue.enqueue('q-2', ['A', 'B'])
    await queue.flush()

    expect(calls.sort()).toEqual(['q-1', 'q-2'])
  })

  it('surfaces failures instead of swallowing them and can retry', async () => {
    let failNext = true
    const queue = createDraftQueue(async () => {
      if (failNext) throw new Error('network down')
    })

    queue.enqueue('q-1', 'A')
    const firstFlush = await queue.flush()

    expect(firstFlush).toBe(false)
    expect(queue.hasFailures()).toBe(true)
    expect(queue.state().failures.map((failure) => failure.questionId)).toEqual(['q-1'])

    failNext = false
    await queue.retry('q-1')

    expect(queue.hasFailures()).toBe(false)
  })

  it('flushes answers enqueued while a previous write is still in flight', async () => {
    let release: () => void = () => {}
    const calls: unknown[] = []
    const queue = createDraftQueue(async (_questionId, answer) => {
      calls.push(answer)
      if (answer === 'first') {
        await new Promise<void>((resolve) => { release = resolve })
      }
    })

    queue.enqueue('q-1', 'first')
    await flushMicrotasks()
    queue.enqueue('q-1', 'second')

    const flushing = queue.flush()
    release()
    const saved = await flushing

    expect(saved).toBe(true)
    expect(calls).toEqual(['first', 'second'])
    expect(queue.hasFailures()).toBe(false)
  })

  it('ignores stale in-flight failure and resolution after reset() via epoch isolation', async () => {
    let rejectOld!: (err: Error) => void
    const changes: Array<{ isPending: boolean; failures: number }> = []
    const queue = createDraftQueue(
      async (questionId) => {
        if (questionId === 'q-old') {
          await new Promise<void>((_resolve, reject) => {
            rejectOld = reject
          })
        }
      },
      (state) => {
        changes.push({ isPending: state.isPending, failures: state.failures.length })
      },
    )

    queue.enqueue('q-old', 'A', 'p-A')
    await flushMicrotasks()

    queue.reset()
    const notifyCountAfterReset = changes.length

    rejectOld(new Error('stale network failure'))
    await flushMicrotasks()

    expect(queue.hasFailures()).toBe(false)
    expect(queue.state().failures).toEqual([])
    expect(changes.length).toBe(notifyCountAfterReset)
    expect(await queue.flush()).toBe(true)
  })

  it('statically binds practiceId per queued task and caps concurrent saves to <= 2', async () => {
    let inFlight = 0
    let maxInFlight = 0
    const received: Array<{ questionId: string; practiceId?: string }> = []

    const queue = createDraftQueue(
      async (questionId, _answer, practiceId) => {
        inFlight += 1
        maxInFlight = Math.max(maxInFlight, inFlight)
        received.push({ questionId, practiceId })
        await new Promise((resolve) => setTimeout(resolve, 10))
        inFlight -= 1
      },
      undefined,
      { maxConcurrent: 2 },
    )

    for (let i = 1; i <= 5; i += 1) {
      queue.enqueue(`q-${i}`, `ans-${i}`, 'p-static-1')
    }

    const saved = await queue.flush()
    expect(saved).toBe(true)
    expect(maxInFlight).toBeLessThanOrEqual(2)
    expect(received).toHaveLength(5)
    expect(received.every((item) => item.practiceId === 'p-static-1')).toBe(true)
  })

  it('serializes retryAll() so failed drafts retry one by one', async () => {
    let shouldFail = true
    let inFlightDuringRetry = 0
    let maxInFlightDuringRetry = 0
    const retryOrder: string[] = []

    const queue = createDraftQueue(async (questionId) => {
      if (shouldFail) throw new Error('offline')
      inFlightDuringRetry += 1
      maxInFlightDuringRetry = Math.max(maxInFlightDuringRetry, inFlightDuringRetry)
      retryOrder.push(questionId)
      await new Promise((resolve) => setTimeout(resolve, 10))
      inFlightDuringRetry -= 1
    })

    queue.enqueue('q-1', 'A', 'p-1')
    queue.enqueue('q-2', 'B', 'p-1')
    queue.enqueue('q-3', 'C', 'p-1')
    expect(await queue.flush()).toBe(false)
    expect(queue.state().failures).toHaveLength(3)

    shouldFail = false
    await queue.retryAll()

    expect(queue.hasFailures()).toBe(false)
    expect(maxInFlightDuringRetry).toBe(1)
    expect(retryOrder).toEqual(['q-1', 'q-2', 'q-3'])
  })
})
