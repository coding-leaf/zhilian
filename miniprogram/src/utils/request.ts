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
}

export function request<T = any>(options: RequestOptions): Promise<T> {
  const token = uni.getStorageSync('access_token')
  const header: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.header,
  }

  const fullUrl = options.url.startsWith('http') ? options.url : `${API_BASE_URL}${options.url}`

  return new Promise((resolve, reject) => {
    uni.request({
      url: fullUrl,
      method: (options.method || 'GET') as any,
      data: options.data,
      header,
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
          handleUnauthorized()
          reject(new Error('Unauthorized'))
        } else {
          const errData = res.data as any
          const errMsg = errData?.detail || errData?.message || `请求失败 (${res.statusCode})`
          uni.showToast({
            title: errMsg,
            icon: 'none',
          })
          reject(new Error(errMsg))
        }
      },
      fail: (err) => {
        uni.showToast({
          title: '网络连接异常，请重试',
          icon: 'none',
        })
        reject(err)
      },
    })
  })
}

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

  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: `${API_BASE_URL}${endpoint}`,
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
          handleUnauthorized()
          reject(new Error('Unauthorized'))
        } else {
          uni.showToast({
            title: '上传失败，请重试',
            icon: 'none',
          })
          reject(new Error(`Upload failed with status ${res.statusCode}`))
        }
      },
      fail: (err) => {
        uni.showToast({
          title: '上传网络失败',
          icon: 'none',
        })
        reject(err)
      },
    })
  })
}
