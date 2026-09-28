import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PracticeSession, QuestionItem } from '@/types'
import {
  apiCreatePractice,
  apiGetPracticeSession,
  apiSavePracticeDraft,
  apiSubmitPractice,
  apiTriggerDiagnosis,
} from '@/api'

export const usePracticeStore = defineStore('practice', () => {
  const currentSession = ref<PracticeSession | null>(null)
  const currentIndex = ref<number>(0)
  const userAnswers = ref<Record<string, any>>({})
  const isSubmitting = ref<boolean>(false)

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
  const initPractice = async (practiceId?: string, materialId?: string) => {
    if (practiceId) {
      currentSession.value = await apiGetPracticeSession(practiceId)
    } else if (materialId) {
      currentSession.value = await apiCreatePractice(materialId)
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

  // 2. 记录单题答案并做本地持久化
  const recordAnswer = (questionId: string, answer: any) => {
    userAnswers.value[questionId] = answer
    if (currentSession.value) {
      // 写入本地存储 (防止意外退回丢失)
      uni.setStorageSync(getStorageKey(currentSession.value.id), userAnswers.value)
      // 异步无阻塞推送到服务器草稿
      apiSavePracticeDraft(currentSession.value.id, userAnswers.value).catch(() => {})
    }
  }

  // 3. 提交练习与触发诊断
  const submit = async () => {
    if (!currentSession.value) return null
    isSubmitting.value = true
    try {
      // 提交服务端
      await apiSubmitPractice(currentSession.value.id)
      // 清理本地草稿
      uni.removeStorageSync(getStorageKey(currentSession.value.id))
      // 触发后端真实诊断生成
      const diagnosis = await apiTriggerDiagnosis(currentSession.value.id)
      return diagnosis
    } finally {
      isSubmitting.value = false
    }
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
    questions,
    currentQuestion,
    answeredCount,
    unansweredCount,
    initPractice,
    recordAnswer,
    submit,
    nextQuestion,
    prevQuestion,
    jumpTo,
  }
})
