import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useDiagnosisStore } from '@/stores/diagnosis'
import { useQuestionCompose } from '@/subpackages/material/composables/useQuestionCompose'
import {
  diagnosisReportFixture,
  generatedQuestionFixture,
  practiceDetailFixture,
} from './fixtures/backendResponses'

const completedSession = {
  ...practiceDetailFixture,
  status: 'completed',
  completed_at: '2026-09-28T12:00:00',
}

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

describe('question compose async job flow & coverage gating', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
  })

  afterEach(() => {
    useBackgroundTaskStore().reset()
  })

  it('raises the planned count to cover all selected points without capping', () => {
    const compose = useQuestionCompose()
    compose.setKnowledgePoints([
      { id: 'k-1', name: '考点一' },
      { id: 'k-2', name: '考点二' },
      { id: 'k-3', name: '考点三' },
      { id: 'k-4', name: '考点四' },
      { id: 'k-5', name: '考点五' },
      { id: 'k-6', name: '考点六' },
      { id: 'k-7', name: '考点七' },
    ])
    compose.questionCount.value = 1

    expect(compose.selectedKpIds.value).toHaveLength(7)
    expect(compose.plannedCount.value).toBe(7)
  })

  it('submits async job, blocks starting on removal gap, and fills missing KPs asynchronously', async () => {
    let jobCounter = 0
    const batchItemsByBatch: Record<string, any[]> = {}

    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions/jobs' && options.method === 'POST') {
        jobCounter += 1
        const kpIds: string[] = options.data.knowledge_point_ids || []
        const batchId = `b-${jobCounter}`
        batchItemsByBatch[batchId] = kpIds.map((kpId, index) =>
          generatedQuestionFixture({
            id: `q-${jobCounter}-${kpId}`,
            knowledge_point_id: kpId,
            batch_id: batchId,
            stem: `题干-${index}`,
          }),
        )
        return {
          id: `job-${jobCounter}`,
          status: 'completed',
          material_id: options.data.material_id ?? null,
          folder_id: options.data.folder_id ?? null,
          total_kps: kpIds.length,
          completed_kps: kpIds.length,
          generated_count: kpIds.length,
          batch_id: batchId,
          question_ids: batchItemsByBatch[batchId].map((q) => q.id),
          created_at: '2026-11-17T10:00:00',
          updated_at: '2026-11-17T10:00:01',
          completed_at: '2026-11-17T10:00:01',
        }
      }
      if (options.url.startsWith('/questions?batch_id=')) {
        const match = /batch_id=([^&]+)/.exec(options.url)
        const batchId = match ? decodeURIComponent(match[1]) : ''
        return { items: batchItemsByBatch[batchId] || [] }
      }
      if (options.url.startsWith('/questions/batches')) return batchSummaryResponse('b-1')
      throw new Error(`unexpected: ${options.url}`)
    })

    const compose = useQuestionCompose()
    compose.setScope({ materialId: 'm-1' })
    compose.setKnowledgePoints([
      { id: 'k-1', name: '考点一' },
      { id: 'k-2', name: '考点二' },
    ])
    compose.selectedTypes.value = ['single_choice']

    await expect(compose.generate()).resolves.toBe(2)

    expect(compose.questions.value).toHaveLength(2)
    expect(compose.questions.value[0].knowledge_point_name).toBe('考点一')
    expect(compose.canStart.value).toBe(true)
    expect(compose.coverage.value.missing).toEqual([])
    expect(requestMock.mock.calls.some(([o]: any[]) => o.url === '/questions/generate')).toBe(false)

    compose.removeQuestion(compose.questions.value[0])
    expect(compose.coverage.value.missing).toEqual(['k-1'])
    expect(compose.canStart.value).toBe(false)
    expect(compose.generationNotice.value).toContain('未覆盖')

    await compose.fillCoverageGap()
    expect(compose.coverage.value.missing).toEqual([])
    expect(compose.canStart.value).toBe(true)
  })

  it('handles queued->running->completed async jobs non-blockingly and loads batch summary', async () => {
    let pollStep = 0
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions/jobs' && options.method === 'POST') {
        return {
          id: 'job-async',
          status: 'queued',
          material_id: 'm-1',
          total_kps: 2,
          completed_kps: 0,
          generated_count: 0,
          question_ids: [],
          created_at: '',
          updated_at: '',
        }
      }
      if (options.url === '/questions/jobs/job-async' && options.method === 'GET') {
        pollStep += 1
        if (pollStep === 1) {
          return {
            id: 'job-async',
            status: 'running',
            material_id: 'm-1',
            total_kps: 2,
            completed_kps: 1,
            generated_count: 1,
            question_ids: [],
            created_at: '',
            updated_at: '',
          }
        }
        return {
          id: 'job-async',
          status: 'completed',
          material_id: 'm-1',
          total_kps: 2,
          completed_kps: 2,
          generated_count: 2,
          batch_id: 'b-async',
          question_ids: ['q-k-1', 'q-k-2'],
          created_at: '',
          updated_at: '',
          completed_at: '2026-11-17T10:00:10',
        }
      }
      if (options.url.startsWith('/questions?batch_id=b-async')) {
        return {
          items: [
            generatedQuestionFixture({ id: 'q-k-1', knowledge_point_id: 'k-1', batch_id: 'b-async' }),
            generatedQuestionFixture({ id: 'q-k-2', knowledge_point_id: 'k-2', batch_id: 'b-async' }),
          ],
        }
      }
      if (options.url.startsWith('/questions/batches')) {
        return batchSummaryResponse('b-async', {
          availableCount: 2,
          materialTitle: '软件工程导论.pdf',
        })
      }
      throw new Error(`unexpected: ${options.url}`)
    })

    const taskStore = useBackgroundTaskStore()
    const compose = useQuestionCompose()
    compose.setScope({ materialId: 'm-1' })
    compose.setKnowledgePoints([
      { id: 'k-1', name: '考点一' },
      { id: 'k-2', name: '考点二' },
    ])

    // 异步排队时立即返回 0，不阻塞当前页；进度提示立即可见
    await expect(compose.generate()).resolves.toBe(0)
    expect(compose.isJobInFlight.value).toBe(true)
    expect(compose.jobProgressText.value).toContain('0 / 2 考点')

    await taskStore.pollOnce()
    expect(compose.jobProgressText.value).toContain('1 / 2 考点')

    await taskStore.pollOnce()
    expect(compose.activeJob.value?.status).toBe('completed')

    await expect(compose.applyCompletedJob(compose.activeJob.value!)).resolves.toBe(2)
    expect(compose.questions.value).toHaveLength(2)
    expect(compose.canStart.value).toBe(true)
    expect(compose.generatedBatchLabels.value[0]).toContain('软件工程导论.pdf · 2 题')
  })

  it('returns zero and stays out of reviewable state when job fails, produces nothing, or nothing selected', async () => {
    const composeEmpty = useQuestionCompose()
    await expect(composeEmpty.generate()).resolves.toBe(0)
    expect(requestMock).not.toHaveBeenCalled()

    requestMock.mockRejectedValueOnce(new Error('upstream down'))
    const composeErr = useQuestionCompose()
    composeErr.setKnowledgePoints([{ id: 'k-1', name: '考点一' }])
    await expect(composeErr.generate()).resolves.toBe(0)
    expect(composeErr.questions.value).toEqual([])
    expect(composeErr.canStart.value).toBe(false)

    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions/jobs') {
        return {
          id: 'job-empty',
          status: 'completed',
          material_id: 'm-1',
          total_kps: 1,
          completed_kps: 1,
          generated_count: 0,
          batch_id: 'b-empty',
          question_ids: [],
        }
      }
      if (options.url.startsWith('/questions?batch_id=b-empty')) {
        return { items: [] }
      }
      throw new Error(`unexpected: ${options.url}`)
    })
    await expect(composeErr.generate()).resolves.toBe(0)
    expect(composeErr.questions.value).toEqual([])
    expect(composeErr.canStart.value).toBe(false)
  })
})

describe('loading already generated questions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
  })

  afterEach(() => {
    useBackgroundTaskStore().reset()
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
