import { computed, ref, watch } from 'vue'
import { apiAskQuestionCoach, apiAskScopedCoach } from '@/api'
import { useAuthStore } from '@/stores/auth'
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
const COACH_LRU_INDEX_PREFIX = 'zhilian:coach:lru:'
const MAX_PERSISTED_MESSAGES = 30
const MAX_REQUEST_HISTORY_ITEMS = 20
export const MAX_PERSISTED_SESSIONS = 30

function resolveCoachUserId(): string {
  try {
    return useAuthStore().user?.id || 'anonymous'
  } catch {
    return 'anonymous'
  }
}

export function buildCoachStorageKey(userId: string, sessionKey: string): string {
  return `${COACH_HISTORY_STORAGE_PREFIX}${userId || 'anonymous'}:${sessionKey}`
}

export function buildCoachLruIndexKey(userId: string): string {
  return `${COACH_LRU_INDEX_PREFIX}${userId || 'anonymous'}`
}

function buildScopedMapKey(userId: string, sessionKey: string): string {
  return `${userId || 'anonymous'}:${sessionKey}`
}

function readLruIndex(userId: string): string[] {
  try {
    if (typeof uni === 'undefined' || typeof uni.getStorageSync !== 'function') return []
    const raw = uni.getStorageSync(buildCoachLruIndexKey(userId))
    if (!raw) return []
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item): item is string => typeof item === 'string' && item.length > 0)
  } catch {
    return []
  }
}

function writeLruIndex(userId: string, entries: string[]): void {
  try {
    if (typeof uni === 'undefined') return
    const indexKey = buildCoachLruIndexKey(userId)
    if (entries.length === 0) {
      if (typeof uni.removeStorageSync === 'function') {
        uni.removeStorageSync(indexKey)
      }
      return
    }
    if (typeof uni.setStorageSync === 'function') {
      uni.setStorageSync(indexKey, JSON.stringify(entries))
    }
  } catch {
    // 忽略受限环境下的本地存储异常
  }
}

function touchLruSession(userId: string, sessionKey: string): void {
  const entries = readLruIndex(userId).filter((item) => item !== sessionKey)
  entries.push(sessionKey)
  while (entries.length > MAX_PERSISTED_SESSIONS) {
    const evicted = entries.shift()
    if (evicted && typeof uni !== 'undefined' && typeof uni.removeStorageSync === 'function') {
      try {
        uni.removeStorageSync(buildCoachStorageKey(userId, evicted))
      } catch {
        // ignore storage errors
      }
    }
  }
  writeLruIndex(userId, entries)
}

function removeFromLruIndex(userId: string, sessionKey: string): void {
  const entries = readLruIndex(userId).filter((item) => item !== sessionKey)
  writeLruIndex(userId, entries)
}

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

function readPersistedHistory(userId: string, sessionKey: string): CoachMessage[] {
  try {
    if (typeof uni === 'undefined' || typeof uni.getStorageSync !== 'function') return []
    const raw = uni.getStorageSync(buildCoachStorageKey(userId, sessionKey))
    if (!raw) return []
    const messages = sanitizeStoredMessages(raw)
    if (messages.length > 0) {
      touchLruSession(userId, sessionKey)
    }
    return messages
  } catch {
    return []
  }
}

function writePersistedHistory(
  userId: string,
  sessionKey: string,
  messages: CoachMessage[],
): void {
  try {
    if (typeof uni === 'undefined' || typeof uni.setStorageSync !== 'function') return
    const valid = messages
      .filter((msg) => !msg.error && msg.content.trim().length > 0)
      .slice(-MAX_PERSISTED_MESSAGES)
    if (valid.length === 0) {
      if (typeof uni.removeStorageSync === 'function') {
        uni.removeStorageSync(buildCoachStorageKey(userId, sessionKey))
      }
      removeFromLruIndex(userId, sessionKey)
      return
    }
    uni.setStorageSync(buildCoachStorageKey(userId, sessionKey), JSON.stringify(valid))
    touchLruSession(userId, sessionKey)
  } catch {
    // 忽略测试或受限环境下的本地存储异常，不阻断对话主流程。
  }
}

