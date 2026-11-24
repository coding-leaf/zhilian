import { getActivePinia } from 'pinia'
import {
  DEFAULT_REQUEST_TIMEOUT_MS,
  UPLOAD_REQUEST_TIMEOUT_MS,
  RequestError,
  classifyTransportFailure,
} from './requestError'
import { dismissBlockingLoading, safeShowToast } from './loadingGuard'
import { ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY } from './storageKeys'

export const API_BASE_URL =
  (import.meta as any).env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1'

/** 全局并发请求上限：微信小程序硬上限 10，预留 4 个槽位给上传、刷新与登录。 */
export const MAX_CONCURRENT_REQUESTS = 6

const MAX_GET_RETRIES = 2
const RETRY_BASE_DELAY_MS = 200
const RETRYABLE_HTTP_STATUSES = new Set([502, 503, 504])
const UNAUTHORIZED_GUARD_MS = 1500

let activeRequests = 0
const waitQueue: Array<() => void> = []

let refreshPromise: Promise<string | null> | null = null
let isHandlingUnauthorized = false
let lastUnauthorizedToken: string | null = null
let unauthorizedGuardTimer: ReturnType<typeof setTimeout> | null = null

interface InFlightGetEntry {
  promise: Promise<any>
  hasNonSilentCaller: boolean
}

const inFlightGetMap = new Map<string, InFlightGetEntry>()

function releaseSlot(): void {
  activeRequests = Math.max(0, activeRequests - 1)
  if (waitQueue.length > 0 && activeRequests < MAX_CONCURRENT_REQUESTS) {
    const next = waitQueue.shift()
    next?.()
  }
}

function runWithSlot<T>(task: () => Promise<T>): Promise<T> {
  if (activeRequests < MAX_CONCURRENT_REQUESTS) {
    activeRequests += 1
    return task().finally(releaseSlot)
  }
  return new Promise<T>((resolve, reject) => {
    waitQueue.push(() => {
      activeRequests += 1
      task().finally(releaseSlot).then(resolve, reject)
    })
  })
}

function isAuthEndpoint(url: string): boolean {
  const path = url.split('?')[0]
  return path.endsWith('/auth/refresh') || path.endsWith('/auth/login')
}

function unwrapResponseBody<T>(body: any): T {
  // 如果后端格式为 { code, message, data } 结构，解构 data；否则直接返回 body
  if (body && typeof body === 'object' && 'data' in body && 'code' in body) {
    return body.data as T
  }
  return body as T
}

