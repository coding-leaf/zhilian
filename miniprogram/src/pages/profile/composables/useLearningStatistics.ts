import { onScopeDispose, ref, watch } from 'vue'
import { apiGetMaterialStatistics, apiListFolders } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { LearningStatisticsState } from '@/types'

/** 个人页统计：整组成功才展示数字，账号变化立即清空并使旧请求失效。 */
export function useLearningStatistics() {
  const authStore = useAuthStore()
  const state = ref<LearningStatisticsState>({
    status: authStore.isLoggedIn() ? 'loading' : 'logged-out',
  })
  let generation = 0
  let inFlight: Promise<void> | null = null

  function refresh(): Promise<void> {
    const token = authStore.token
    if (!token) {
      state.value = { status: 'logged-out' }
      return Promise.resolve()
    }
    if (inFlight) return inFlight

    const requestGeneration = ++generation
    const isCurrent = () => generation === requestGeneration && authStore.token === token
    state.value = { status: 'loading' }

    const request = (async () => {
      try {
        // /folders 会清理逾期归档课程；之后读取资料统计，避免跨清理前后取数。
        const folders = await apiListFolders()
        if (!isCurrent()) return
        const materials = await apiGetMaterialStatistics()
        if (!isCurrent()) return
        state.value = { status: 'ready', course_count: folders.items.length, ...materials }
      } catch {
        // 网络层负责 toast/诊断；此处保留可见且可重试的整卡失败状态。
        if (isCurrent()) state.value = { status: 'error' }
      } finally {
        if (isCurrent()) inFlight = null
      }
    })()
    inFlight = request
    return request
  }

  watch(() => authStore.token, () => {
    generation++
    inFlight = null
    state.value = { status: authStore.isLoggedIn() ? 'loading' : 'logged-out' }
    if (authStore.isLoggedIn()) void refresh()
  }, { flush: 'sync' })

  onScopeDispose(() => {
    generation++
    inFlight = null
  })

  return { state, refresh }
}
