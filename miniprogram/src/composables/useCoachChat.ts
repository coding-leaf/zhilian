import { computed, ref } from 'vue'
import { apiAskQuestionCoach, apiAskScopedCoach } from '@/api'
import type { CoachSource } from '@/types'

export interface CoachMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  prompt?: string
  suggestions?: string[]
  sources?: CoachSource[]
  error?: boolean
  retryQuery?: string
}

export type ChatMessage = CoachMessage

export interface CoachContextParams {
  questionId?: string
  userAnswer?: string
  gradingPoints?: string[]
  folderId?: string
  materialId?: string
  knowledgePointId?: string
}

export function buildCoachSessionKey(ctx: CoachContextParams): string {
  if (ctx.questionId) return `q:${ctx.questionId}`
  if (ctx.knowledgePointId) return `kp:${ctx.knowledgePointId}`
  if (ctx.materialId) return `mat:${ctx.materialId}`
  if (ctx.folderId) return `folder:${ctx.folderId}`
  return 'global'
}

const QUESTION_QUICK_PROMPTS = [
  '这道题为什么选这个答案？',
  '其他选项分别错在哪里？',
  '帮我梳理这题考察的核心考点',
  '用通俗例子再解释一遍',
]

const KP_QUICK_PROMPTS = [
  '用大白话解释这个考点',
  '总结核心公式与推导思路',
  '这个考点有哪些易混边界条件？',
  '结合典型场景帮我加深理解',
]

const MATERIAL_QUICK_PROMPTS = [
  '帮我梳理这份资料的核心框架',
  '哪些核心公式和概念最容易混淆？',
  '总结这部分内容的关键适用条件',
]

/** AI 助教对话流状态与多上下文会话隔离编排。 */
export function useCoachChat(getContext: () => CoachContextParams) {
  const inputQuery = ref('')
  const sessionHistories = ref<Map<string, CoachMessage[]>>(new Map())
  const thinkingKeys = ref<Set<string>>(new Set())
  let msgSeq = 0

  const nextId = (): string => {
    msgSeq += 1
    return `coach-msg-${msgSeq}`
  }

  const sessionKey = computed(() => buildCoachSessionKey(getContext()))

  const messageList = computed<CoachMessage[]>(
    () => sessionHistories.value.get(sessionKey.value) ?? [],
  )

  const isThinking = computed(() => thinkingKeys.value.has(sessionKey.value))

  const quickPrompts = computed<string[]>(() => {
    const ctx = getContext()
    if (ctx.questionId) return QUESTION_QUICK_PROMPTS
    if (ctx.knowledgePointId) return KP_QUICK_PROMPTS
    if (ctx.materialId || ctx.folderId) return MATERIAL_QUICK_PROMPTS
    return []
  })

  const appendMessage = (key: string, msg: CoachMessage): void => {
    const nextMap = new Map(sessionHistories.value)
    const current = nextMap.get(key) ?? []
    nextMap.set(key, [...current, msg])
    sessionHistories.value = nextMap
  }

  const removeMessage = (key: string, messageId: string): void => {
    const nextMap = new Map(sessionHistories.value)
    const current = nextMap.get(key)
    if (!current) return
    nextMap.set(
      key,
      current.filter((item) => item.id !== messageId),
    )
    sessionHistories.value = nextMap
  }

  const setThinking = (key: string, active: boolean): void => {
    const nextSet = new Set(thinkingKeys.value)
    if (active) nextSet.add(key)
    else nextSet.delete(key)
    thinkingKeys.value = nextSet
  }

  const setInputQuery = (text: string): void => {
    inputQuery.value = text
  }

  const clearCurrentSession = (): void => {
    const key = sessionKey.value
    if (!sessionHistories.value.has(key)) return
    const nextMap = new Map(sessionHistories.value)
    nextMap.delete(key)
    sessionHistories.value = nextMap
  }

  const sendMessage = async (
    overrideQuery?: unknown,
    options?: { skipUserBubble?: boolean },
  ): Promise<void> => {
    const rawText = typeof overrideQuery === 'string' ? overrideQuery : inputQuery.value
    const query = rawText.trim()
    const targetKey = sessionKey.value
    if (!query || thinkingKeys.value.has(targetKey)) return

    const ctx = { ...getContext() }
    if (!options?.skipUserBubble) {
      appendMessage(targetKey, { id: nextId(), role: 'user', content: query })
    }
    if (typeof overrideQuery !== 'string') {
      inputQuery.value = ''
    }

    setThinking(targetKey, true)
    try {
      if (ctx.questionId) {
        const res = await apiAskQuestionCoach(
          ctx.questionId,
          query,
          ctx.userAnswer,
          ctx.gradingPoints,
        )
        appendMessage(targetKey, {
          id: nextId(),
          role: 'assistant',
          content: res.reply,
          suggestions: res.suggestions,
        })
        return
      }

      if (!ctx.folderId && !ctx.materialId && !ctx.knowledgePointId) {
        appendMessage(targetKey, {
          id: nextId(),
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
      appendMessage(targetKey, {
        id: nextId(),
        role: 'assistant',
        content: response.reply,
        suggestions: response.suggestions,
        sources: response.sources,
      })
    } catch {
      appendMessage(targetKey, {
        id: nextId(),
        role: 'assistant',
        content: '助教响应失败，请检查网络后重试。',
        error: true,
        retryQuery: query,
      })
    } finally {
      setThinking(targetKey, false)
    }
  }

  const retryMessage = async (failedMsg: CoachMessage): Promise<void> => {
    if (!failedMsg.retryQuery) return
    removeMessage(sessionKey.value, failedMsg.id)
    await sendMessage(failedMsg.retryQuery, { skipUserBubble: true })
  }

  return {
    sessionKey,
    inputQuery,
    isThinking,
    messageList,
    quickPrompts,
    setInputQuery,
    clearCurrentSession,
    sendMessage,
    retryMessage,
  }
}
