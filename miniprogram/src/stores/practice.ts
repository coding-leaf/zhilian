import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  PracticeSession,
  QuestionItem,
  RegradeResponse,
  SelfEvaluateResponse,
  AttemptResult,
} from '@/types'
import {
  apiCreatePractice,
  apiGetPracticeSession,
  apiSavePracticeDraft,
  apiSubmitPractice,
  apiRetryPracticeGrading,
  apiRegradeAttempt,
  apiSelfEvaluate,
  apiListPractices,
  buildAttemptResults,
  type CreatePracticeParams,
} from '@/api'
import { createDraftQueue } from '@/utils/draftQueue'
import {
  clearPracticeStorage,
  getOrCreatePracticeSubmitKey,
  isAnswered,
  readPracticeDraft,
  writePracticeDraft,
} from '@/utils/practiceHelpers'
import { useAuthStore } from './auth'

export { isAnswered }

function resolveUserId(): string {
  try {
    return useAuthStore().user?.id || 'anonymous'
  } catch {
    return 'anonymous'
  }
}

function clearPracticeDraftWithFallback(userId: string, practiceId: string): void {
  clearPracticeStorage(userId, practiceId)
  if (userId !== 'anonymous') {
    clearPracticeStorage('anonymous', practiceId)
  }
}

