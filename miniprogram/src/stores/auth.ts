import { defineStore, getActivePinia } from 'pinia'
import { ref } from 'vue'
import type { UserProfile, UpdateUserProfilePayload } from '@/types'
import { apiLoginByWechat, apiGetUserProfile, apiUpdateUserProfile, apiUploadAvatar } from '@/api'
import { RequestError } from '@/utils/requestError'
import { ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY } from '@/utils/storageKeys'

/** 登录失败的用户可见原因，覆盖「网络不通 / 后端拒绝 / wx.login 失败」三类。 */
export type LoginFailureReason = 'wechat' | 'timeout' | 'network' | 'http'

export interface LoginFailure {
  reason: LoginFailureReason
  /** 可直接展示给用户的短文案，保证非空。 */
  message: string
}

/** 登录结果。失败时带原因，避免调用方只能拿到一个无法区分的 `false`。 */
export type LoginOutcome = { ok: true } | ({ ok: false } & LoginFailure)

/**
 * 把登录过程中抛出的异常归一为可区分的失败原因。
 *
 * 必须是可独立调用的纯函数：`loginWithWechat` 的失败路径在 vitest 里不可达
 * （`#ifdef` 条件编译在测试环境下不生效，详见 `tests/loginFailure.spec.ts` 顶部说明），
 * 所以判定逻辑只能在这里被测到。
 */
export function classifyLoginFailure(err: unknown): LoginFailure {
  if (err instanceof RequestError) {
    return {
      // 登录场景本身不会出现 401；万一出现也归入 http 一类，不额外造第四个用户可见分类。
      reason: err.kind === 'unauthorized' ? 'http' : err.kind,
      message: err.userMessage || '登录失败，请重试',
    }
  }
  return { reason: 'network', message: '登录失败，请重试' }
}

/**
 * 登出/鉴权失效时同步重置所有已初始化的域 Store，停止后台轮询并消除跨账号数据残留。
 * 通过 Pinia 注册表惰性查找，避免与 `stores/practice.ts` 等形成循环依赖。
 */
function resetRegisteredDomainStores(): void {
  try {
    const pinia = getActivePinia() as { _s?: Map<string, Record<string, any>> } | undefined
    const stores = pinia?._s
    if (!stores) return

    const backgroundTask = stores.get('backgroundTask')
    if (backgroundTask && typeof backgroundTask.reset === 'function') {
      backgroundTask.reset()
    }

    const practice = stores.get('practice')
    if (practice) {
      if (typeof practice.resetState === 'function') {
        practice.resetState()
      } else if (typeof practice.reset === 'function') {
        practice.reset()
      }
    }

    const diagnosis = stores.get('diagnosis')
    if (diagnosis) {
      if (typeof diagnosis.reset === 'function') {
        diagnosis.reset()
      }
      if ('masteryOverview' in diagnosis) {
        diagnosis.masteryOverview = null
      }
    }

    const material = stores.get('material')
    if (material) {
      if (typeof material.reset === 'function') {
        material.reset()
      } else {
        if ('currentMaterial' in material) material.currentMaterial = null
        if ('materialList' in material) material.materialList = []
        if ('isGenerating' in material) material.isGenerating = false
        if ('activeKnowledgePoint' in material) material.activeKnowledgePoint = null
      }
    }

    const folder = stores.get('folder')
    if (folder) {
      if (typeof folder.reset === 'function') {
        folder.reset()
      } else {
        if ('folders' in folder) folder.folders = []
        if ('currentFolderId' in folder) folder.currentFolderId = 'all'
      }
    }
  } catch (err) {
    console.error('[auth] 重置域 Store 失败:', err)
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(uni.getStorageSync(ACCESS_TOKEN_KEY) || '')
  const refreshToken = ref<string>(uni.getStorageSync(REFRESH_TOKEN_KEY) || '')
  const user = ref<UserProfile | null>(null)

  const isLoggedIn = () => !!token.value

  const setToken = (newToken: string) => {
    token.value = newToken
    uni.setStorageSync(ACCESS_TOKEN_KEY, newToken)
  }

  const setAuth = (newAccessToken: string, newRefreshToken?: string) => {
    setToken(newAccessToken)
    if (typeof newRefreshToken === 'string') {
      refreshToken.value = newRefreshToken
      if (newRefreshToken) {
        uni.setStorageSync(REFRESH_TOKEN_KEY, newRefreshToken)
      } else {
        uni.removeStorageSync(REFRESH_TOKEN_KEY)
      }
    }
  }

  let inFlightLoginPromise: Promise<LoginOutcome> | null = null

  const clearAuth = () => {
    token.value = ''
    refreshToken.value = ''
    user.value = null
    uni.removeStorageSync(ACCESS_TOKEN_KEY)
    uni.removeStorageSync(REFRESH_TOKEN_KEY)
    resetRegisteredDomainStores()
  }

  const loginWithWechat = (): Promise<LoginOutcome> => {
    if (inFlightLoginPromise) {
      return inFlightLoginPromise
    }

    inFlightLoginPromise = new Promise<LoginOutcome>((resolve) => {
      // #ifdef MP-WEIXIN
      uni.login({
        provider: 'weixin',
        success: async (res) => {
          if (res.code) {
            try {
              const resData = await apiLoginByWechat(res.code)
              setAuth(resData.access_token, resData.refresh_token)
              await fetchProfile()
              resolve({ ok: true })
            } catch (err) {
              const failure = classifyLoginFailure(err)
              console.error(`Login error (${failure.reason}):`, err)
              resolve({ ok: false, ...failure })
            }
          } else {
            resolve({ ok: false, reason: 'wechat', message: '未取得微信登录凭证，请重试' })
          }
        },
        fail: (err) => {
          console.error('wx.login failed:', err)
          resolve({ ok: false, reason: 'wechat', message: '微信登录失败，请重试' })
        },
      })
      // #endif
      // #ifndef MP-WEIXIN
      setAuth('mock_token_dev', 'mock_refresh_token_dev')
      user.value = { id: 'dev_user_1', nickname: '学术探索者' }
      resolve({ ok: true })
      // #endif
    }).finally(() => {
      inFlightLoginPromise = null
    })

    return inFlightLoginPromise
  }

  const fetchProfile = async () => {
    if (!token.value) return
    try {
      user.value = await apiGetUserProfile()
    } catch (err) {
      // 不阻断登录：资料拉取失败时 user 保持 null，由统一拦截或下次刷新兜底。
      // 但必须留下可定位的痕迹 —— 静默吞错被 quality-guidelines.md 明令禁止。
      const detail = err instanceof RequestError ? err.describe() : String(err)
      console.error(`[auth] 用户资料拉取失败: ${detail}`)
    }
  }

  const updateProfile = async (payload: UpdateUserProfilePayload): Promise<UserProfile> => {
    const updated = await apiUpdateUserProfile(payload)
    user.value = updated
    return updated
  }

  const updateAvatar = async (filePath: string): Promise<UserProfile> => {
    const updated = await apiUploadAvatar(filePath)
    user.value = updated
    return updated
  }

  return {
    token,
    refreshToken,
    user,
    isLoggedIn,
    setToken,
    setAuth,
    clearAuth,
    loginWithWechat,
    fetchProfile,
    updateProfile,
    updateAvatar,
  }
})
