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
