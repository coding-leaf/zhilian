import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PracticeSession, QuestionItem, DiagnosisReport, RegradeResponse } from '@/types'
import {
  apiCreatePractice,
  apiGetPracticeSession,
  apiSavePracticeDraft,
  apiSubmitPractice,
  apiTriggerDiagnosis,
  apiRegradeAttempt,
  apiAskQuestionCoach,
  apiGenerateQuestions,
  type CreatePracticeParams,
} from '@/api'

export const usePracticeStore = defineStore('practice', () => {
  const currentSession = ref<PracticeSession | null>(null)
  const currentIndex = ref<number>(0)
  const userAnswers = ref<Record<string, any>>({})
  const isSubmitting = ref<boolean>(false)
  const latestDiagnosis = ref<DiagnosisReport | null>(null)

  const questions = computed<QuestionItem[]>(() => currentSession.value?.questions || [])
  const currentQuestion = computed<QuestionItem | null>(() => {
    if (!questions.value.length) return null
    return questions.value[currentIndex.value] || null
  })

  const answeredCount = computed<number>(() => {
    return Object.keys(userAnswers.value).filter((key) => {
      const val = userAnswers.value[key]
      if (val === undefined || val === null || val === '') return false
      if (Array.isArray(val) && val.length === 0) return false
      return true
    }).length
  })

  const unansweredCount = computed<number>(() => {
    return questions.value.length - answeredCount.value
  })

  // 本地持久化 Draft 缓存 Key
  const getStorageKey = (practiceId: string) => `practice_draft_${practiceId}`

  // 1. 初始化或继续练习
  const initPractice = async (practiceId?: string, params?: CreatePracticeParams | string) => {
    if (practiceId) {
      currentSession.value = await apiGetPracticeSession(practiceId)
    } else if (params) {
      currentSession.value = await apiCreatePractice(params)
    }

    if (currentSession.value) {
      currentIndex.value = 0
      // 优先从本地恢复草稿答案，若无则使用服务端的 user_answers
      const localDraft = uni.getStorageSync(getStorageKey(currentSession.value.id))
      if (localDraft && typeof localDraft === 'object') {
        userAnswers.value = localDraft
      } else if (currentSession.value.user_answers) {
        userAnswers.value = { ...currentSession.value.user_answers }
      } else {
        userAnswers.value = {}
      }
    }
  }

  // 2. 记录单题答案并做本地持久化与异步暂存
  const recordAnswer = (questionId: string, answer: any) => {
    userAnswers.value[questionId] = answer
    if (currentSession.value) {
      // 写入本地存储 (防止意外退回丢失)
      uni.setStorageSync(getStorageKey(currentSession.value.id), userAnswers.value)
      // 异步无阻塞推送到服务器草稿 (入参: practiceId, questionId, userAnswer)
      apiSavePracticeDraft(currentSession.value.id, questionId, answer).catch(() => {})
    }
  }

  // 3. 提交练习与触发诊断
  const submit = async (): Promise<DiagnosisReport | null> => {
    if (!currentSession.value) return null
    isSubmitting.value = true
    try {
      // 提交服务端 (携带强幂等键)
      await apiSubmitPractice(currentSession.value.id, true)
      // 清理本地草稿
      uni.removeStorageSync(getStorageKey(currentSession.value.id))
      // 触发后端真实诊断生成
      const diagnosis = await apiTriggerDiagnosis(currentSession.value.id)
      latestDiagnosis.value = diagnosis
      return diagnosis
    } finally {
      isSubmitting.value = false
    }
  }

  // 4. 申请主观题 AI 重判
  const requestRegrade = async (attemptItemId: string, reason: string): Promise<RegradeResponse> => {
    const res = await apiRegradeAttempt(attemptItemId, reason)
    // 更新本地诊断报告详情中的评分与反馈
    if (latestDiagnosis.value) {
      const targetDetail = latestDiagnosis.value.details.find(
        (d) => d.attempt_item_id === attemptItemId
      )
      if (targetDetail && res.score !== undefined) {
        targetDetail.score = res.score
        if (targetDetail.max_score > 0) {
          targetDetail.is_correct = res.score === targetDetail.max_score
        }
      }
    }
    return res
  }

  // 5. 错题自适应一键再生题
  const regenerateFromWrongPoints = async (
    knowledgePointIds: string[],
    folderId?: string,
    materialId?: string
  ): Promise<PracticeSession> => {
    if (!knowledgePointIds || knowledgePointIds.length === 0) {
      throw new Error('未提供错题知识点')
    }
    // 1. 调用出题流水线
    const genResult = await apiGenerateQuestions({
      folder_id: folderId,
      material_id: materialId,
      knowledge_point_ids: knowledgePointIds,
      count: Math.max(3, knowledgePointIds.length * 2),
      difficulty: 3,
    })

    const newQuestionIds = (genResult.qualified_questions || []).map((q) => q.id)

    // 2. 创建新一轮练习批次
    const newSession = await apiCreatePractice({
      title: '错题巩固练习',
      folder_id: folderId,
      material_id: materialId,
      knowledge_point_ids: knowledgePointIds,
      question_ids: newQuestionIds.length > 0 ? newQuestionIds : undefined,
    })

    currentSession.value = newSession
    currentIndex.value = 0
    userAnswers.value = {}
    return newSession
  }

  // 6. 追问题目级 AI 助教
  const askCoach = async (questionId: string, prompt: string, userAnswer?: string, gradingPoints?: string[]) => {
    return apiAskQuestionCoach(questionId, prompt, userAnswer, gradingPoints)
  }

  // 切换题目
  const nextQuestion = () => {
    if (currentIndex.value < questions.value.length - 1) {
      currentIndex.value++
    }
  }

  const prevQuestion = () => {
    if (currentIndex.value > 0) {
      currentIndex.value--
    }
  }

  const jumpTo = (index: number) => {
    if (index >= 0 && index < questions.value.length) {
      currentIndex.value = index
    }
  }

  return {
    currentSession,
    currentIndex,
    userAnswers,
    isSubmitting,
    latestDiagnosis,
    questions,
    currentQuestion,
    answeredCount,
    unansweredCount,
    initPractice,
    recordAnswer,
    submit,
    requestRegrade,
    regenerateFromWrongPoints,
    askCoach,
    nextQuestion,
    prevQuestion,
    jumpTo,
  }
})
