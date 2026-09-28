import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    apiLoginByWechat: vi.fn(),
    apiGetUserProfile: vi.fn(),
    apiUpdateUserProfile: vi.fn(),
  },
}))

vi.mock('@/api', () => apiMock)

import { classifyLoginFailure, useAuthStore } from '@/stores/auth'
import { RequestError } from '@/utils/requestError'

/**
 * `stores/auth.ts` 的 `loginWithWechat` 用 `#ifdef MP-WEIXIN` 条件编译，
 * 而 `vitest.config.ts` 不加载 uni 插件 —— 条件编译注释在测试里是普通注释，
 * 两条分支都会执行。非 MP 分支同步 `resolve`，永远先于 `uni.login` 的异步回调完成，
 * 因此**登录失败路径在单测里不可达**。失败分类必须由纯函数承载，本文件直接测它。
 */
describe('login failure classification', () => {
  it('maps a transport timeout to the timeout reason and says how long it waited', () => {
    const failure = classifyLoginFailure(
      new RequestError('timeout', 'http://localhost:8000/api/v1/auth/login', 'POST', '请求超时（15秒），请检查后端是否可达'),
    )

    expect(failure.reason).toBe('timeout')
    expect(failure.message).toContain('超时')
    expect(failure.message).toContain('15')
  })

  it('maps a plain transport failure to the network reason', () => {
    const failure = classifyLoginFailure(
      new RequestError('network', 'http://localhost:8000/api/v1/auth/login', 'POST', '网络连接失败，请检查网络后重试'),
    )

    expect(failure.reason).toBe('network')
    expect(failure.message).not.toContain('超时')
  })

  it('maps an HTTP rejection to the http reason and keeps the backend detail', () => {
    const failure = classifyLoginFailure(
      new RequestError('http', 'http://localhost:8000/api/v1/auth/login', 'POST', '微信授权登录失败 (错误码 40029)', {
        statusCode: 400,
        detail: '微信授权登录失败 (错误码 40029)',
      }),
    )

    expect(failure.reason).toBe('http')
    expect(failure.message).toBe('微信授权登录失败 (错误码 40029)')
  })

  it('maps a 401 to the http reason rather than inventing a fourth user-facing category', () => {
    const failure = classifyLoginFailure(
      new RequestError('unauthorized', 'http://localhost:8000/api/v1/auth/login', 'POST', '登录已过期，请重新登录', {
        statusCode: 401,
      }),
    )

    expect(failure.reason).toBe('http')
  })

  it('never yields an empty message for an unrecognised throw', () => {
    const failure = classifyLoginFailure(new Error('boom'))

    expect(failure.reason).toBe('network')
    expect(failure.message.length).toBeGreaterThan(0)
  })

  it('never yields an empty message even for a non-Error throw', () => {
    const failure = classifyLoginFailure(undefined)

    expect(failure.message.length).toBeGreaterThan(0)
  })
})

describe('auth store: login failures reach the caller', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    apiMock.apiLoginByWechat.mockReset()
    apiMock.apiGetUserProfile.mockReset()
    // vitest 不处理 #ifdef，MP 分支也会执行；给默认实现以免它抛出无关的 TypeError 噪音。
    apiMock.apiLoginByWechat.mockResolvedValue({ access_token: 't', refresh_token: 'r', token_type: 'Bearer' })
    apiMock.apiGetUserProfile.mockResolvedValue({ id: 'u-1', nickname: '测试用户' })
    ;(globalThis as any).uni.login = (options: any) => options.success({ code: 'dev_test_code' })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reports the dev-platform login as a discriminated success, not a bare boolean', async () => {
    const store = useAuthStore()

    const outcome = await store.loginWithWechat()

    expect(outcome).toEqual({ ok: true })
  })

  it('records a failed profile fetch instead of swallowing it', async () => {
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
    const store = useAuthStore()
    store.setToken('valid-token')
    apiMock.apiGetUserProfile.mockRejectedValue(
      new RequestError('timeout', 'http://localhost:8000/api/v1/users/me', 'GET', '请求超时（15秒），请检查后端是否可达'),
    )

    await expect(store.fetchProfile()).resolves.toBeUndefined()

    expect(store.user).toBeNull()
    expect(logged).toHaveBeenCalled()
    const output = logged.mock.calls.flat().map((part) => String(part)).join(' ')
    expect(output).toContain('/users/me')
    expect(output).toContain('timeout')
  })

  it('does not pretend a failed profile fetch succeeded by inventing a user', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const store = useAuthStore()
    store.setToken('valid-token')
    apiMock.apiGetUserProfile.mockRejectedValue(new Error('boom'))

    await store.fetchProfile()

    expect(store.user).toBeNull()
    expect(store.token).toBe('valid-token')
  })
})
