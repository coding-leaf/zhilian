import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import { usePracticeStore } from '@/stores/practice'
import { useAuthStore } from '@/stores/auth'
import { practiceDetailFixture } from './fixtures/backendResponses'

const inProgressSession = {
  id: 'p-1',
  title: '练习',
  status: 'in_progress',
  total_count: 3,
  questions: [],
  items: [],
}

const submitCalls = () => requestMock.mock.calls.filter(([options]: any[]) => options.url.endsWith('/submit'))
const answerCalls = () => requestMock.mock.calls.filter(([options]: any[]) => options.url.endsWith('/answers'))

describe('practice store submit reliability', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    requestMock.mockReset()
    requestMock.mockImplementation(async (options: any) => {
      if (options.url.endsWith('/answers')) return { success: true }
      if (options.url.endsWith('/submit')) return { practice_id: 'p-1', status: 'submitted' }
      if (options.url === '/practices/p-1') return practiceDetailFixture
      throw new Error(`unexpected request: ${options.url}`)
    })
  })

  it('flushes pending drafts before submitting and refreshes the session', async () => {
    const store = usePracticeStore()
    store.currentSession = inProgressSession as any

    store.recordAnswer('q-1', 'A')
    store.recordAnswer('q-2', '我的论述')

    const session = await store.submit()

    expect(answerCalls()).toHaveLength(2)
    expect(submitCalls()).toHaveLength(1)
    expect(session.status).toBe('partially_graded')
    expect(uni.getStorageSync(`practice_draft_anonymous_p-1`)).toBe('')
  })

  it('blocks submission and surfaces the failure when a draft cannot be saved', async () => {
    const store = usePracticeStore()
    store.currentSession = inProgressSession as any

    requestMock.mockImplementation(async (options: any) => {
      if (options.url.endsWith('/answers')) throw new Error('network down')
      return {}
    })

    store.recordAnswer('q-1', 'A')

    await expect(store.submit()).rejects.toThrow('仍有作答未保存成功')
    expect(submitCalls()).toHaveLength(0)
    expect(store.draftFailures).toEqual(['q-1'])

    // 恢复网络后重试草稿，再交卷即可成功
    requestMock.mockImplementation(async (options: any) => {
      if (options.url.endsWith('/answers')) return { success: true }
      if (options.url.endsWith('/submit')) return { practice_id: 'p-1', status: 'submitted' }
      return practiceDetailFixture
    })
    await store.retryAllDrafts()
    expect(store.draftFailures).toEqual([])

    const session = await store.submit()
    expect(submitCalls()).toHaveLength(1)
    expect(session.id).toBe('p-1')
  })

  it('reuses a stable Idempotency-Key across retries of the same submission', async () => {
    const store = usePracticeStore()
    store.currentSession = inProgressSession as any

    requestMock.mockImplementation(async (options: any) => {
      if (options.url.endsWith('/answers')) return { success: true }
      if (options.url.endsWith('/submit')) throw new Error('gateway timeout')
      return {}
    })

    await expect(store.submit()).rejects.toThrow('gateway timeout')
    const firstKey = submitCalls()[0][0].header['Idempotency-Key']
    expect(firstKey).toBeTruthy()

    requestMock.mockImplementation(async (options: any) => {
      if (options.url.endsWith('/answers')) return { success: true }
      if (options.url.endsWith('/submit')) return { practice_id: 'p-1', status: 'submitted' }
      return practiceDetailFixture
    })
    await store.submit()

    const keys = submitCalls().map(([options]: any[]) => options.header['Idempotency-Key'])
    expect(keys).toEqual([firstKey, firstKey])
  })
})

