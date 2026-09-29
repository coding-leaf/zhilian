import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import { useDiagnosisStore } from '@/stores/diagnosis'
import { useQuestionCompose } from '@/subpackages/material/composables/useQuestionCompose'
import { diagnosisReportFixture, generatedQuestionFixture, practiceDetailFixture } from './fixtures/backendResponses'

const completedSession = {
  ...practiceDetailFixture,
  status: 'completed',
  completed_at: '2026-09-28T12:00:00',
}

/**
 * 生成成功后出题页会回查批次摘要来显示「本次生成批次」。
 * 用同一份响应满足该请求，避免用例把「批次回查失败」的降级路径当成正常路径。
 */
function batchSummaryResponse(
  batchId: string,
  options: { availableCount?: number; materialTitle?: string } = {},
) {
  const availableCount = options.availableCount ?? 1
  return {
    items: [
      {
        batch_id: batchId,
        question_count: availableCount,
        available_count: availableCount,
        pending_review_count: 0,
        created_at: '2026-03-01T08:00:00',
        sources: [
          {
            material_id: 'm-1',
            material_title: options.materialTitle ?? '讲义.pdf',
            folder_id: null,
            folder_name: null,
          },
        ],
      },
    ],
    total: 1,
  }
}

describe('diagnosis store waits for real grading completion', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
  })

  it('returns null and flags pending while the paper is not fully graded', async () => {
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/practices/p-1') return practiceDetailFixture
      throw new Error(`should not fetch report yet: ${options.url}`)
    })

    const store = useDiagnosisStore()
    const report = await store.loadReport('p-1', 2, 0)

    expect(report).toBeNull()
    expect(store.isPending).toBe(true)
    expect(store.currentReport).toBeNull()
  })

  it('fetches the formal report only after completed_at is persisted', async () => {
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/practices/p-1') return completedSession
      if (options.url === '/practices/p-1/diagnosis') return diagnosisReportFixture
      throw new Error(`unexpected: ${options.url}`)
    })

    const store = useDiagnosisStore()
    const report = await store.loadReport('p-1', 2, 0)

    expect(report?.id).toBe('d-1')
    expect(store.isPending).toBe(false)
    const diagnosisCall = requestMock.mock.calls.find(([options]: any[]) => options.url.endsWith('/diagnosis'))
    expect(diagnosisCall?.[0].method).toBe('POST')
  })
})

describe('question compose coverage gating', () => {
  beforeEach(() => {
    requestMock.mockReset()
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions/generate') {
        const kpIds: string[] = options.data.knowledge_point_ids || []
        return {
          batch_id: 'b-1',
          total_generated: kpIds.length,
          qualified_count: kpIds.length,
          pending_count: 0,
          qualified_questions: kpIds.map((kpId, index) =>
            generatedQuestionFixture({ id: `q-${kpId}`, knowledge_point_id: kpId, stem: `题干-${index}` }),
          ),
          pending_questions: [],
        }
      }
      if (options.url.startsWith('/questions/batches')) return batchSummaryResponse('b-1')
      throw new Error(`unexpected: ${options.url}`)
    })
  })

  it('raises the planned count to cover all selected points', () => {
    const compose = useQuestionCompose()
    compose.setKnowledgePoints([
      { id: 'k-1', name: '考点一' },
      { id: 'k-2', name: '考点二' },
      { id: 'k-3', name: '考点三' },
    ])
    compose.questionCount.value = 1

    expect(compose.plannedCount.value).toBe(3)
  })

  it('blocks starting when removal creates a coverage gap', async () => {
    const compose = useQuestionCompose()
    compose.setKnowledgePoints([
      { id: 'k-1', name: '考点一' },
      { id: 'k-2', name: '考点二' },
    ])
    compose.selectedTypes.value = ['single_choice']

    await compose.generate()

    expect(compose.questions.value).toHaveLength(2)
    expect(compose.canStart.value).toBe(true)
    expect(compose.coverage.value.missing).toEqual([])

    compose.removeQuestion(compose.questions.value[0])

    expect(compose.coverage.value.missing).toEqual(['k-1'])
    expect(compose.canStart.value).toBe(false)
    expect(compose.generationNotice.value).toContain('未覆盖')
  })

  it('fills the coverage gap by generating for the missing points only', async () => {
    const compose = useQuestionCompose()
    compose.setKnowledgePoints([
      { id: 'k-1', name: '考点一' },
      { id: 'k-2', name: '考点二' },
    ])

    await compose.generate()
    compose.removeQuestion(compose.questions.value.find((item) => item.knowledge_point_id === 'k-2')!)
    expect(compose.canStart.value).toBe(false)

    await compose.fillCoverageGap()

    expect(compose.coverage.value.missing).toEqual([])
    expect(compose.canStart.value).toBe(true)
  })
})

/**
 * 出题页曾经把「生成成功」和「切到核对视图」之间的连接漏掉：`isConfigMode` 只被写过 true，
 * 于是生成的题目永远渲染不出来，用户看到的是「点了没反应」。
 * 修复把这条连接放在 `generate()` 的返回值上——下面锁定该返回值契约，
 * 使「零合格题/失败」不可能被误当成「可以进核对视图」。
 */
