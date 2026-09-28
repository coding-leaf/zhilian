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
    let release: (() => void) | null = null
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
    release?.()
    const saved = await flushing

    expect(saved).toBe(true)
    expect(calls).toEqual(['first', 'second'])
    expect(queue.hasFailures()).toBe(false)
  })
})
