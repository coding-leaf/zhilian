import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPoller } from '@/utils/poller'

describe('cancellable poller utility', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('resolves completed when terminal condition matches within maxAttempts', async () => {
    const poller = createPoller()
    let count = 0
    const promise = poller.run(
      async () => {
        count += 1
        return { ready: count === 3, attempt: count }
      },
      {
        maxAttempts: 5,
        intervalMs: 1000,
        isDone: (v) => v.ready,
      },
    )

    await vi.advanceTimersByTimeAsync(0)
    expect(count).toBe(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(count).toBe(2)
    await vi.advanceTimersByTimeAsync(1000)
    expect(count).toBe(3)

    const res = await promise
    expect(res).toEqual({ status: 'completed', value: { ready: true, attempt: 3 } })
  })

  it('resolves timeout after exhausting maxAttempts without dangling extra sleep', async () => {
    const poller = createPoller()
    let count = 0
    const onAttempt = vi.fn()
    const promise = poller.run(
      async () => {
        count += 1
        return count
      },
      {
        maxAttempts: 2,
        intervalMs: 1500,
        isDone: () => false,
        onAttempt,
      },
    )

    await vi.advanceTimersByTimeAsync(0)
    expect(onAttempt).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1500)

    const res = await promise
    expect(count).toBe(2)
    expect(onAttempt).toHaveBeenCalledTimes(2)
    expect(res).toEqual({ status: 'timeout', lastValue: 2 })
  })

  it('aborts pending wait immediately on stop() and clears active timer', async () => {
    const poller = createPoller()
    const fetcher = vi.fn().mockResolvedValue('pending')
    const promise = poller.run(fetcher, {
      maxAttempts: 10,
      intervalMs: 5000,
      isDone: () => false,
    })

    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(1)

    poller.stop()
    const res = await promise
    expect(res).toEqual({ status: 'stopped', lastValue: 'pending' })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('blocks future runs after dispose()', async () => {
    const poller = createPoller()
    poller.dispose()
    expect(poller.isDisposed).toBe(true)

    const fetcher = vi.fn()
    const res = await poller.run(fetcher, {
      maxAttempts: 3,
      intervalMs: 100,
      isDone: () => true,
    })
    expect(fetcher).not.toHaveBeenCalled()
    expect(res).toEqual({ status: 'stopped', lastValue: undefined })
  })

  it('tolerates transient errors below maxConsecutiveErrors and resets counter on success', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const poller = createPoller()
    let call = 0
    const onError = vi.fn()
    const promise = poller.run(
      async () => {
        call += 1
        // 连续失败 2 次 -> 第 3 次成功重置计数 -> 再失败 2 次 -> 第 6 次完成
        if (call === 1 || call === 2 || call === 4 || call === 5) {
          throw new Error(`transient-${call}`)
        }
        return { done: call === 6, call }
      },
      {
        maxAttempts: 8,
        intervalMs: 500,
        isDone: (v) => v.done,
        onError,
      },
    )

    for (let i = 0; i < 6; i += 1) {
      await vi.advanceTimersByTimeAsync(i === 0 ? 0 : 500)
    }

    const res = await promise
    expect(res).toEqual({ status: 'completed', value: { done: true, call: 6 } })
    expect(onError).toHaveBeenCalledTimes(4)
  })

  it('throws and aborts polling once consecutive errors reach maxConsecutiveErrors', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const poller = createPoller()
    let call = 0
    const promise = poller.run(
      async () => {
        call += 1
        throw new Error(`down-${call}`)
      },
      {
        maxAttempts: 10,
        intervalMs: 300,
        maxConsecutiveErrors: 3,
        isDone: () => false,
      },
    )
    const caught = promise.catch((err) => err)

    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(300)
    await vi.advanceTimersByTimeAsync(300)

    const error = await caught
    expect(error).toBeInstanceOf(Error)
    expect(error.message).toBe('down-3')
    expect(call).toBe(3)
  })
})
