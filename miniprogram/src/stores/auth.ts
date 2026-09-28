import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { UserProfile, UpdateUserProfilePayload } from '@/types'
import { apiLoginByWechat, apiGetUserProfile, apiUpdateUserProfile } from '@/api'

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

  const loginWithWechat = async (): Promise<boolean> => {
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
              resolve(true)
            } catch (err) {
              console.error('Login error:', err)
              resolve(false)
            }
          } else {
            resolve(false)
          }
        },
        fail: () => resolve(false),
      })
      // #endif
      // #ifndef MP-WEIXIN
      setToken('mock_token_dev')
      user.value = { id: 'dev_user_1', nickname: '学术探索者' }
      resolve(true)
      // #endif
    })
  }

  const fetchProfile = async () => {
    if (!token.value) return
    try {
      user.value = await apiGetUserProfile()
    } catch {
      // 静默失败或等待统一拦截
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
