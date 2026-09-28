import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { request, uploadFile } from '@/utils/request'
import {
  DEFAULT_REQUEST_TIMEOUT_MS,
  LONG_REQUEST_TIMEOUT_MS,
  RequestError,
  classifyTransportFailure,
} from '@/utils/requestError'
import {
  apiAskQuestionCoach,
  apiAskScopedCoach,
  apiGenerateQuestions,
  apiGetUserProfile,
  apiLoginByWechat,
  apiRegradeAttempt,
  apiSubmitPractice,
} from '@/api'

const requestMock = vi.fn()

/** `tests/setup.ts` 已经把 `uni` 挂到 globalThis；这里取引用以便按需替换其方法。 */
const uniGlobal = globalThis as any

/** 取最后一次传给 uni.request 的选项。 */
const lastRequestOptions = () => requestMock.mock.calls.at(-1)?.[0]

const replySuccess = (data: any = {}) => {
  requestMock.mockImplementation((options: any) => {
    options.success({ statusCode: 200, data })
  })
}

const replyFailure = (err: any) => {
  requestMock.mockImplementation((options: any) => {
    options.fail(err)
  })
}

const replyStatus = (statusCode: number, data: any = {}) => {
  requestMock.mockImplementation((options: any) => {
    options.success({ statusCode, data })
  })
}

describe('request layer: explicit timeout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    requestMock.mockReset()
    uniGlobal.uni.request = requestMock
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('passes the converged default timeout to uni.request instead of relying on the 60s platform default', () => {
    replySuccess()

    void request({ url: '/anything' })

    expect(lastRequestOptions().timeout).toBe(DEFAULT_REQUEST_TIMEOUT_MS)
    expect(DEFAULT_REQUEST_TIMEOUT_MS).toBe(15000)
  })

  it('lets a single call override the timeout', () => {
    replySuccess()

    void request({ url: '/anything', timeout: 1234 })

    expect(lastRequestOptions().timeout).toBe(1234)
  })
})

describe('request layer: synchronous LLM endpoints keep a long timeout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    requestMock.mockReset()
    uniGlobal.uni.request = requestMock
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('annotates question generation with the long timeout', async () => {
    replySuccess({
      batch_id: 'b-1',
      total_generated: 0,
      qualified_count: 0,
      pending_count: 0,
      qualified_questions: [],
      pending_questions: [],
    })

    await apiGenerateQuestions({ knowledge_point_ids: ['k-1'] })

    expect(lastRequestOptions().timeout).toBe(LONG_REQUEST_TIMEOUT_MS)
  })

  it('annotates both coach endpoints and attempt regrade with the long timeout', async () => {
    replySuccess({})

    await apiAskQuestionCoach('q-1', '为什么').catch(() => undefined)
    expect(lastRequestOptions().timeout).toBe(LONG_REQUEST_TIMEOUT_MS)

    await apiAskScopedCoach({ user_prompt: '讲讲这个考点' }).catch(() => undefined)
    expect(lastRequestOptions().timeout).toBe(LONG_REQUEST_TIMEOUT_MS)

    await apiRegradeAttempt('a-1', '分数偏低').catch(() => undefined)
    expect(lastRequestOptions().timeout).toBe(LONG_REQUEST_TIMEOUT_MS)
  })

  it('keeps the converged default on non-LLM endpoints', async () => {
    replySuccess({ access_token: 't' })

    await apiLoginByWechat('dev_code').catch(() => undefined)
    expect(lastRequestOptions().timeout).toBe(DEFAULT_REQUEST_TIMEOUT_MS)

    replySuccess({})
    await apiSubmitPractice('p-1').catch(() => undefined)
    expect(lastRequestOptions().timeout).toBe(DEFAULT_REQUEST_TIMEOUT_MS)

    await apiGetUserProfile().catch(() => undefined)
    expect(lastRequestOptions().timeout).toBe(DEFAULT_REQUEST_TIMEOUT_MS)
  })
})

describe('request layer: diagnosable failures', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    requestMock.mockReset()
    uniGlobal.uni.request = requestMock
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('normalises a transport timeout into a timeout error carrying url, errMsg and errno', async () => {
    replyFailure({ errMsg: 'request:fail timeout', errno: '<Undefined>' })

    const rejection = await request({ url: '/auth/login', method: 'POST' }).catch((err) => err)

    expect(rejection).toBeInstanceOf(RequestError)
    expect(rejection.kind).toBe('timeout')
    expect(rejection.url).toContain('/auth/login')
    expect(rejection.method).toBe('POST')
    expect(rejection.errMsg).toBe('request:fail timeout')
    expect(rejection.describe()).toContain('request:fail timeout')
    expect(rejection.describe()).toContain('/auth/login')
  })

  it('states the elapsed budget in the timeout toast so the wait is explainable', async () => {
    const toast = vi.spyOn(uniGlobal.uni, 'showToast')
    replyFailure({ errMsg: 'request:fail timeout', errno: '<Undefined>' })

    await request({ url: '/auth/login', method: 'POST' }).catch(() => undefined)

    const title = toast.mock.calls.at(-1)?.[0].title as string
    expect(title).toContain('超时')
    expect(title).toContain('15')
  })

  it('separates a plain transport failure from a timeout', async () => {
    const toast = vi.spyOn(uniGlobal.uni, 'showToast')
    replyFailure({ errMsg: 'request:fail -102:net::ERR_CONNECTION_REFUSED' })

    const rejection = await request({ url: '/users/me' }).catch((err) => err)

    expect(rejection.kind).toBe('network')
    const title = toast.mock.calls.at(-1)?.[0].title as string
    expect(title).not.toContain('超时')
    expect(title).toContain('网络')
  })

  it('keeps the backend detail and status code on an HTTP rejection', async () => {
    replyStatus(422, { detail: '考点不存在或越权' })

    const rejection = await request({ url: '/knowledge/k-1' }).catch((err) => err)

    expect(rejection.kind).toBe('http')
    expect(rejection.statusCode).toBe(422)
    expect(rejection.detail).toBe('考点不存在或越权')
    expect(rejection.userMessage).toBe('考点不存在或越权')
  })

  it('still routes 401 through the session-expiry path', async () => {
    uni.setStorageSync('access_token', 'stale-token')
    replyStatus(401, { detail: 'expired' })

    const rejection = await request({ url: '/users/me' }).catch((err) => err)

    expect(rejection.kind).toBe('unauthorized')
    expect(uni.getStorageSync('access_token')).toBe('')
  })

  it('omits the platform placeholder errno from the developer-facing summary', () => {
    expect(classifyTransportFailure('request:fail timeout', 15000).kind).toBe('timeout')
    const failure = new RequestError('network', '/x', 'GET', '网络连接失败', { errno: '<Undefined>' })
    expect(failure.describe()).not.toContain('<Undefined>')
  })

  it('reports upload failures with the same structured contract', async () => {
    uniGlobal.uni.uploadFile = (options: any) => options.fail({ errMsg: 'uploadFile:fail timeout' })

    const rejection = await uploadFile('/tmp/a.pdf').catch((err) => err)

    expect(rejection).toBeInstanceOf(RequestError)
    expect(rejection.kind).toBe('timeout')
    expect(rejection.url).toContain('/materials/upload')
  })
})
