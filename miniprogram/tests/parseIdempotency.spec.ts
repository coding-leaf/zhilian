import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useCourseDetail } from '@/subpackages/material/composables/useCourseDetail'

describe('material parse double-submit guard & request coalescing', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    requestMock.mockReset()
  })

  afterEach(() => {
    useBackgroundTaskStore().reset()
    vi.restoreAllMocks()
  })

  it('coalesces concurrent startMaterialParse calls for the same materialId and cleans up in finally', async () => {
    let resolveFirst!: (val: { message: string }) => void
    let callCount = 0
    requestMock.mockImplementation(() => {
      callCount += 1
      if (callCount === 1) {
        return new Promise<{ message: string }>((resolve) => {
          resolveFirst = resolve
        })
      }
      if (callCount === 2) {
        return Promise.reject(new Error('network error'))
      }
      return Promise.resolve({ message: 'requeued' })
    })

    const store = useBackgroundTaskStore()
    const p1 = store.startMaterialParse('m-1', '高数讲义.pdf', false)
    const p2 = store.startMaterialParse('m-1', '高数讲义.pdf', false)

    expect(requestMock).toHaveBeenCalledTimes(1)

    resolveFirst({ message: 'queued' })
    const [r1, r2] = await Promise.all([p1, p2])
    expect(r1).toEqual({ message: 'queued' })
    expect(r2).toEqual({ message: 'queued' })
    expect(requestMock).toHaveBeenCalledTimes(1)

    // After settlement, a failed request cleans up in finally so subsequent retries issue a new request
    await expect(store.startMaterialParse('m-1', '高数讲义.pdf', true)).rejects.toThrow('network error')
    expect(requestMock).toHaveBeenCalledTimes(2)

    const r3 = await store.startMaterialParse('m-1', '高数讲义.pdf', true)
    expect(r3).toEqual({ message: 'requeued' })
    expect(requestMock).toHaveBeenCalledTimes(3)
  })

  it('guards useCourseDetail startParse and confirmAndReparse with isStartingParse and isParsing', async () => {
    let resolveParse!: (val: { message: string }) => void
    const showModalSpy = vi.spyOn(uni, 'showModal')
    requestMock.mockImplementation(async ({ url, method }: { url: string; method?: string }) => {
      if (url === '/materials/m-2' && method === 'GET') {
        return {
          id: 'm-2',
          title: '线性代数.pdf',
          status: 'pending',
          parse_status: 'not_started',
          created_at: '2026-11-25T00:00:00',
        }
      }
      if (url.startsWith('/materials/m-2/parse') && method === 'POST') {
        return new Promise<{ message: string }>((resolve) => {
          resolveParse = resolve
        })
      }
      return {}
    })

    const course = useCourseDetail()
    await course.initCourse('m-2')

    expect(course.isStartingParse.value).toBe(false)
    const first = course.startParse(false)
    expect(course.isStartingParse.value).toBe(true)

    // Double tap while starting should be ignored and not open modal or send second request
    await course.startParse(false)
    course.confirmAndReparse()
    expect(showModalSpy).not.toHaveBeenCalled()
    expect(requestMock.mock.calls.filter(([o]) => String((o as { url: string }).url).includes('/parse'))).toHaveLength(1)

    resolveParse({ message: 'queued' })
    await first

    expect(course.isStartingParse.value).toBe(false)
    expect(course.isParsing.value).toBe(true)

    // Once parsing, confirmAndReparse and startParse remain blocked
    await course.startParse(true)
    course.confirmAndReparse()
    expect(showModalSpy).not.toHaveBeenCalled()
    expect(requestMock.mock.calls.filter(([o]) => String((o as { url: string }).url).includes('/parse'))).toHaveLength(1)
  })
})
