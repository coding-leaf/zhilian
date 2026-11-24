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
    uni.clearStorageSync()
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
          thread_id: 'kp:kp-1',
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
          thread_id: 'mat:m-1',
        },
      }),
    )
  })

  it('passes the session key as thread_id for every scoped coach turn', async () => {
    requestMock.mockResolvedValue({ reply: '多轮答复', suggestions: [], sources: [] })
    const ctx = reactive<CoachContextParams>({ folderId: 'f-1' })
    const coach = useCoachChat(() => ctx)

    await coach.sendMessage('第一轮')
    await coach.sendMessage('那不满足这个条件会怎样')
    const folderCalls = requestMock.mock.calls
      .map(([options]) => options as { url: string; data: Record<string, unknown> })
      .filter((options) => options.url === '/coach/ask')
    expect(folderCalls).toHaveLength(2)
    for (const call of folderCalls) {
      expect(call.data).toEqual({
        folder_id: 'f-1',
        user_prompt: expect.any(String),
        thread_id: 'folder:f-1',
      })
    }

    ctx.folderId = undefined
    ctx.materialId = 'm-9'
    await coach.sendMessage('换到讲义')
    expect(requestMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        data: { material_id: 'm-9', user_prompt: '换到讲义', thread_id: 'mat:m-9' },
      }),
    )
  })

  it('sends thread_id and bounded recent history (excluding errors) on question coach endpoint', async () => {
    requestMock
      .mockResolvedValueOnce({ reply: '题目答复1', suggestions: [] })
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce({ reply: '题目答复2', suggestions: [] })

    const ctx = reactive<CoachContextParams>({ questionId: 'q-7', folderId: 'f-1' })
    const coach = useCoachChat(() => ctx)

    await coach.sendMessage('为什么')
    const firstCall = requestMock.mock.calls[0][0] as { url: string; data: Record<string, unknown> }
    expect(firstCall.url).toContain('/questions/q-7/')
    expect(firstCall.data.thread_id).toBe('q:q-7')
    expect(firstCall.data).not.toHaveProperty('history')

    // 触发一次失败产生 error 占位气泡
    await coach.sendMessage('失败的一问')
    expect(coach.messageList.value.some((msg) => msg.error)).toBe(true)

    // 后续成功追问不得把 error 占位气泡或当前提问本身塞进 history
    await coach.sendMessage('我刚开始问的什么')
    const thirdCall = requestMock.mock.calls[2][0] as { url: string; data: Record<string, unknown> }
    expect(thirdCall.data.thread_id).toBe('q:q-7')
    expect(thirdCall.data.user_prompt).toBe('我刚开始问的什么')
    expect(thirdCall.data.history).toEqual([
      { role: 'user', content: '为什么' },
      { role: 'assistant', content: '题目答复1' },
      { role: 'user', content: '失败的一问' },
    ])
  })

  it('persists question chat history across drawer remount / page redirect and clears cleanly', async () => {
    requestMock
      .mockResolvedValueOnce({ reply: '答复一', suggestions: ['追问'] })
      .mockResolvedValueOnce({ reply: '答复二：你刚问了第一题', suggestions: [] })

    const coach1 = useCoachChat(() => ({ questionId: 'q-99', userAnswer: '' }))
    await coach1.sendMessage('第一问是什么')
    expect(coach1.messageList.value).toHaveLength(2)

    // 模拟页面 redirectTo（如做题页 -> 报告页）后重新创建 composable
    const coach2 = useCoachChat(() => ({ questionId: 'q-99', userAnswer: 'A' }))
    expect(coach2.messageList.value).toHaveLength(2)
    expect(coach2.messageList.value[0].content).toBe('第一问是什么')
    expect(coach2.messageList.value[1].content).toBe('答复一')

    await coach2.sendMessage('我刚才问了什么')
    const secondCall = requestMock.mock.calls[1][0] as { url: string; data: Record<string, unknown> }
    expect(secondCall.data.thread_id).toBe('q:q-99')
    expect(secondCall.data.history).toEqual([
      { role: 'user', content: '第一问是什么' },
      { role: 'assistant', content: '答复一' },
    ])
    expect(coach2.messageList.value).toHaveLength(4)

    coach2.clearCurrentSession()
    expect(coach2.messageList.value).toEqual([])
    const coach3 = useCoachChat(() => ({ questionId: 'q-99' }))
    expect(coach3.messageList.value).toEqual([])
  })

  it('bounds persisted storage and request history and degrades safely if storage throws', async () => {
    requestMock.mockImplementation(async ({ data }: { data: any }) => ({
      reply: `reply:${data.user_prompt}`,
      suggestions: [],
    }))

    const ctx = reactive<CoachContextParams>({ questionId: 'q-cap' })
    const coach = useCoachChat(() => ctx)
    for (let i = 1; i <= 16; i += 1) {
      await coach.sendMessage(`q-${i}`)
    }

    // 16 轮 = 32 条消息，本地持久化上限裁剪到最近 30 条，单次请求 history 上限 20 条
    const lastCall = requestMock.mock.calls.at(-1)?.[0] as { data: { history: Array<{ content: string }> } }
    expect(lastCall.data.history).toHaveLength(20)
    expect(lastCall.data.history[0].content).toBe('q-6')

    const coachReloaded = useCoachChat(() => ({ questionId: 'q-cap' }))
    expect(coachReloaded.messageList.value).toHaveLength(30)
    expect(coachReloaded.messageList.value[0].content).toBe('q-2')

    const spy = vi.spyOn(uni, 'getStorageSync').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    const safeCoach = useCoachChat(() => ({ questionId: 'q-broken' }))
    expect(safeCoach.messageList.value).toEqual([])
    spy.mockRestore()
  })
})