describe('practice store draft isolation and epoch safety', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    requestMock.mockReset()
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/practices/p-1') return practiceDetailFixture
      if (options.url.endsWith('/answers')) return { success: true }
      throw new Error(`unexpected request: ${options.url}`)
    })
  })

  it('keeps local drafts isolated per user and restores only the current user draft', async () => {
    const auth = useAuthStore()
    auth.user = { id: 'u1', nickname: '用户一' } as any
    const first = usePracticeStore()
    await first.initPractice('p-1')
    first.recordAnswer('q-2', 'u1-answer')

    expect(uni.getStorageSync('practice_draft_u1_p-1')).toMatchObject({ 'q-2': 'u1-answer' })

    setActivePinia(createPinia())
    const otherAuth = useAuthStore()
    otherAuth.user = { id: 'u2', nickname: '用户二' } as any
    const second = usePracticeStore()
    await second.initPractice('p-1')

    // 用户二不会读到用户一的本地草稿，回退到服务端已存作答
    expect(second.userAnswers['q-2']).toBe('我的论述')
    expect(second.userAnswers['q-2']).not.toBe('u1-answer')
  })

  it('sends silentToast=true on draft saves and cleans anonymous draft fallback on submit', async () => {
    const auth = useAuthStore()
    const store = usePracticeStore()
    requestMock.mockImplementation(async (options: any) => {
      if (options.url.endsWith('/answers')) return { success: true }
      if (options.url.endsWith('/submit')) return { practice_id: 'p-1', status: 'submitted' }
      if (options.url === '/practices/p-1') return practiceDetailFixture
      throw new Error(`unexpected request: ${options.url}`)
    })

    store.currentSession = inProgressSession as any
    // 资料尚未拉取完成时写到 anonymous 键
    store.recordAnswer('q-1', 'A')
    expect(uni.getStorageSync('practice_draft_anonymous_p-1')).toMatchObject({ 'q-1': 'A' })

    // 随后用户资料就绪，交卷时应同时清理当前用户键与 anonymous 兜底键
    auth.user = { id: 'u1', nickname: '用户一' } as any
    await store.submit()

    const draftCall = answerCalls()[0]?.[0]
    expect(draftCall?.silentToast).toBe(true)
    expect(uni.getStorageSync('practice_draft_anonymous_p-1')).toBe('')
    expect(uni.getStorageSync('practice_draft_u1_p-1')).toBe('')
  })

  it('isolates in-flight draft failures across practice switch so new practice can still submit (P0-5)', async () => {
    let rejectPracticeADraft!: (err: Error) => void
    const store = usePracticeStore()
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/practices/p-A/answers') {
        return new Promise((_resolve, reject) => {
          rejectPracticeADraft = reject
        })
      }
      if (options.url === '/practices/p-B') {
        return { ...practiceDetailFixture, id: 'p-B', practice_id: 'p-B' }
      }
      if (options.url === '/practices/p-B/answers') return { success: true }
      if (options.url === '/practices/p-B/submit') return { practice_id: 'p-B', status: 'submitted' }
      throw new Error(`unexpected request: ${options.url}`)
    })

    store.currentSession = { ...inProgressSession, id: 'p-A' } as any
    store.recordAnswer('q-old', 'A')

    // 立即切换到练习 B，在途练习 A 的草稿随后失败
    await store.initPractice('p-B')
    rejectPracticeADraft(new Error('old practice network timeout'))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.draftFailures).toEqual([])
    store.recordAnswer('q-new', 'B')
    const submitted = await store.submit()
    expect(submitted.id).toBe('p-B')
    expect(submitCalls()).toHaveLength(1)
  })
})

describe('practice store grading retry (AC-9)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    requestMock.mockReset()
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/practices/p-1/regrade') return { practice_id: 'p-1', status: 'submitted', message: 'ok' }
      if (options.url === '/practices/p-1') return practiceDetailFixture
      throw new Error(`unexpected request: ${options.url}`)
    })
  })

  const regradeCalls = () => requestMock.mock.calls.filter(([options]: any[]) => options.url.endsWith('/regrade'))

  it('re-dispatches grading and refreshes the session afterwards', async () => {
    const store = usePracticeStore()
    store.currentSession = { ...inProgressSession, status: 'partially_graded' } as any

    const session = await store.retryGrading()

    expect(regradeCalls()).toHaveLength(1)
    expect(regradeCalls()[0][0].method).toBe('POST')
    expect(session?.id).toBe('p-1')
  })

  it('rejects retry without an active practice', async () => {
    const store = usePracticeStore()

    await expect(store.retryGrading()).rejects.toThrow('当前没有可重试判题的练习')
    expect(regradeCalls()).toHaveLength(0)
  })
})
