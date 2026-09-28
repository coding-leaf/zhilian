import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { UserProfile, UpdateUserProfilePayload } from '@/types'
import { apiLoginByWechat, apiGetUserProfile, apiUpdateUserProfile } from '@/api'
import { RequestError } from '@/utils/requestError'

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
 *
 * Args:
 *   err: 登录过程中捕获到的异常。
 *
 * Returns:
 *   LoginFailure: 失败原因与可直接展示的文案。
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

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(uni.getStorageSync('access_token') || '')
  const user = ref<UserProfile | null>(null)

  const isLoggedIn = () => !!token.value

  const setToken = (newToken: string) => {
    token.value = newToken
    uni.setStorageSync('access_token', newToken)
  }

  const clearAuth = () => {
    token.value = ''
    user.value = null
    uni.removeStorageSync('access_token')
  }

  const loginWithWechat = async (): Promise<LoginOutcome> => {
    return new Promise((resolve) => {
      // #ifdef MP-WEIXIN
      uni.login({
        provider: 'weixin',
        success: async (res) => {
          if (res.code) {
            try {
              const resData = await apiLoginByWechat(res.code)
              setToken(resData.access_token)
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
      setToken('mock_token_dev')
      user.value = { id: 'dev_user_1', nickname: '学术探索者' }
      resolve({ ok: true })
      // #endif
    })
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

  return {
    token,
    user,
    isLoggedIn,
    setToken,
    clearAuth,
    loginWithWechat,
    fetchProfile,
    updateProfile,
  }
})
