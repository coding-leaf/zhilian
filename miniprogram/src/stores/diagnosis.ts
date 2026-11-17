import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { DiagnosisReport } from '@/types'
import { apiGetPracticeSession, apiTriggerDiagnosis } from '@/api'
import { createPoller, type PollerHandle } from '@/utils/poller'

export const useDiagnosisStore = defineStore('diagnosis', () => {
  const currentReport = ref<DiagnosisReport | null>(null)
  const isLoading = ref<boolean>(false)
  /** 全卷尚未判完，正式诊断还不存在（结果页显示“判题中”）。 */
  const isPending = ref<boolean>(false)

  /**
   * 正式诊断只在全卷真正判完（completed_at 落库 + status=completed）后请求。
   * 未判完时返回 null，由结果页展示逐题判题进度，不展示伪造的零分报告。
   */
  const loadReport = async (
    practiceId: string,
    maxAttempts = 15,
    intervalMs = 2000,
    poller: PollerHandle = createPoller(),
  ): Promise<DiagnosisReport | null> => {
    isLoading.value = true
    isPending.value = false
    try {
      const result = await poller.run(() => apiGetPracticeSession(practiceId), {
        maxAttempts,
        intervalMs,
        isDone: (session) => Boolean(session.completed_at) && session.status === 'completed',
        onAttempt: () => {
          isPending.value = true
        },
      })
      if (result.status === 'completed') {
        // 后端不会在判题完成时自动生成报告；确认全卷判完后按幂等语义触发生成/取回
        const report = await apiTriggerDiagnosis(practiceId)
        currentReport.value = report
        isPending.value = false
        return report
      }
      return null
    } finally {
      isLoading.value = false
    }
  }

  const reset = () => {
    currentReport.value = null
    isPending.value = false
  }

  return {
    currentReport,
    isLoading,
    isPending,
    loadReport,
    reset,
  }
})
