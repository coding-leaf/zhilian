import { computed, ref, watch } from 'vue'
import { apiAskQuestionCoach, apiAskScopedCoach } from '@/api'
import type { AskCoachHistoryItem, CoachSource } from '@/types'

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

const COACH_HISTORY_STORAGE_PREFIX = 'zhilian:coach:history:'
const MAX_PERSISTED_MESSAGES = 30
const MAX_REQUEST_HISTORY_ITEMS = 20

const buildStorageKey = (sessionKey: string): string =>
  `${COACH_HISTORY_STORAGE_PREFIX}${sessionKey}`

function sanitizeStoredMessages(raw: unknown): CoachMessage[] {
  let parsed: unknown = raw
  if (typeof raw === 'string') {
    if (!raw.trim()) return []
    try {
      parsed = JSON.parse(raw)
    } catch {
      return []
    }
  }
  if (!Array.isArray(parsed)) return []

  const cleaned: CoachMessage[] = []
  for (let idx = 0; idx < parsed.length; idx += 1) {
    const item = parsed[idx] as Record<string, unknown> | null | undefined
    if (!item || typeof item !== 'object') continue
    if (item.error === true) continue
    if (item.role !== 'user' && item.role !== 'assistant') continue
    if (typeof item.content !== 'string' || !item.content.trim()) continue

    cleaned.push({
      id: typeof item.id === 'string' && item.id ? item.id : `coach-restored-${idx}`,
      role: item.role,
      content: item.content,
      suggestions: Array.isArray(item.suggestions)
        ? item.suggestions.filter((s): s is string => typeof s === 'string')
        : undefined,
      sources: Array.isArray(item.sources) ? (item.sources as CoachSource[]) : undefined,
    })
  }
  return cleaned.slice(-MAX_PERSISTED_MESSAGES)
}

function readPersistedHistory(sessionKey: string): CoachMessage[] {
  try {
    if (typeof uni === 'undefined' || typeof uni.getStorageSync !== 'function') return []
    const raw = uni.getStorageSync(buildStorageKey(sessionKey))
    if (!raw) return []
    return sanitizeStoredMessages(raw)
  } catch {
    return []
  }
}

function writePersistedHistory(sessionKey: string, messages: CoachMessage[]): void {
  try {
    if (typeof uni === 'undefined' || typeof uni.setStorageSync !== 'function') return
    const valid = messages
      .filter((msg) => !msg.error && msg.content.trim().length > 0)
      .slice(-MAX_PERSISTED_MESSAGES)
    if (valid.length === 0) {
      if (typeof uni.removeStorageSync === 'function') {
        uni.removeStorageSync(buildStorageKey(sessionKey))
      }
      return
    }
    uni.setStorageSync(buildStorageKey(sessionKey), JSON.stringify(valid))
  } catch {
    // 忽略测试或受限环境下的本地存储异常，不阻断对话主流程。
  }
}

function removePersistedHistory(sessionKey: string): void {
  try {
    if (typeof uni === 'undefined' || typeof uni.removeStorageSync !== 'function') return
    uni.removeStorageSync(buildStorageKey(sessionKey))
  } catch {
    // ignore storage errors
  }
}

function buildRequestHistory(
  messages: CoachMessage[],
  skipTrailingUserQuery?: string,
): AskCoachHistoryItem[] {
  const valid = messages.filter((msg) => !msg.error && msg.content.trim().length > 0)
  const trimmedList =
    skipTrailingUserQuery &&
    valid.length > 0 &&
    valid[valid.length - 1].role === 'user' &&
    valid[valid.length - 1].content.trim() === skipTrailingUserQuery
      ? valid.slice(0, -1)
      : valid

  return trimmedList.slice(-MAX_REQUEST_HISTORY_ITEMS).map((msg) => ({
    role: msg.role,
    content: msg.content.trim().slice(0, 2000),
  }))
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
    return `coach-msg-${Date.now().toString(36)}-${msgSeq}`
  }

  const sessionKey = computed(() => buildCoachSessionKey(getContext()))

  const ensureSessionHydrated = (key: string): CoachMessage[] => {
    const inMemory = sessionHistories.value.get(key)
    if (inMemory !== undefined) return inMemory
    const restored = readPersistedHistory(key)
    if (restored.length > 0) {
      const nextMap = new Map(sessionHistories.value)
      nextMap.set(key, restored)
      sessionHistories.value = nextMap
    }
    return restored
  }

  watch(
    sessionKey,
    (key) => {
      ensureSessionHydrated(key)
    },
    { immediate: true },
  )

  const messageList = computed<CoachMessage[]>(
    () => sessionHistories.value.get(sessionKey.value) ?? readPersistedHistory(sessionKey.value),
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
    const current = nextMap.get(key) ?? readPersistedHistory(key)
    const updated = [...current, msg]
    nextMap.set(key, updated)
    sessionHistories.value = nextMap
    if (!msg.error) {
      writePersistedHistory(key, updated)
    }
  }

  const removeMessage = (key: string, messageId: string): void => {
    const nextMap = new Map(sessionHistories.value)
    const current = nextMap.get(key)
    if (!current) return
    const updated = current.filter((item) => item.id !== messageId)
    nextMap.set(key, updated)
    sessionHistories.value = nextMap
    writePersistedHistory(key, updated)
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
    if (sessionHistories.value.has(key)) {
      const nextMap = new Map(sessionHistories.value)
      nextMap.delete(key)
      sessionHistories.value = nextMap
    }
    removePersistedHistory(key)
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
    const priorMessages = ensureSessionHydrated(targetKey)
    const requestHistory = buildRequestHistory(
      priorMessages,
      options?.skipUserBubble ? query : undefined,
    )

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
          {
            threadId: targetKey,
            history: requestHistory,
          },
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

      const scopePayload = ctx.knowledgePointId
        ? { knowledge_point_id: ctx.knowledgePointId }
        : ctx.materialId
          ? { material_id: ctx.materialId }
          : { folder_id: ctx.folderId }

      const response = await apiAskScopedCoach({
        ...scopePayload,
        user_prompt: query,
        thread_id: targetKey,
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