function stableSerialize(value: unknown): string {
  if (value === undefined || value === null) return ''
  if (typeof value !== 'object') return String(value)
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(',')}]`
  }
  const record = value as Record<string, unknown>
  const keys = Object.keys(record).sort()
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableSerialize(record[k])}`).join(',')}}`
}

function normalizeUrlForDedup(fullUrl: string): string {
  const queryIdx = fullUrl.indexOf('?')
  if (queryIdx === -1) return fullUrl
  const base = fullUrl.slice(0, queryIdx)
  const rawQuery = fullUrl.slice(queryIdx + 1)
  if (!rawQuery) return base
  const pairs = rawQuery
    .split('&')
    .filter((part) => part.length > 0)
    .sort()
  return pairs.length > 0 ? `${base}?${pairs.join('&')}` : base
}

function buildGetDedupKey(fullUrl: string, data: unknown, token: string): string {
  const normalizedUrl = normalizeUrlForDedup(fullUrl)
  const serializedData = stableSerialize(data)
  return `GET|${token}|${normalizedUrl}|${serializedData}`
}

function computeRetryDelayMs(attempt: number): number {
  const jitter = 0.5 + Math.random()
  return Math.round(RETRY_BASE_DELAY_MS * Math.pow(2, attempt) * jitter)
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function isRetryableGetError(error: RequestError): boolean {
  if (error.kind === 'network' || error.kind === 'timeout') return true
  if (
    error.kind === 'http' &&
    error.statusCode !== undefined &&
    RETRYABLE_HTTP_STATUSES.has(error.statusCode)
  ) {
    return true
  }
  return false
}

let unauthorizedToastTimer: ReturnType<typeof setTimeout> | null = null

function clearUnauthorizedGuard(): void {
  if (unauthorizedGuardTimer !== null) {
    clearTimeout(unauthorizedGuardTimer)
    unauthorizedGuardTimer = null
  }
  if (unauthorizedToastTimer !== null) {
    clearTimeout(unauthorizedToastTimer)
    unauthorizedToastTimer = null
  }
  isHandlingUnauthorized = false
  lastUnauthorizedToken = null
}

function getActiveAuthStore(): {
  clearAuth?: () => void
  setAuth?: (token: string, refreshToken?: string | null) => void
} | null {
  try {
    // 微信小程序 CJS 产物不支持动态 import()，通过 Pinia 活跃注册表同步访问避免循环依赖与编译断裂
    const pinia = getActivePinia() as { _s?: Map<string, unknown> } | undefined
    const store = pinia?._s?.get('auth')
    if (store && typeof store === 'object') {
      return store as {
        clearAuth?: () => void
        setAuth?: (token: string, refreshToken?: string | null) => void
      }
    }
  } catch {
    // Pinia may be inactive in isolated utility tests
  }
  return null
}

function handleUnauthorized(failedToken?: string): void {
  const normalizedFailed = failedToken || ''
  if (isHandlingUnauthorized && (!normalizedFailed || normalizedFailed === lastUnauthorizedToken)) {
    return
  }
  if (unauthorizedGuardTimer !== null) {
    clearTimeout(unauthorizedGuardTimer)
  }
  isHandlingUnauthorized = true
  lastUnauthorizedToken = normalizedFailed || null
  unauthorizedGuardTimer = setTimeout(() => {
    isHandlingUnauthorized = false
    lastUnauthorizedToken = null
    unauthorizedGuardTimer = null
  }, UNAUTHORIZED_GUARD_MS)

  dismissBlockingLoading()
  uni.removeStorageSync(ACCESS_TOKEN_KEY)
  uni.removeStorageSync(REFRESH_TOKEN_KEY)
  try {
    getActiveAuthStore()?.clearAuth?.()
  } catch {
    // Never let store reset error block login redirect
  }
  if (unauthorizedToastTimer !== null) {
    clearTimeout(unauthorizedToastTimer)
    unauthorizedToastTimer = null
  }
  uni.reLaunch({
    url: '/pages/auth/login',
    fail: () => {
      if (unauthorizedToastTimer !== null) {
        clearTimeout(unauthorizedToastTimer)
        unauthorizedToastTimer = null
      }
      safeShowToast('请手动打开登录页')
    },
  })
  // 微信页面跳转销毁会冲掉同步 Toast，延迟 150ms 在目标页稳定后提示
  unauthorizedToastTimer = setTimeout(() => {
    unauthorizedToastTimer = null
    safeShowToast('登录已过期，请重新登录')
  }, 150)
}

function refreshAccessTokenSingleFlight(refreshToken: string): Promise<string | null> {
  if (refreshPromise) return refreshPromise

  const refreshUrl = `${API_BASE_URL}/auth/refresh`
  refreshPromise = new Promise<string | null>((resolve) => {
    uni.request({
      url: refreshUrl,
      method: 'POST',
      data: { refresh_token: refreshToken },
      header: { 'Content-Type': 'application/json' },
      timeout: DEFAULT_REQUEST_TIMEOUT_MS,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const payload = unwrapResponseBody<{
            access_token?: string
            refresh_token?: string
          }>(res.data)
          const nextAccessToken = payload?.access_token
          const nextRefreshToken = payload?.refresh_token
          if (typeof nextAccessToken === 'string' && nextAccessToken.length > 0) {
            uni.setStorageSync(ACCESS_TOKEN_KEY, nextAccessToken)
            if (typeof nextRefreshToken === 'string' && nextRefreshToken.length > 0) {
              uni.setStorageSync(REFRESH_TOKEN_KEY, nextRefreshToken)
            }
            clearUnauthorizedGuard()
            try {
              getActiveAuthStore()?.setAuth?.(nextAccessToken, nextRefreshToken)
            } catch {
              // Pinia may be inactive in isolated utility tests
            }
            resolve(nextAccessToken)
            return
          }
        }
        resolve(null)
      },
      fail: () => {
        resolve(null)
      },
    })
  }).finally(() => {
    refreshPromise = null
  })

  return refreshPromise
}

export interface RequestOptions {
  url: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  data?: any
  header?: Record<string, string>
  /** 覆盖默认超时（毫秒）。同步调用大模型的接口应传 `LONG_REQUEST_TIMEOUT_MS`。 */
  timeout?: number
  /** 静默错误弹窗（设为 true 时不弹 Toast 且不调用 dismissBlockingLoading）。 */
  silentToast?: boolean
  /** 跳过 in-flight GET 去重合并。 */
  skipDedup?: boolean
  /** 覆盖幂等 GET 最大重试次数（默认 GET 为 2，非 GET 为 0）。 */
  retries?: number
}

/** 失败时的统一收尾：把结构化细节交给 console，按需把短文案交给 toast。 */
function reportFailure(error: RequestError, toastTitle: string, silentToast = false): void {
  console.error(`[request] ${error.describe()}`)
  if (silentToast) return
  dismissBlockingLoading()
  uni.showToast({ title: toastTitle, icon: 'none' })
}

type TransportResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: RequestError; isUnauthorized?: boolean }

function dispatchSingleTransport<T>(
  fullUrl: string,
  method: NonNullable<RequestOptions['method']>,
  data: any,
  header: Record<string, string>,
  timeout: number,
  onSyncSuccess?: () => void,
): Promise<TransportResult<T>> {
  return runWithSlot<TransportResult<T>>(
    () =>
      new Promise((resolve) => {
        uni.request({
          url: fullUrl,
          method,
          data,
          header,
          timeout,
          success: (res) => {
            if (res.statusCode >= 200 && res.statusCode < 300) {
              clearUnauthorizedGuard()
              onSyncSuccess?.()
              resolve({ ok: true, data: unwrapResponseBody<T>(res.data) })
            } else if (res.statusCode === 401) {
              const error = new RequestError('unauthorized', fullUrl, method, '登录已过期，请重新登录', {
                statusCode: 401,
              })
              resolve({ ok: false, error, isUnauthorized: true })
            } else {
              const errData = res.data as any
              const errMsg = errData?.detail || errData?.message || `请求失败 (${res.statusCode})`
              const error = new RequestError('http', fullUrl, method, errMsg, {
                statusCode: res.statusCode,
                detail: errData?.detail || errData?.message,
              })
              resolve({ ok: false, error })
            }
          },
          fail: (err) => {
            const { kind, userMessage } = classifyTransportFailure((err as any)?.errMsg, timeout)
            const error = new RequestError(kind, fullUrl, method, userMessage, {
              errMsg: (err as any)?.errMsg,
              errno: (err as any)?.errno,
            })
            resolve({ ok: false, error })
          },
        })
      }),
  )
}

function buildRequestHeaders(
  token: string,
  extraHeader?: Record<string, string>,
): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extraHeader,
  }
}

function executeRequest<T>(
  options: RequestOptions,
  fullUrl: string,
  method: NonNullable<RequestOptions['method']>,
  timeout: number,
  isSilent: () => boolean,
  onSyncSuccess?: () => void,
): Promise<T> {
  const maxRetries =
    method === 'GET' ? Math.max(0, options.retries ?? MAX_GET_RETRIES) : 0
  let hasRetriedAfterRefresh = false

  const attemptOnce = (attempt: number, overrideToken?: string): Promise<T> => {
    const token =
      overrideToken !== undefined
        ? overrideToken
        : String(uni.getStorageSync(ACCESS_TOKEN_KEY) || '')
    const header = buildRequestHeaders(token, options.header)

    return dispatchSingleTransport<T>(
      fullUrl,
      method,
      options.data,
      header,
      timeout,
      onSyncSuccess,
    ).then(async (result) => {
      if (result.ok) {
        return result.data
      }

      if (result.isUnauthorized) {
        if (!isAuthEndpoint(fullUrl) && !hasRetriedAfterRefresh) {
          const storedRefresh = String(uni.getStorageSync(REFRESH_TOKEN_KEY) || '')
          if (storedRefresh) {
            const nextToken = await refreshAccessTokenSingleFlight(storedRefresh)
            if (nextToken) {
              hasRetriedAfterRefresh = true
              return attemptOnce(0, nextToken)
            }
          }
        }
        console.error(`[request] ${result.error.describe()}`)
        if (!isAuthEndpoint(fullUrl)) {
          handleUnauthorized(token)
        }
        throw result.error
      }

      if (attempt < maxRetries && isRetryableGetError(result.error)) {
        await sleep(computeRetryDelayMs(attempt))
        return attemptOnce(attempt + 1, overrideToken)
      }

      reportFailure(result.error, result.error.userMessage, isSilent())
      throw result.error
    })
  }

  return attemptOnce(0)
}

export function request<T = any>(options: RequestOptions): Promise<T> {
  const fullUrl = options.url.startsWith('http') ? options.url : `${API_BASE_URL}${options.url}`
  const method = (options.method || 'GET').toUpperCase() as NonNullable<RequestOptions['method']>
  const timeout = options.timeout ?? DEFAULT_REQUEST_TIMEOUT_MS

  if (method === 'GET' && !options.skipDedup) {
    const token = String(uni.getStorageSync(ACCESS_TOKEN_KEY) || '')
    const dedupKey = buildGetDedupKey(fullUrl, options.data, token)
    const existing = inFlightGetMap.get(dedupKey)
    if (existing) {
      if (!options.silentToast) {
        existing.hasNonSilentCaller = true
      }
      return existing.promise as Promise<T>
    }

    const entry: InFlightGetEntry = {
      promise: Promise.resolve(),
      hasNonSilentCaller: !options.silentToast,
    }
    const cleanup = () => {
      if (inFlightGetMap.get(dedupKey) === entry) {
        inFlightGetMap.delete(dedupKey)
      }
    }
    inFlightGetMap.set(dedupKey, entry)
    entry.promise = executeRequest<T>(
      options,
      fullUrl,
      method,
      timeout,
      () => !entry.hasNonSilentCaller,
      cleanup,
    ).finally(cleanup)
    return entry.promise as Promise<T>
  }

  return executeRequest<T>(
    options,
    fullUrl,
    method,
    timeout,
    () => Boolean(options.silentToast),
  )
}

/**
 * 上传文件。
 *
 * 平台限制：`uni.uploadFile` 没有 `timeout` 参数（超时由 `manifest.json` 的 `networkTimeout.uploadFile` 决定），
 * 失败分类显式传入 `UPLOAD_REQUEST_TIMEOUT_MS`（120s），与平台配置保持一致。
 */
export function uploadFile<T = any>(
  filePath: string,
  name: string = 'file',
  formData?: Record<string, any>,
  endpoint: string = '/materials/upload',
  options?: { silentToast?: boolean },
): Promise<T> {
  const fullUrl = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`
  let hasRetriedAfterRefresh = false

  const dispatchUpload = (overrideToken?: string): Promise<T> => {
    const token =
      overrideToken !== undefined
        ? overrideToken
        : String(uni.getStorageSync(ACCESS_TOKEN_KEY) || '')
    const header: Record<string, string> = {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    }

    return new Promise<T>((resolve, reject) => {
      const sanitizedFormData =
        formData && typeof formData === 'object'
          ? Object.fromEntries(Object.entries(formData).filter(([, value]) => value !== undefined))
          : undefined
      const uploadOptions: UniApp.UploadFileOption = {
        url: fullUrl,
        filePath,
        name,
        header,
        ...(sanitizedFormData && Object.keys(sanitizedFormData).length > 0
          ? { formData: sanitizedFormData }
          : {}),
        success: async (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            clearUnauthorizedGuard()
            try {
              const body = JSON.parse(res.data)
              if (body && typeof body === 'object' && 'data' in body) {
                resolve(body.data as T)
              } else {
                resolve(body as T)
              }
            } catch {
              resolve(res.data as any)
            }
          } else if (res.statusCode === 401) {
            if (!hasRetriedAfterRefresh) {
              const storedRefresh = String(uni.getStorageSync(REFRESH_TOKEN_KEY) || '')
              if (storedRefresh) {
                const nextToken = await refreshAccessTokenSingleFlight(storedRefresh)
                if (nextToken) {
                  hasRetriedAfterRefresh = true
                  dispatchUpload(nextToken).then(resolve, reject)
                  return
                }
              }
            }
            const error = new RequestError('unauthorized', fullUrl, 'POST', '登录已过期，请重新登录', {
              statusCode: 401,
            })
            console.error(`[request] ${error.describe()}`)
            handleUnauthorized(token)
            reject(error)
          } else {
            let detail: string | undefined
            try {
              const body = JSON.parse(res.data)
              detail = body?.detail || body?.message
            } catch {
              detail = undefined
            }
            const error = new RequestError('http', fullUrl, 'POST', detail || '上传失败，请重试', {
              statusCode: res.statusCode,
              detail,
            })
            reportFailure(error, error.userMessage, Boolean(options?.silentToast))
            reject(error)
          }
        },
        fail: (err) => {
          const { kind, userMessage } = classifyTransportFailure(
            (err as any)?.errMsg,
            UPLOAD_REQUEST_TIMEOUT_MS,
          )
          const error = new RequestError(kind, fullUrl, 'POST', userMessage, {
            errMsg: (err as any)?.errMsg,
            errno: (err as any)?.errno,
          })
          reportFailure(error, userMessage, Boolean(options?.silentToast))
          reject(error)
        },
      }
      uni.uploadFile(uploadOptions)
    })
  }

  return dispatchUpload()
}

/** 仅用于测试重置并发调度、去重缓存、刷新单飞与 401 防重锁状态。 */
export function resetRequestStateForTest(): void {
  activeRequests = 0
  waitQueue.length = 0
  refreshPromise = null
  inFlightGetMap.clear()
  clearUnauthorizedGuard()
}
