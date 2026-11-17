import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import {
  buildCoachSessionKey,
  useCoachChat,
  type CoachContextParams,
} from '@/composables/useCoachChat'

describe('useCoachChat session isolation & error retry', () => {
  beforeEach(() => {
    requestMock.mockReset()
  })

  it('derives deterministic session keys by context priority', () => {
    expect(buildCoachSessionKey({ questionId: 'q-1', knowledgePointId: 'kp-1' })).toBe('q:q-1')
    expect(buildCoachSessionKey({ knowledgePointId: 'kp-1', materialId: 'm-1' })).toBe('kp:kp-1')
    expect(buildCoachSessionKey({ materialId: 'm-1', folderId: 'f-1' })).toBe('mat:m-1')
    expect(buildCoachSessionKey({ folderId: 'f-1' })).toBe('folder:f-1')
    expect(buildCoachSessionKey({})).toBe('global')
  })

  it('isolates histories across questions and knowledge points without cross-talk', async () => {
    const ctx = reactive<CoachContextParams>({ questionId: 'q-1' })
    requestMock.mockImplementation(async ({ url, data }: { url: string; data: any }) => {
      if (url.includes('/questions/q-1/')) {
        return { reply: `Q1答复:${data.user_prompt}`, suggestions: ['追问Q1'] }
      }
      if (url.includes('/questions/q-2/')) {
        return { reply: `Q2答复:${data.user_prompt}`, suggestions: [] }
      }
      return { reply: `KP答复:${data.user_prompt}`, suggestions: [], sources: [] }
    })

    const coach = useCoachChat(() => ctx)
    expect(coach.quickPrompts.value[0]).toContain('答案')

    await coach.sendMessage('为什么选A')
    expect(coach.messageList.value).toHaveLength(2)
    expect(coach.messageList.value[1].content).toBe('Q1答复:为什么选A')

    ctx.questionId = 'q-2'
    expect(coach.sessionKey.value).toBe('q:q-2')
    expect(coach.messageList.value).toEqual([])

    await coach.sendMessage('第二题怎么解')
    expect(coach.messageList.value).toHaveLength(2)
    expect(coach.messageList.value[1].content).toBe('Q2答复:第二题怎么解')

    ctx.questionId = undefined
    ctx.knowledgePointId = 'kp-1'
    expect(coach.quickPrompts.value[0]).toContain('大白话')
    await coach.sendMessage('讲讲考点')
    expect(coach.messageList.value[1].content).toBe('KP答复:讲讲考点')

    // 切回 q-1 保留原有完整历史
    ctx.knowledgePointId = undefined
    ctx.questionId = 'q-1'
    expect(coach.messageList.value).toHaveLength(2)
    expect(coach.messageList.value[0].content).toBe('为什么选A')

    coach.clearCurrentSession()
    expect(coach.messageList.value).toEqual([])

    ctx.questionId = 'q-2'
    expect(coach.messageList.value).toHaveLength(2)
  })

  it('delivers late async reply to the original session even after context switch', async () => {
    let resolveQ1!: (value: any) => void
    requestMock.mockImplementation(
      () => new Promise((resolve) => { resolveQ1 = resolve }),
    )

    const ctx = reactive<CoachContextParams>({ questionId: 'q-1' })
    const coach = useCoachChat(() => ctx)

    const pending = coach.sendMessage('延迟提问')
    expect(coach.isThinking.value).toBe(true)

    ctx.questionId = 'q-2'
    expect(coach.isThinking.value).toBe(false)
    expect(coach.messageList.value).toEqual([])

    resolveQ1({ reply: '延迟回到Q1', suggestions: [] })
    await pending

    expect(coach.messageList.value).toEqual([])
    ctx.questionId = 'q-1'
    expect(coach.messageList.value).toHaveLength(2)
    expect(coach.messageList.value[1].content).toBe('延迟回到Q1')
  })

  it('supports retrying a failed turn without duplicating the user bubble', async () => {
    const ctx = reactive<CoachContextParams>({ materialId: 'm-1' })
    requestMock
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce({ reply: '重试成功答复', suggestions: [], sources: [] })

    const coach = useCoachChat(() => ctx)
    await coach.sendMessage('总结核心公式')

    expect(coach.messageList.value).toHaveLength(2)
    const errMsg = coach.messageList.value[1]
    expect(errMsg.error).toBe(true)
    expect(errMsg.retryQuery).toBe('总结核心公式')

    await coach.retryMessage(errMsg)
    expect(coach.messageList.value).toHaveLength(2)
    expect(coach.messageList.value[0].role).toBe('user')
    expect(coach.messageList.value[1]).toMatchObject({
      role: 'assistant',
      content: '重试成功答复',
    })
  })

  it('sends only the highest-priority scope field when multiple context IDs exist', async () => {
    requestMock.mockResolvedValue({ reply: '单一范围答复', suggestions: [], sources: [] })
    const ctx = reactive<CoachContextParams>({
      folderId: 'f-1',
      materialId: 'm-1',
      knowledgePointId: 'kp-1',
    })
    const coach = useCoachChat(() => ctx)

    await coach.sendMessage('你好呀')
    expect(requestMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        url: '/coach/ask',
        data: {
          knowledge_point_id: 'kp-1',
          user_prompt: '你好呀',
        },
      }),
    )

    ctx.knowledgePointId = undefined
    await coach.sendMessage('讲义总结')
    expect(requestMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        url: '/coach/ask',
        data: {
          material_id: 'm-1',
          user_prompt: '讲义总结',
        },
      }),
    )
  })
})