describe('question compose reports generated count to the caller', () => {
  beforeEach(() => {
    requestMock.mockReset()
  })

  const respondWithQualified = (knowledgePointIds: string[]) => {
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions/generate') {
        return {
          batch_id: 'b-1',
          total_generated: knowledgePointIds.length,
          qualified_count: knowledgePointIds.length,
          pending_count: 0,
          qualified_questions: knowledgePointIds.map((kpId) =>
            generatedQuestionFixture({ id: `q-${kpId}`, knowledge_point_id: kpId }),
          ),
          pending_questions: [],
        }
      }
      // 生成后回查批次摘要用于展示「本次生成批次」（标签与题库区块同一函数）
      if (options.url.startsWith('/questions/batches')) {
        return batchSummaryResponse('b-1', {
          availableCount: knowledgePointIds.length,
          materialTitle: '软件工程导论.pdf',
        })
      }
      throw new Error(`unexpected: ${options.url}`)
    })
  }

  it('returns the qualified count on success', async () => {
    respondWithQualified(['k-1', 'k-2'])
    const compose = useQuestionCompose()
    compose.setKnowledgePoints([
      { id: 'k-1', name: '考点一' },
      { id: 'k-2', name: '考点二' },
    ])
    compose.selectedTypes.value = ['single_choice']

    await expect(compose.generate()).resolves.toBe(2)
    expect(compose.questions.value).toHaveLength(2)
    expect(compose.canStart.value).toBe(true)
    // R5：核对出题页要显示本次生成的批次，标签走与题库区块同一份推导
    // （只断言时间之后的部分：年份由运行时刻决定，不写死会过期的完整串）
    expect(compose.generatedBatchLabels.value).toHaveLength(1)
    expect(compose.generatedBatchLabels.value[0]).toContain('软件工程导论.pdf · 2 题')
  })

  it('returns zero and stays out of the reviewable state when nothing qualifies', async () => {
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions/generate') {
        return {
          batch_id: 'b-1',
          total_generated: 0,
          qualified_count: 0,
          pending_count: 0,
          qualified_questions: [],
          pending_questions: [],
        }
      }
      throw new Error(`unexpected: ${options.url}`)
    })
    const compose = useQuestionCompose()
    compose.setKnowledgePoints([{ id: 'k-1', name: '考点一' }])

    await expect(compose.generate()).resolves.toBe(0)
    expect(compose.questions.value).toEqual([])
    expect(compose.canStart.value).toBe(false)
  })

  it('returns zero instead of throwing when generation fails', async () => {
    requestMock.mockImplementation(async (options: any) => {
      throw new Error(`upstream down: ${options.url}`)
    })
    const compose = useQuestionCompose()
    compose.setKnowledgePoints([{ id: 'k-1', name: '考点一' }])

    await expect(compose.generate()).resolves.toBe(0)
    expect(compose.questions.value).toEqual([])
    expect(compose.canStart.value).toBe(false)
  })

  it('returns zero and generates nothing when no point is selected', async () => {
    const compose = useQuestionCompose()

    await expect(compose.generate()).resolves.toBe(0)
    expect(requestMock).not.toHaveBeenCalled()
  })
})

/**
 * 「继续核对已生成题目」入口的载入契约：选中考点必须取自题目实际覆盖的集合，
 * 否则覆盖率会凭空出现缺口，把用户挡在「开始作答」之外。
 */
describe('loading already generated questions', () => {
  beforeEach(() => {
    requestMock.mockReset()
  })

  it('selects exactly the points the loaded questions cover', async () => {
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions?material_id=m-1') {
        return {
          items: [
            generatedQuestionFixture({ id: 'q-2', knowledge_point_id: 'k-2' }),
            generatedQuestionFixture({ id: 'q-1', knowledge_point_id: 'k-1' }),
          ],
        }
      }
      throw new Error(`unexpected: ${options.url}`)
    })
    const compose = useQuestionCompose()

    await expect(compose.loadExistingQuestions('m-1')).resolves.toBe(2)
    expect(compose.questions.value).toHaveLength(2)
    expect([...compose.selectedKpIds.value].sort()).toEqual(['k-1', 'k-2'])
    expect(compose.coverage.value.missing).toEqual([])
    expect(compose.canStart.value).toBe(true)
  })

  it('reports zero and keeps the config view when nothing was persisted', async () => {
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions?material_id=m-empty') return { items: [] }
      throw new Error(`unexpected: ${options.url}`)
    })
    const compose = useQuestionCompose()

    await expect(compose.loadExistingQuestions('m-empty')).resolves.toBe(0)
    expect(compose.questions.value).toEqual([])
    expect(compose.canStart.value).toBe(false)
  })

  it('accepts a bare array response as well as the items envelope', async () => {
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions?material_id=m-2') {
        return [generatedQuestionFixture({ id: 'q-9', knowledge_point_id: 'k-9' })]
      }
      throw new Error(`unexpected: ${options.url}`)
    })
    const compose = useQuestionCompose()

    await expect(compose.loadExistingQuestions('m-2')).resolves.toBe(1)
    expect(compose.canStart.value).toBe(true)
  })
})
