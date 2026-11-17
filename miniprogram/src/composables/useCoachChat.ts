import { ref } from 'vue'
import { apiAskQuestionCoach, apiAskScopedCoach } from '@/api'
import type { CoachSource } from '@/types'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  prompt?: string
  suggestions?: string[]
  sources?: CoachSource[]
}

export interface CoachContextParams {
  questionId?: string
  userAnswer?: string
  gradingPoints?: string[]
  folderId?: string
  materialId?: string
  knowledgePointId?: string
}

/** AI 助教对话流状态与请求编排。 */
export function useCoachChat(getContext: () => CoachContextParams) {
  const inputQuery = ref('')
  const isThinking = ref(false)
  const messageList = ref<ChatMessage[]>([])

  const setInputQuery = (text: string) => {
    inputQuery.value = text
  }

  const sendMessage = async () => {
    const query = inputQuery.value.trim()
    if (!query || isThinking.value) return

    messageList.value.push({ role: 'user', content: query })
    inputQuery.value = ''
    isThinking.value = true

    try {
      const ctx = getContext()
      if (ctx.questionId) {
        const res = await apiAskQuestionCoach(
          ctx.questionId,
          query,
          ctx.userAnswer,
          ctx.gradingPoints,
        )
        messageList.value.push({
          role: 'assistant',
          content: res.reply,
          suggestions: res.suggestions,
        })
        return
      }

      if (!ctx.folderId && !ctx.materialId && !ctx.knowledgePointId) {
        messageList.value.push({
          role: 'assistant',
          content: '请先选择一门课程或打开一份讲义，再向助教提问。',
        })
        return
      }

      const response = await apiAskScopedCoach({
        ...(ctx.folderId ? { folder_id: ctx.folderId } : {}),
        ...(ctx.materialId ? { material_id: ctx.materialId } : {}),
        ...(ctx.knowledgePointId ? { knowledge_point_id: ctx.knowledgePointId } : {}),
        user_prompt: query,
      })
      messageList.value.push({
        role: 'assistant',
        content: response.reply,
        suggestions: response.suggestions,
        sources: response.sources,
      })
    } catch {
      messageList.value.push({
        role: 'assistant',
        content: '助教网络开小差了，请稍后再试。',
      })
    } finally {
      isThinking.value = false
    }
  }

  return {
    inputQuery,
    isThinking,
    messageList,
    setInputQuery,
    sendMessage,
  }
}
