import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { DiagnosisReport } from '@/types'
import { apiGetDiagnosisReport, apiTriggerDiagnosis } from '@/api'

export const useDiagnosisStore = defineStore('diagnosis', () => {
  const currentReport = ref<DiagnosisReport | null>(null)
  const isLoading = ref<boolean>(false)

  // 获取诊断报告（若未生成则触发并轮询）
  const loadReport = async (practiceId: string, maxAttempts = 10): Promise<DiagnosisReport> => {
    isLoading.value = true
    try {
      for (let i = 0; i < maxAttempts; i++) {
        try {
          const report = await apiGetDiagnosisReport(practiceId)
          if (report && report.details && report.details.length > 0) {
            currentReport.value = report
            return report
          }
        } catch {
          // 首次未生成，尝试触发一次
          if (i === 0) {
            await apiTriggerDiagnosis(practiceId).catch(() => {})
          }
        }
        await new Promise((r) => setTimeout(r, 1500))
      }
      throw new Error('学情报告生成中，请下拉刷新')
    } finally {
      isLoading.value = false
    }
  }

  return {
    currentReport,
    isLoading,
    loadReport,
  }
})
