import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import manifest from '@/manifest.json'
import {
  API_BASE_URL,
  MAX_CONCURRENT_REQUESTS,
  request,
  resetRequestStateForTest,
  uploadFile,
} from '@/utils/request'
import { RequestError } from '@/utils/requestError'
import {
  isBlockingLoadingActive,
  resetLoadingGuardForTest,
  withBlockingLoading,
} from '@/utils/loadingGuard'
import { ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY } from '@/utils/storageKeys'
import { useAuthStore } from '@/stores/auth'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useDiagnosisStore } from '@/stores/diagnosis'
import { useFolderStore } from '@/stores/folder'
import { useMaterialStore } from '@/stores/material'
import { usePracticeStore } from '@/stores/practice'

const uniGlobal = globalThis as any

describe('network resilience: config, silentToast, concurrency, dedup, retry & 401 single-flight', () => {
  const requestMock = vi.fn()

  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    resetRequestStateForTest()
    resetLoadingGuardForTest()
    requestMock.mockReset()
    uniGlobal.uni.request = requestMock
  })

  afterEach(() => {
    resetRequestStateForTest()
    resetLoadingGuardForTest()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('defaults API_BASE_URL to 127.0.0.1 and configures mp-weixin privacy, lazy loading, and 60s networkTimeout in manifest.json', () => {
    expect(API_BASE_URL).toBe('http://127.0.0.1:8000/api/v1')
    const mpWeixin = (manifest as any)['mp-weixin']
    expect(mpWeixin?.__usePrivacyCheck__).toBe(true)
    expect(mpWeixin?.lazyCodeLoading).toBe('requiredComponents')
    expect(mpWeixin?.setting?.enhance).toBe(true)
    expect(mpWeixin?.networkTimeout).toEqual({
      request: 60000,
      uploadFile: 60000,
    })
  })

  it('classifies uploadFile timeout using actual 60s upload timeout budget and omits undefined formData', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const capturedOptions: any[] = []
    uniGlobal.uni.uploadFile = (options: any) => {
      capturedOptions.push(options)
      options.fail({ errMsg: 'uploadFile:fail timeout' })
    }

    const rejection = await uploadFile('/tmp/big.pdf').catch((err) => err)

    expect(rejection).toBeInstanceOf(RequestError)
    expect(rejection.kind).toBe('timeout')
    expect(rejection.userMessage).toContain('60秒')
    expect('formData' in capturedOptions[0]).toBe(false)
  })

  it('never shows toast or dismisses active foreground loading when silentToast=true fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const toastSpy = vi.spyOn(uniGlobal.uni, 'showToast')
    const hideLoadingSpy = vi.spyOn(uniGlobal.uni, 'hideLoading')

    requestMock.mockImplementation((options: any) => {
      options.success({ statusCode: 500, data: { detail: 'backend boom' } })
    })

    await withBlockingLoading('前台加载中...', async () => {
      expect(isBlockingLoadingActive()).toBe(true)
      const err = await request({
        url: '/materials/m-1',
        method: 'GET',
        silentToast: true,
      }).catch((e) => e)
      expect(err).toBeInstanceOf(RequestError)
      // 静默请求失败后，前台 loading 必须保持存活且未触发 toast 或 hideLoading
      expect(isBlockingLoadingActive()).toBe(true)
      expect(toastSpy).not.toHaveBeenCalled()
      expect(hideLoadingSpy).not.toHaveBeenCalled()
    })

    // 仅在 withBlockingLoading 正常退出时关闭一次 loading
    expect(hideLoadingSpy).toHaveBeenCalledTimes(1)
  })

  it('limits concurrent requests to MAX_CONCURRENT_REQUESTS (6) and drains FIFO', async () => {
    let inFlight = 0
    let maxObserved = 0
    const resolvers: Array<() => void> = []

    requestMock.mockImplementation((options: any) => {
      inFlight += 1
      maxObserved = Math.max(maxObserved, inFlight)
      resolvers.push(() => {
        inFlight -= 1
        options.success({ statusCode: 200, data: { url: options.url } })
      })
    })

    const promises = Array.from({ length: 10 }, (_, idx) =>
      request({ url: `/items/${idx}`, method: 'GET' }),
    )

    expect(MAX_CONCURRENT_REQUESTS).toBe(6)
    expect(maxObserved).toBe(6)
    expect(requestMock).toHaveBeenCalledTimes(6)

    // 释放全部请求并推进队列
    while (resolvers.length > 0) {
      const done = resolvers.shift()!
      done()
      await Promise.resolve()
    }

    const results = await Promise.all(promises)
    expect(results).toHaveLength(10)
    expect(maxObserved).toBe(6)
    expect(requestMock).toHaveBeenCalledTimes(10)
  })

  it('deduplicates concurrent in-flight GET requests with normalized query params', async () => {
    const callbacks: Array<(res: any) => void> = []
    requestMock.mockImplementation((options: any) => {
      callbacks.push(options.success)
    })

    const p1 = request({ url: '/materials?status=ready&folder_id=f-1', method: 'GET' })
    const p2 = request({ url: '/materials?folder_id=f-1&status=ready', method: 'GET' })
    const p3 = request({ url: '/materials', method: 'POST', data: { title: 'a' } })
    const p4 = request({ url: '/materials', method: 'POST', data: { title: 'a' } })

    // 两个同义 GET 合并为 1 次底层请求，两个 POST 不合并 -> 共 3 次
    expect(requestMock).toHaveBeenCalledTimes(3)

    callbacks.forEach((cb, i) => cb({ statusCode: 200, data: { seq: i } }))
    const [r1, r2, r3, r4] = await Promise.all([p1, p2, p3, p4])
    expect(r1).toEqual(r2)
    expect(r3).not.toEqual(r4)
  })

  it('retries idempotent GET up to 2 times on 502/503/504/network/timeout and does not retry POST', async () => {
    vi.useFakeTimers()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(Math, 'random').mockReturnValue(0.5)

    let getCalls = 0
    requestMock.mockImplementation((options: any) => {
      if (options.method === 'GET') {
        getCalls += 1
        if (getCalls === 1) {
          options.success({ statusCode: 503, data: { detail: 'upstream unavailable' } })
        } else if (getCalls === 2) {
          options.fail({ errMsg: 'request:fail timeout' })
        } else {
          options.success({ statusCode: 200, data: { ok: true } })
        }
        return
      }
      options.success({ statusCode: 503, data: { detail: 'post unavailable' } })
    })

    const getPromise = request({ url: '/materials', method: 'GET' })
    await vi.runAllTimersAsync()
    await expect(getPromise).resolves.toEqual({ ok: true })
    expect(getCalls).toBe(3)

    const postCallsBefore = requestMock.mock.calls.length
    const postErr = await request({ url: '/materials', method: 'POST' }).catch((e) => e)
    expect(postErr).toBeInstanceOf(RequestError)
    expect(requestMock.mock.calls.length - postCallsBefore).toBe(1)
  })

  it('performs single-flight 401 refresh_token renewal once for concurrent 401s and replays all', async () => {
    uni.setStorageSync(ACCESS_TOKEN_KEY, 'expired-access')
    uni.setStorageSync(REFRESH_TOKEN_KEY, 'valid-refresh')

    let refreshCalls = 0
    const replayedHeaders: string[] = []
    requestMock.mockImplementation((options: any) => {
      if (options.url.endsWith('/auth/refresh')) {
        refreshCalls += 1
        expect(options.data).toEqual({ refresh_token: 'valid-refresh' })
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: {
              access_token: 'fresh-access',
              refresh_token: 'fresh-refresh',
              token_type: 'Bearer',
            },
          })
        }, 5)
        return
      }

      if (options.header?.Authorization === 'Bearer expired-access') {
        setTimeout(() => {
          options.success({ statusCode: 401, data: { detail: 'expired' } })
        }, 0)
        return
      }

      replayedHeaders.push(options.header?.Authorization)
      options.success({ statusCode: 200, data: { ok: options.url } })
    })

    const results = await Promise.all([
      request({ url: '/folders', method: 'GET' }),
      request({ url: '/materials', method: 'GET' }),
      request({ url: '/practices', method: 'GET' }),
      request({ url: '/users/me', method: 'GET' }),
    ])

    expect(refreshCalls).toBe(1)
    expect(results).toHaveLength(4)
    expect(replayedHeaders).toEqual([
      'Bearer fresh-access',
      'Bearer fresh-access',
      'Bearer fresh-access',
      'Bearer fresh-access',
    ])
    expect(uni.getStorageSync(ACCESS_TOKEN_KEY)).toBe('fresh-access')
    expect(uni.getStorageSync(REFRESH_TOKEN_KEY)).toBe('fresh-refresh')
  })

  it('guards handleUnauthorized so concurrent failed 401s only trigger reLaunch and toast once', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const reLaunchSpy = vi.spyOn(uniGlobal.uni, 'reLaunch')
    const toastSpy = vi.spyOn(uniGlobal.uni, 'showToast')

    uni.setStorageSync(ACCESS_TOKEN_KEY, 'dead-access')
    uni.setStorageSync(REFRESH_TOKEN_KEY, 'dead-refresh')

    let refreshCalls = 0
    requestMock.mockImplementation((options: any) => {
      if (options.url.endsWith('/auth/refresh')) {
        refreshCalls += 1
        setTimeout(() => {
          options.success({ statusCode: 401, data: { detail: 'refresh expired' } })
        }, 5)
        return
      }
      setTimeout(() => {
        options.success({ statusCode: 401, data: { detail: 'unauthorized' } })
      }, 0)
    })

    const settled = await Promise.allSettled([
      request({ url: '/a', method: 'GET' }),
      request({ url: '/b', method: 'GET' }),
      request({ url: '/c', method: 'GET' }),
    ])

    expect(settled.every((item) => item.status === 'rejected')).toBe(true)
    expect(refreshCalls).toBe(1)
    expect(reLaunchSpy).toHaveBeenCalledTimes(1)
    // Toast is scheduled after reLaunch so WeChat page teardown does not flash-dismiss it
    expect(toastSpy).toHaveBeenCalledTimes(0)
    await new Promise((resolve) => setTimeout(resolve, 180))
    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ title: '登录已过期，请重新登录', icon: 'none' }),
    )
    expect(uni.getStorageSync(ACCESS_TOKEN_KEY)).toBe('')
    expect(uni.getStorageSync(REFRESH_TOKEN_KEY)).toBe('')
  })

  it('clearAuth resets tokens, stops backgroundTask polling, and clears all domain stores', () => {
    const authStore = useAuthStore()
    const bgStore = useBackgroundTaskStore()
    const materialStore = useMaterialStore()
    const folderStore = useFolderStore()
    const practiceStore = usePracticeStore()
    const diagnosisStore = useDiagnosisStore()

    authStore.setAuth('acc-1', 'ref-1')
    authStore.user = { id: 'u-1', nickname: '测试同学' }
    materialStore.materialList = [{ id: 'm-1', title: '讲义', status: 'ready' } as any]
    materialStore.currentMaterial = { id: 'm-1', title: '讲义', status: 'ready' } as any
    folderStore.folders = [{ id: 'f-1', name: '高数' } as any]
    folderStore.setCurrentFolderId('f-1')
    practiceStore.currentSession = { id: 'p-1', status: 'in_progress', questions: [] } as any
    practiceStore.userAnswers = { 'q-1': 'A' }
    diagnosisStore.currentReport = { id: 'r-1' } as any
    diagnosisStore.masteryOverview = { total_points: 3 } as any

    const bgResetSpy = vi.spyOn(bgStore, 'reset')

    authStore.clearAuth()

    expect(authStore.token).toBe('')
    expect(authStore.refreshToken).toBe('')
    expect(authStore.user).toBeNull()
    expect(uni.getStorageSync(ACCESS_TOKEN_KEY)).toBe('')
    expect(uni.getStorageSync(REFRESH_TOKEN_KEY)).toBe('')
    expect(bgResetSpy).toHaveBeenCalledTimes(1)
    expect(materialStore.materialList).toEqual([])
    expect(materialStore.currentMaterial).toBeNull()
    expect(folderStore.folders).toEqual([])
    expect(folderStore.currentFolderId).toBe('all')
    expect(practiceStore.currentSession).toBeNull()
    expect(practiceStore.userAnswers).toEqual({})
    expect(diagnosisStore.currentReport).toBeNull()
    expect(diagnosisStore.masteryOverview).toBeNull()
  })

  it('does not trigger /auth/refresh when 401 came from a request without an Authorization token', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    uni.setStorageSync(REFRESH_TOKEN_KEY, 'orphan-refresh')

    let refreshCalls = 0
    requestMock.mockImplementation((options: any) => {
      if (options.url.endsWith('/auth/refresh')) {
        refreshCalls += 1
      }
      options.success({ statusCode: 401, data: { detail: 'missing token' } })
    })

    const rejection = await request({ url: '/folders', method: 'GET' }).catch((e) => e)
    expect(rejection).toBeInstanceOf(RequestError)
    expect(rejection.kind).toBe('unauthorized')
    expect(refreshCalls).toBe(0)
  })

  it('replays with newer storage token without calling /auth/refresh when login completes mid-flight', async () => {
    uni.setStorageSync(REFRESH_TOKEN_KEY, 'valid-refresh')

    let refreshCalls = 0
    let folderCalls = 0
    requestMock.mockImplementation((options: any) => {
      if (options.url.endsWith('/auth/refresh')) {
        refreshCalls += 1
        return
      }
      folderCalls += 1
      if (folderCalls === 1 && !options.header?.Authorization) {
        // Simulate concurrent login completing while unauthenticated request was in-flight
        uni.setStorageSync(ACCESS_TOKEN_KEY, 'fresh-login-token')
        options.success({ statusCode: 401, data: { detail: 'missing token' } })
        return
      }
      expect(options.header?.Authorization).toBe('Bearer fresh-login-token')
      options.success({ statusCode: 200, data: { items: [] } })
    })

    const res = await request({ url: '/folders', method: 'GET' })
    expect(res).toEqual({ items: [] })
    expect(refreshCalls).toBe(0)
    expect(uni.getStorageSync(ACCESS_TOKEN_KEY)).toBe('fresh-login-token')
  })
})