function removePersistedHistory(userId: string, sessionKey: string): void {
  try {
    if (typeof uni === 'undefined' || typeof uni.removeStorageSync !== 'function') return
    uni.removeStorageSync(buildCoachStorageKey(userId, sessionKey))
    removeFromLruIndex(userId, sessionKey)
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

/** AI 助教对话流状态与多上下文/多用户会话隔离编排。 */
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
  const activeUserId = computed(() => resolveCoachUserId())
  const activeScopedKey = computed(() => buildScopedMapKey(activeUserId.value, sessionKey.value))

  const ensureSessionHydrated = (userId: string, key: string): CoachMessage[] => {
    const scopedKey = buildScopedMapKey(userId, key)
    const inMemory = sessionHistories.value.get(scopedKey)
    if (inMemory !== undefined) return inMemory
    const restored = readPersistedHistory(userId, key)
    if (restored.length > 0) {
      const nextMap = new Map(sessionHistories.value)
      nextMap.set(scopedKey, restored)
      sessionHistories.value = nextMap
    }
    return restored
  }

  watch(
    [activeUserId, sessionKey],
    ([userId, key]) => {
      ensureSessionHydrated(userId, key)
    },
    { immediate: true },
  )

  const messageList = computed<CoachMessage[]>(
    () =>
      sessionHistories.value.get(activeScopedKey.value) ??
      readPersistedHistory(activeUserId.value, sessionKey.value),
  )

  const isThinking = computed(() => thinkingKeys.value.has(activeScopedKey.value))

  const quickPrompts = computed<string[]>(() => {
    const ctx = getContext()
    if (ctx.questionId) return QUESTION_QUICK_PROMPTS
    if (ctx.knowledgePointId) return KP_QUICK_PROMPTS
    if (ctx.materialId || ctx.folderId) return MATERIAL_QUICK_PROMPTS
    return []
  })

  const appendMessage = (userId: string, key: string, msg: CoachMessage): void => {
    const scopedKey = buildScopedMapKey(userId, key)
    const nextMap = new Map(sessionHistories.value)
    const current = nextMap.get(scopedKey) ?? readPersistedHistory(userId, key)
    const updated = [...current, msg]
    nextMap.set(scopedKey, updated)
    sessionHistories.value = nextMap
    if (!msg.error) {
      writePersistedHistory(userId, key, updated)
    }
  }

  const removeMessage = (userId: string, key: string, messageId: string): void => {
    const scopedKey = buildScopedMapKey(userId, key)
    const nextMap = new Map(sessionHistories.value)
    const current = nextMap.get(scopedKey)
    if (!current) return
    const updated = current.filter((item) => item.id !== messageId)
    nextMap.set(scopedKey, updated)
    sessionHistories.value = nextMap
    writePersistedHistory(userId, key, updated)
  }

  const setThinking = (scopedKey: string, active: boolean): void => {
    const nextSet = new Set(thinkingKeys.value)
    if (active) nextSet.add(scopedKey)
    else nextSet.delete(scopedKey)
    thinkingKeys.value = nextSet
  }

  const setInputQuery = (text: string): void => {
    inputQuery.value = text
  }

  const clearCurrentSession = (): void => {
    const userId = activeUserId.value
    const key = sessionKey.value
    const scopedKey = buildScopedMapKey(userId, key)
    if (sessionHistories.value.has(scopedKey)) {
      const nextMap = new Map(sessionHistories.value)
      nextMap.delete(scopedKey)
      sessionHistories.value = nextMap
    }
    removePersistedHistory(userId, key)
  }

  const sendMessage = async (
    overrideQuery?: unknown,
    options?: { skipUserBubble?: boolean },
  ): Promise<void> => {
    const rawText = typeof overrideQuery === 'string' ? overrideQuery : inputQuery.value
    const query = rawText.trim()
    const targetUserId = activeUserId.value
    const targetKey = sessionKey.value
    const targetScopedKey = buildScopedMapKey(targetUserId, targetKey)
    if (!query || thinkingKeys.value.has(targetScopedKey)) return

    const ctx = { ...getContext() }
    const priorMessages = ensureSessionHydrated(targetUserId, targetKey)
    const requestHistory = buildRequestHistory(
      priorMessages,
      options?.skipUserBubble ? query : undefined,
    )

    if (!options?.skipUserBubble) {
      appendMessage(targetUserId, targetKey, { id: nextId(), role: 'user', content: query })
    }
    if (typeof overrideQuery !== 'string') {
      inputQuery.value = ''
    }

    setThinking(targetScopedKey, true)
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
        appendMessage(targetUserId, targetKey, {
          id: nextId(),
          role: 'assistant',
          content: res.reply,
          suggestions: res.suggestions,
        })
        return
      }

      if (!ctx.folderId && !ctx.materialId && !ctx.knowledgePointId) {
        appendMessage(targetUserId, targetKey, {
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
      appendMessage(targetUserId, targetKey, {
        id: nextId(),
        role: 'assistant',
        content: response.reply,
        suggestions: response.suggestions,
        sources: response.sources,
      })
    } catch {
      appendMessage(targetUserId, targetKey, {
        id: nextId(),
        role: 'assistant',
        content: '助教响应失败，请检查网络后重试。',
        error: true,
        retryQuery: query,
      })
    } finally {
      setThinking(targetScopedKey, false)
    }
  }

  const retryMessage = async (failedMsg: CoachMessage): Promise<void> => {
    if (!failedMsg.retryQuery) return
    removeMessage(activeUserId.value, sessionKey.value, failedMsg.id)
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
