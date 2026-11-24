import { computed, ref } from 'vue'
import { isQuestionJobActive, useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useDiagnosisStore } from '@/stores/diagnosis'
import { usePracticeStore } from '@/stores/practice'
import { needsGradingRetry, summarizeProgress } from '@/api/adapters/practice'
import { safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import { createPoller } from '@/utils/poller'
import { startWrongRegenerateJob } from '@/utils/questionGeneration'
import { RequestError } from '@/utils/requestError'
import type { AttemptResult, DiagnosisReport } from '@/types'
import {
  buildWeakPointViews,
  collectWrongKnowledgePointIds,
  resolveSessionScope,
  type GradingMode,
} from '../utils/reportView'

const formatErrorMessage = (error: unknown, fallback: string): string => {
  if (error instanceof RequestError) return error.userMessage
  if (
    error &&
    typeof error === 'object' &&
    'message' in error &&
    typeof (error as { message?: unknown }).message === 'string'
  ) {
    return (error as { message: string }).message || fallback
  }
  return fallback
}

/** 报告详情页编排：作答加载、可取消判题轮询、复查/自评提交与错题再生题。 */
export function useReportDetail() {
  const backgroundTaskStore = useBackgroundTaskStore()
  const diagnosisStore = useDiagnosisStore()
  const practiceStore = usePracticeStore()
  const gradingPoller = createPoller()
  const reportPoller = createPoller()

  const practiceId = ref('')
  const report = ref<DiagnosisReport | null>(null)
  const loadError = ref('')
  const isPolling = ref(false)
  const isDispatchingRegenerate = ref(false)
  const isRetryingGrading = ref(false)
  const isRegenerating = computed(
    () =>
      isDispatchingRegenerate.value ||
      Array.from(backgroundTaskStore.questionJobs.values()).some(
        (job) =>
          isQuestionJobActive(job) &&
          job.source_type === 'wrong_record' &&
          (!practiceId.value || job.source_practice_id === practiceId.value),
      ),
  )

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
    if (!fullyGraded.value || reportPoller.isDisposed) return
    report.value = await diagnosisStore.loadReport(practiceId.value, 1, 0, reportPoller)
  }

  const bootstrap = async () => {
    if (!practiceId.value) return
    loadError.value = ''
    try {
      await withBlockingLoading('加载作答结果...', async () => {
        await practiceStore.refreshSession(practiceId.value)
        await loadReportIfGraded()
      })
    } catch (error: unknown) {
      loadError.value = formatErrorMessage(error, '加载失败，请稍后重试')
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
    } catch (error: unknown) {
      safeShowToast(formatErrorMessage(error, '重试失败，请稍后再试'))
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
        safeShowToast(res.message || '复查已完成')
      } else {
        await practiceStore.selfEvaluate(result.attemptItemId, payload.score, payload.reason)
        safeShowToast('自评已生效', 'success')
      }
      showModal.value = false
      await loadReportIfGraded()
    } catch (error: unknown) {
      safeShowToast(formatErrorMessage(error, '提交失败，请重试'))
    } finally {
      isSubmittingGrading.value = false
    }
  }

  const startAdaptivePractice = async () => {
    if (isRegenerating.value) return
    const scope = regenerateScope.value
    if (!scope || !wrongKnowledgePointIds.value.length) {
      safeShowToast('暂无可用再生范围')
      return
    }
    isDispatchingRegenerate.value = true
    try {
      await startWrongRegenerateJob({
        knowledgePointIds: wrongKnowledgePointIds.value,
        scope,
        sourcePracticeId: practiceId.value || undefined,
        practiceTitle: '错题巩固练习',
      })
      safeShowToast('已在后台生成错题巩固卷，完成后顶部提醒')
    } catch (error: unknown) {
      safeShowToast(formatErrorMessage(error, '生成失败'))
    } finally {
      isDispatchingRegenerate.value = false
    }
  }

  const dispose = () => {
    gradingPoller.dispose()
    reportPoller.dispose()
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
    loadReportIfGraded,
    pollGrading,
    retryGrading,
    openGrading,
    submitGrading,
    startAdaptivePractice,
    dispose,
  }
}
