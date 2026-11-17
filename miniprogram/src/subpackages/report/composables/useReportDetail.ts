import { computed, ref } from 'vue'
import { useDiagnosisStore } from '@/stores/diagnosis'
import { usePracticeStore } from '@/stores/practice'
import { needsGradingRetry, summarizeProgress } from '@/api/adapters/practice'
import { safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import { createPoller } from '@/utils/poller'
import type { AttemptResult, DiagnosisReport } from '@/types'
import {
  buildWeakPointViews,
  collectWrongKnowledgePointIds,
  resolveSessionScope,
  type GradingMode,
} from '../utils/reportView'

/** 报告详情页编排：作答加载、可取消判题轮询、复查/自评提交与错题再生题。 */
export function useReportDetail() {
  const diagnosisStore = useDiagnosisStore()
  const practiceStore = usePracticeStore()
  const gradingPoller = createPoller()

  const practiceId = ref('')
  const report = ref<DiagnosisReport | null>(null)
  const loadError = ref('')
  const isPolling = ref(false)
  const isRegenerating = ref(false)
  const isRetryingGrading = ref(false)

  const showModal = ref(false)
  const modalMode = ref<GradingMode>('regrade')
  const activeResult = ref<AttemptResult | null>(null)
  const isSubmittingGrading = ref(false)

  const session = computed(() => practiceStore.currentSession)
  const results = computed(() => practiceStore.attemptResults)
  const progress = computed(() => summarizeProgress(session.value))
  const fullyGraded = computed(() => progress.value.fullyGraded)
  const gradedCount = computed(() => progress.value.graded)
  const needsRetry = computed(() => needsGradingRetry(session.value) && !fullyGraded.value)
  const totalScore = computed(() => session.value?.total_score ?? null)
  const maxScore = computed(() => session.value?.max_score ?? null)
  const pendingCount = computed(
    () => report.value?.pending_regrade_count ?? progress.value.pendingRegrade,
  )
  const unansweredCount = computed(
    () => report.value?.unanswered_count ?? progress.value.unanswered,
  )
  const wrongCount = computed(() => {
    if (report.value && fullyGraded.value) return report.value.wrong_count
    return results.value.filter((item) => item.isCorrect === false).length
  })
  const weakPoints = computed(() => buildWeakPointViews(report.value))
  const wrongKnowledgePointIds = computed(() =>
    collectWrongKnowledgePointIds(report.value, results.value),
  )
  const regenerateScope = computed(() => resolveSessionScope(session.value))
  const canRegenerate = computed(() =>
    Boolean(regenerateScope.value.folderId || regenerateScope.value.materialId),
  )

  const loadReportIfGraded = async () => {
    if (!fullyGraded.value || gradingPoller.isDisposed) return
    report.value = await diagnosisStore.loadReport(practiceId.value, 1, 0, gradingPoller)
  }

  const bootstrap = async () => {
    if (!practiceId.value) return
    loadError.value = ''
    try {
      await withBlockingLoading('加载作答结果...', async () => {
        await practiceStore.refreshSession(practiceId.value)
        await loadReportIfGraded()
      })
    } catch (error: any) {
      loadError.value = error?.message || '加载失败，请稍后重试'
    }
  }

  const pollGrading = async () => {
    if (!practiceId.value || isPolling.value || gradingPoller.isDisposed) return
    isPolling.value = true
    try {
      const outcome = await gradingPoller.run(
        () => practiceStore.refreshSession(practiceId.value),
        {
          maxAttempts: 20,
          intervalMs: 2500,
          isDone: () => fullyGraded.value || needsRetry.value,
        },
      )
      if (outcome.status !== 'stopped') {
        await loadReportIfGraded()
      }
    } finally {
      isPolling.value = false
    }
  }

  const retryGrading = async () => {
    if (!practiceId.value || isRetryingGrading.value) return
    isRetryingGrading.value = true
    try {
      await practiceStore.retryGrading(practiceId.value)
      safeShowToast('已重新调度判题')
      await pollGrading()
      if (!fullyGraded.value && !needsRetry.value && !gradingPoller.isDisposed) {
        safeShowToast('判题仍在进行，可稍后从学情页查看')
      }
    } catch (error: any) {
      safeShowToast(error?.message || '重试失败，请稍后再试')
    } finally {
      isRetryingGrading.value = false
    }
  }

  const openGrading = (mode: GradingMode, result: AttemptResult) => {
    modalMode.value = mode
    activeResult.value = result
    showModal.value = true
  }

  const submitGrading = async (payload: { reason: string; score: number }) => {
    const result = activeResult.value
    if (!result) return
    isSubmittingGrading.value = true
    try {
      if (modalMode.value === 'regrade') {
        const res = await practiceStore.requestRegrade(result.attemptItemId, payload.reason)
        safeShowToast(res.message || '复查已完成', 'success')
      } else {
        await practiceStore.selfEvaluate(result.attemptItemId, payload.score, payload.reason)
        safeShowToast('自评已生效', 'success')
      }
      showModal.value = false
      await loadReportIfGraded()
    } catch (error: any) {
      safeShowToast(error?.message || '提交失败，请重试')
    } finally {
      isSubmittingGrading.value = false
    }
  }

  const startAdaptivePractice = async () => {
    const scope = regenerateScope.value
    if (!scope || !wrongKnowledgePointIds.value.length) {
      safeShowToast('暂无可用再生范围')
      return
    }
    isRegenerating.value = true
    try {
      const { session: nextSession, coverage } = await withBlockingLoading('生成中...', () =>
        practiceStore.regenerateFromWrongPoints(wrongKnowledgePointIds.value, scope),
      )
      if (coverage.missing.length > 0) {
        safeShowToast(`仍有 ${coverage.missing.length} 个考点未覆盖`)
      }
      uni.redirectTo({
        url: `/subpackages/practice/pages/session/index?practice_id=${nextSession.id}`,
        fail: () => safeShowToast('打开练习失败，请重试'),
      })
    } catch (error: any) {
      safeShowToast(error?.message || '生成失败')
    } finally {
      isRegenerating.value = false
    }
  }

  const dispose = () => {
    gradingPoller.dispose()
  }

  return {
    practiceId,
    report,
    loadError,
    isPolling,
    isRegenerating,
    isRetryingGrading,
    showModal,
    modalMode,
    activeResult,
    isSubmittingGrading,
    results,
    progress,
    fullyGraded,
    gradedCount,
    needsRetry,
    totalScore,
    maxScore,
    pendingCount,
    unansweredCount,
    wrongCount,
    weakPoints,
    wrongKnowledgePointIds,
    canRegenerate,
    bootstrap,
    pollGrading,
    retryGrading,
    openGrading,
    submitGrading,
    startAdaptivePractice,
    dispose,
  }
}
