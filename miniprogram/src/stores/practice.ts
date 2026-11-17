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
  type CoverageResult,
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
import { regenerateWrongPractice } from '@/utils/questionGeneration'
import { useAuthStore } from './auth'

export { isAnswered }

export interface RegenerateScope {
  folderId?: string
  materialId?: string
}

export interface RegenerateResult {
  session: PracticeSession
  coverage: CoverageResult
}

function resolveUserId(): string {
  try {
    return useAuthStore().user?.id || 'anonymous'
  } catch {
    return 'anonymous'
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

  // 逐题草稿写入队列：同题串行、失败可见、交卷前必须 flush 成功
  const draftQueue = createDraftQueue(
    async (questionId, answer) => {
      const practiceId = currentSession.value?.id
      if (!practiceId) return
      await apiSavePracticeDraft(practiceId, questionId, answer)
    },
    (state) => {
      isSavingDrafts.value = state.isPending
      draftFailures.value = state.failures.map((failure) => failure.questionId)
    },
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

  // 2. 记录单题答案：本地即时持久化 + 队列异步写后台
  const recordAnswer = (questionId: string, answer: unknown) => {
    userAnswers.value = { ...userAnswers.value, [questionId]: answer }
    if (currentSession.value) {
      writePracticeDraft(resolveUserId(), currentSession.value.id, userAnswers.value)
      draftQueue.enqueue(questionId, answer)
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
      clearPracticeStorage(resolveUserId(), practiceId)
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

  // 5. 错题自适应一键再生题：限定单一课程或未分类资料范围
  const regenerateFromWrongPoints = async (
    knowledgePointIds: string[],
    scope: RegenerateScope,
  ): Promise<RegenerateResult> => {
    const result = await regenerateWrongPractice(knowledgePointIds, scope)
    currentSession.value = result.session
    currentIndex.value = 0
    userAnswers.value = {}
    draftQueue.reset()
    return result
  }

  // 6. 查询本人练习列表：学情页恢复未完成练习与打开历史报告
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
    recordAnswer,
    retryAllDrafts,
    submit,
    requestRegrade,
    retryGrading,
    selfEvaluate,
    regenerateFromWrongPoints,
    loadPractices,
    nextQuestion,
    prevQuestion,
    jumpTo,
  }
})