export const usePracticeStore = defineStore('practice', () => {
  const currentSession = ref<PracticeSession | null>(null)
  const currentIndex = ref<number>(0)
  const userAnswers = ref<Record<string, unknown>>({})
  const isSubmitting = ref<boolean>(false)
  const isSavingDrafts = ref<boolean>(false)
  const draftFailures = ref<string[]>([])

  const questions = computed<QuestionItem[]>(() => currentSession.value?.questions || [])
  const attemptResults = computed<AttemptResult[]>(() => buildAttemptResults(currentSession.value))
  const currentQuestion = computed<QuestionItem | null>(() => {
    if (!questions.value.length) return null
    return questions.value[currentIndex.value] || null
  })

  const answeredCount = computed<number>(() =>
    Object.keys(userAnswers.value).filter((key) => isAnswered(userAnswers.value[key])).length,
  )

  const unansweredCount = computed<number>(() => questions.value.length - answeredCount.value)

  // 逐题草稿写入队列：同题串行、代际隔离、静态绑定 practiceId、限流 <=2、静默不误杀前台 loading
  const draftQueue = createDraftQueue(
    async (questionId, answer, boundPracticeId) => {
      const practiceId = boundPracticeId || currentSession.value?.id
      if (!practiceId) return
      await apiSavePracticeDraft(practiceId, questionId, answer, 0, { silentToast: true })
    },
    (state) => {
      isSavingDrafts.value = state.isPending
      draftFailures.value = state.failures.map((failure) => failure.questionId)
    },
    { maxConcurrent: 2 },
  )

  // 1. 初始化或继续练习
  const initPractice = async (practiceId?: string, params?: CreatePracticeParams) => {
    draftQueue.reset()
    if (practiceId) {
      currentSession.value = await apiGetPracticeSession(practiceId)
    } else if (params) {
      currentSession.value = await apiCreatePractice(params)
    }

    if (currentSession.value) {
      currentIndex.value = 0
      const session = currentSession.value
      // 优先恢复本地草稿，其次使用服务端已存作答
      const localDraft = readPracticeDraft(resolveUserId(), session.id)
      userAnswers.value = localDraft ?? { ...(session.user_answers || {}) }
    }
    return currentSession.value
  }

  const refreshSession = async (practiceId?: string) => {
    const id = practiceId || currentSession.value?.id
    if (!id) return null
    currentSession.value = await apiGetPracticeSession(id)
    return currentSession.value
  }

  // 2a. 仅更新内存答案（供文本输入防抖路径立即刷新 UI 与答题卡进度）
  const setLocalAnswer = (questionId: string, answer: unknown) => {
    userAnswers.value = { ...userAnswers.value, [questionId]: answer }
  }

  // 2b. 将单题答案持久化到本地并静态绑定 practiceId 推入后台草稿队列
  const persistDraftAnswer = (
    questionId: string,
    answer?: unknown,
    boundPracticeId?: string,
  ) => {
    const practiceId = boundPracticeId || currentSession.value?.id
    if (!practiceId) return
    const resolvedAnswer = answer !== undefined ? answer : userAnswers.value[questionId]
    const answersSnapshot =
      answer !== undefined && userAnswers.value[questionId] !== answer
        ? { ...userAnswers.value, [questionId]: answer }
        : userAnswers.value
    writePracticeDraft(resolveUserId(), practiceId, answersSnapshot)
    draftQueue.enqueue(questionId, resolvedAnswer, practiceId)
  }

  // 2c. 记录单题答案：本地即时持久化 + 队列异步写后台
  const recordAnswer = (questionId: string, answer: unknown) => {
    setLocalAnswer(questionId, answer)
    if (currentSession.value) {
      persistDraftAnswer(questionId, answer, currentSession.value.id)
    }
  }

  const retryAllDrafts = async () => {
    await draftQueue.retryAll()
  }

  // 3. 交卷：等待在途草稿全部成功后提交，幂等键对同一提交重试保持稳定
  const submit = async (confirmUnanswered = true): Promise<PracticeSession> => {
    if (!currentSession.value) throw new Error('当前没有进行中的练习')
    const practiceId = currentSession.value.id
    isSubmitting.value = true
    try {
      const saved = await draftQueue.flush()
      if (!saved) {
        throw new Error('仍有作答未保存成功，请检查网络后重试')
      }
      const submitKey = getOrCreatePracticeSubmitKey(practiceId)
      await apiSubmitPractice(practiceId, confirmUnanswered, submitKey)
      const session = await apiGetPracticeSession(practiceId)
      currentSession.value = session
      clearPracticeDraftWithFallback(resolveUserId(), practiceId)
      return session
    } finally {
      isSubmitting.value = false
    }
  }

  // 4. 主观题自评 / 申请 AI 复查：完成后刷新会话，读取最终生效结果
  const requestRegrade = async (attemptItemId: string, reason: string): Promise<RegradeResponse> => {
    const res = await apiRegradeAttempt(attemptItemId, reason)
    await refreshSession()
    return res
  }

  // 4.5 未完成的整卷判题重试：判题任务终态失败或存在待重判项时的恢复入口
  const retryGrading = async (practiceId?: string): Promise<PracticeSession | null> => {
    const id = practiceId || currentSession.value?.id
    if (!id) throw new Error('当前没有可重试判题的练习')
    await apiRetryPracticeGrading(id)
    return refreshSession(id)
  }

  const selfEvaluate = async (
    attemptItemId: string,
    score: number,
    feedback?: string,
    isCorrect?: boolean,
  ): Promise<SelfEvaluateResponse> => {
    const res = await apiSelfEvaluate(attemptItemId, score, feedback, isCorrect)
    await refreshSession()
    return res
  }

  // 5. 查询本人练习列表：学情页恢复未完成练习与打开历史报告
  const loadPractices = async (status?: string, limit = 20) => {
    const res = await apiListPractices({ status, limit })
    return res.items || []
  }

  const nextQuestion = () => {
    if (currentIndex.value < questions.value.length - 1) currentIndex.value++
  }

  const prevQuestion = () => {
    if (currentIndex.value > 0) currentIndex.value--
  }

  const jumpTo = (index: number) => {
    if (index >= 0 && index < questions.value.length) currentIndex.value = index
  }

  // 6. 登出/切账号重置会话与草稿队列，清理匿名草稿兜底键
  const resetState = () => {
    const activePracticeId = currentSession.value?.id
    draftQueue.reset()
    if (activePracticeId) {
      clearPracticeStorage('anonymous', activePracticeId)
    }
    currentSession.value = null
    currentIndex.value = 0
    userAnswers.value = {}
    isSubmitting.value = false
    isSavingDrafts.value = false
    draftFailures.value = []
  }

  return {
    currentSession,
    currentIndex,
    userAnswers,
    isSubmitting,
    isSavingDrafts,
    draftFailures,
    questions,
    attemptResults,
    currentQuestion,
    answeredCount,
    unansweredCount,
    initPractice,
    refreshSession,
    setLocalAnswer,
    persistDraftAnswer,
    recordAnswer,
    retryAllDrafts,
    submit,
    requestRegrade,
    retryGrading,
    selfEvaluate,
    loadPractices,
    nextQuestion,
    prevQuestion,
    jumpTo,
    resetState,
    reset: resetState,
  }
})
