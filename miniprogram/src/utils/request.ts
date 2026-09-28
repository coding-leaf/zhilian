import {
  DEFAULT_REQUEST_TIMEOUT_MS,
  RequestError,
  classifyTransportFailure,
} from './requestError'

export const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'

function handleUnauthorized(): void {
  uni.removeStorageSync('access_token')
  void import('@/stores/auth').then(({ useAuthStore }) => {
    const auth = useAuthStore()
    auth.clearAuth()
  })
  uni.showToast({ title: '登录已过期，请重新登录', icon: 'none' })
  uni.reLaunch({
    url: '/pages/auth/login',
    fail: () => uni.showToast({ title: '请手动打开登录页', icon: 'none' }),
  })
}

export interface RequestOptions {
  url: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS'
  data?: any
  header?: Record<string, string>
  /** 覆盖默认超时（毫秒）。同步调用大模型的接口应传 `LONG_REQUEST_TIMEOUT_MS`。 */
  timeout?: number
}

/** 失败时的统一收尾：把结构化细节交给 console，把短文案交给 toast。 */
function reportFailure(error: RequestError, toastTitle: string): void {
  console.error(`[request] ${error.describe()}`)
  uni.showToast({ title: toastTitle, icon: 'none' })
}

export function request<T = any>(options: RequestOptions): Promise<T> {
  const token = uni.getStorageSync('access_token')
  const header: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.header,
  }

  const fullUrl = options.url.startsWith('http') ? options.url : `${API_BASE_URL}${options.url}`
  const method = options.method || 'GET'
  const timeout = options.timeout ?? DEFAULT_REQUEST_TIMEOUT_MS

  return new Promise((resolve, reject) => {
    uni.request({
      url: fullUrl,
      method: method as any,
      data: options.data,
      header,
      timeout,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const body = res.data as any
          // 如果后端格式为 { code, message, data } 结构，解构 data；否则直接返回 body
          if (body && typeof body === 'object' && 'data' in body && 'code' in body) {
            resolve(body.data as T)
          } else {
            resolve(body as T)
          }
        } else if (res.statusCode === 401) {
          // handleUnauthorized 已经负责提示与跳转，这里不再重复 toast。
          const error = new RequestError('unauthorized', fullUrl, method, '登录已过期，请重新登录', {
            statusCode: 401,
          })
          console.error(`[request] ${error.describe()}`)
          handleUnauthorized()
          reject(error)
        } else {
          const errData = res.data as any
          const errMsg = errData?.detail || errData?.message || `请求失败 (${res.statusCode})`
          const error = new RequestError('http', fullUrl, method, errMsg, {
            statusCode: res.statusCode,
            detail: errData?.detail || errData?.message,
          })
          reportFailure(error, errMsg)
          reject(error)
        }
      },
      fail: (err) => {
        const { kind, userMessage } = classifyTransportFailure((err as any)?.errMsg, timeout)
        const error = new RequestError(kind, fullUrl, method, userMessage, {
          errMsg: (err as any)?.errMsg,
          errno: (err as any)?.errno,
        })
        reportFailure(error, userMessage)
        reject(error)
      },
    })
  })
}

/**
 * 上传文件。
 *
 * 平台限制：`uni.uploadFile` 没有 `timeout` 参数（超时由 `app.json` 的 `networkTimeout` 决定），
 * 故这里无法像 `request` 那样逐请求收敛超时；但失败信息与其他请求保持同一套结构化契约。
 */
export function uploadFile<T = any>(
  filePath: string,
  name: string = 'file',
  formData?: Record<string, any>,
  endpoint: string = '/materials/upload'
): Promise<T> {
  const token = uni.getStorageSync('access_token')
  const header: Record<string, string> = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  const fullUrl = `${API_BASE_URL}${endpoint}`

  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: fullUrl,
      filePath,
      name,
      formData,
      header,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
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
          const error = new RequestError('unauthorized', fullUrl, 'POST', '登录已过期，请重新登录', {
            statusCode: 401,
          })
          console.error(`[request] ${error.describe()}`)
          handleUnauthorized()
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
          reportFailure(error, error.userMessage)
          reject(error)
        }
      },
      fail: (err) => {
        const { kind, userMessage } = classifyTransportFailure((err as any)?.errMsg)
        const error = new RequestError(kind, fullUrl, 'POST', userMessage, {
          errMsg: (err as any)?.errMsg,
          errno: (err as any)?.errno,
        })
        reportFailure(error, userMessage)
        reject(error)
      },
    })
  })
}
