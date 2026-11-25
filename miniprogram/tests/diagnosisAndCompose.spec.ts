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
  groupComposeKps,
  sampleKnowledgePointIds,
  selectLeafComposePoints,
} from '@/subpackages/material/utils/composeHelpers'
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

  it('defaults to smart_sample mode, honors questionCount via cross-group sampling, and supports full_coverage with 50-limit guard', () => {
    const compose = useQuestionCompose()
    compose.setKnowledgePoints([
      { id: 'ch-1', name: '第一章 概率基础', level: 1, parent_id: null, sort_order: 1 },
      { id: 'k-1', name: '考点一', level: 2, parent_id: 'ch-1', sort_order: 1 },
      { id: 'k-2', name: '考点二', level: 2, parent_id: 'ch-1', sort_order: 2 },
      { id: 'k-3', name: '考点三', level: 2, parent_id: 'ch-1', sort_order: 3 },
      { id: 'ch-2', name: '第二章 线性模型', level: 1, parent_id: null, sort_order: 2 },
      { id: 'k-4', name: '考点四', level: 2, parent_id: 'ch-2', sort_order: 1 },
      { id: 'k-5', name: '考点五', level: 2, parent_id: 'ch-2', sort_order: 2 },
      { id: 'k-6', name: '考点六', level: 2, parent_id: 'ch-2', sort_order: 3 },
      { id: 'k-7', name: '独立考点七', level: 1, parent_id: null, sort_order: 3 },
    ])
    compose.questionCount.value = 3

    // L1 章节容器 ch-1/ch-2 被过滤，仅保留 7 个叶子/独立考点
    expect(compose.availableKpList.value).toHaveLength(7)
    expect(compose.selectedKpIds.value).toHaveLength(7)
    expect(compose.composeMode.value).toBe('smart_sample')
    expect(compose.plannedCount.value).toBe(3)
    expect(compose.effectiveKpIds.value).toEqual(['k-1', 'k-4', 'k-7'])

    // 切换全考点覆盖模式后，plannedCount 抬升至已选考点数
    compose.setComposeMode('full_coverage')
    expect(compose.plannedCount.value).toBe(7)
    expect(compose.effectiveKpIds.value).toHaveLength(7)
    expect(compose.exceedsPracticeLimit.value).toBe(false)

    // 超过 50 个考点在全覆盖模式下触发上限阻断
    const fiftyOne = Array.from({ length: 51 }, (_, idx) => ({
      id: `bulk-${idx + 1}`,
      name: `大批量考点-${idx + 1}`,
      level: 1,
      sort_order: idx + 1,
    }))
    compose.setKnowledgePoints(fiftyOne)
    expect(compose.exceedsPracticeLimit.value).toBe(true)
    compose.setComposeMode('smart_sample')
    expect(compose.exceedsPracticeLimit.value).toBe(false)
  })

  it('filters L1 container nodes, samples deterministically across groups, and paginates >100 batch questions', async () => {
    const rawOptions = [
      { id: 'c1', name: '第一章', level: 1, parent_id: null, sort_order: 1 },
      { id: 'p1', name: '子考点1', level: 2, parent_id: 'c1', sort_order: 1 },
      { id: 'p2', name: '子考点2', level: 2, parent_id: 'c1', sort_order: 2 },
      { id: 'c2', name: '第二章', level: 1, parent_id: null, sort_order: 2 },
      { id: 'p3', name: '子考点3', level: 2, parent_id: 'c2', sort_order: 1 },
      { id: 'p4', name: '子考点4', level: 2, parent_id: 'c2', sort_order: 2 },
    ]
    expect(selectLeafComposePoints(rawOptions).map((p) => p.id)).toEqual(['p1', 'p2', 'p3', 'p4'])
    const groups = groupComposeKps(rawOptions)
    expect(groups.map((g) => g.points.map((p) => p.id))).toEqual([
      ['p1', 'p2'],
      ['p3', 'p4'],
    ])
    expect(sampleKnowledgePointIds(groups, ['p1', 'p2', 'p3', 'p4'], 3)).toEqual(['p1', 'p3', 'p2'])

    // 超过分组数的抽样应跨全部分组均匀分布
    const manyGroups = Array.from({ length: 6 }, (_, i) => ({
      id: `g-${i}`,
      title: `G${i}`,
      points: [{ id: `kp-${i}`, name: `KP${i}` }],
    }))
    expect(sampleKnowledgePointIds(manyGroups, manyGroups.map((g) => g.points[0].id), 3)).toEqual([
      'kp-0',
      'kp-2',
      'kp-4',
    ])

    // 验证 fetchBatchQuestions 使用 page_size=100 并在 total > 100 时继续翻页，不截断于 50 题
    const page1 = Array.from({ length: 100 }, (_, i) =>
      generatedQuestionFixture({ id: `q-${i + 1}`, knowledge_point_id: `kp-${i + 1}`, batch_id: 'b-big' }),
    )
    const page2 = Array.from({ length: 10 }, (_, i) =>
      generatedQuestionFixture({ id: `q-${101 + i}`, knowledge_point_id: `kp-${101 + i}`, batch_id: 'b-big' }),
    )
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions?batch_id=b-big&page=1&page_size=100') {
        return { items: page1, total: 110 }
      }
      if (options.url === '/questions?batch_id=b-big&page=2&page_size=100') {
        return { items: page2, total: 110 }
      }
      if (options.url.startsWith('/questions/batches')) {
        return batchSummaryResponse('b-big', { availableCount: 110 })
      }
      throw new Error(`unexpected: ${options.url}`)
    })
    const compose = useQuestionCompose()
    await expect(compose.loadBatchQuestions('b-big')).resolves.toBe(110)
    expect(compose.questions.value).toHaveLength(110)
  })

  it('dispatches a single async job up to 50 KPs with auto_create_practice and source_type initial_compose', async () => {
    const jobPayloads: Array<Record<string, any>> = []
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions/jobs' && options.method === 'POST') {
        const kpIds: string[] = options.data.knowledge_point_ids || []
        jobPayloads.push(options.data)
        return {
          id: 'job-single-25',
          status: 'completed',
          material_id: 'm-1',
          total_kps: kpIds.length,
          completed_kps: kpIds.length,
          generated_count: kpIds.length,
          batch_id: 'b-single-25',
          result_practice_id: 'p-single-25',
          source_type: options.data.source_type,
          practice_title: options.data.practice_title,
          question_ids: kpIds.map((id) => `q-${id}`),
          created_at: '',
          updated_at: '',
          completed_at: '2026-11-17T10:00:00',
        }
      }
      if (options.url.startsWith('/questions?batch_id=b-single-25')) {
        return {
          items: jobPayloads[0].knowledge_point_ids.map((kpId: string) =>
            generatedQuestionFixture({ id: `q-${kpId}`, knowledge_point_id: kpId, batch_id: 'b-single-25' }),
          ),
        }
      }
      if (options.url.startsWith('/questions/batches')) return { items: [], total: 0 }
      throw new Error(`unexpected: ${options.url}`)
    })

    const compose = useQuestionCompose()
    compose.setScope({ materialId: 'm-1' })
    compose.setKnowledgePoints(
      Array.from({ length: 25 }, (_, i) => ({ id: `kp-${i + 1}`, name: `考点-${i + 1}`, level: 1 })),
    )
    compose.setComposeMode('full_coverage')

    await expect(compose.generate()).resolves.toBe(25)
    expect(jobPayloads).toHaveLength(1)
    expect(jobPayloads[0].knowledge_point_ids).toHaveLength(25)
    expect(jobPayloads[0].count).toBe(25)
    expect(jobPayloads[0]).toMatchObject({
      auto_create_practice: true,
      source_type: 'initial_compose',
    })
    expect(compose.readyPracticeId.value).toBe('p-single-25')
    expect(compose.viewMode.value).toBe('ready')
    expect(compose.canStart.value).toBe(true)
  })

  it('never blocks starting practice when partial items are pending_review or missing KP coverage', async () => {
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions/jobs' && options.method === 'POST') {
        return {
          id: 'job-partial',
          status: 'completed',
          material_id: 'm-1',
          total_kps: 2,
          completed_kps: 2,
          generated_count: 1,
          batch_id: 'b-partial',
          result_practice_id: 'p-partial',
          source_type: 'initial_compose',
          question_ids: ['q-1'],
          created_at: '',
          updated_at: '',
          completed_at: '2026-11-17T10:00:01',
        }
      }
      if (options.url.startsWith('/questions?batch_id=b-partial')) {
        return {
          items: [
            generatedQuestionFixture({ id: 'q-1', knowledge_point_id: 'k-1', batch_id: 'b-partial', status: 'available' }),
            generatedQuestionFixture({ id: 'q-2', knowledge_point_id: 'k-2', batch_id: 'b-partial', status: 'pending_review' }),
          ],
        }
      }
      if (options.url.startsWith('/questions/batches')) return batchSummaryResponse('b-partial')
      throw new Error(`unexpected: ${options.url}`)
    })

    const compose = useQuestionCompose()
    compose.setScope({ materialId: 'm-1' })
    compose.setKnowledgePoints([
      { id: 'k-1', name: '考点一' },
      { id: 'k-2', name: '考点二' },
    ])
    compose.selectedTypes.value = ['single_choice']

    await expect(compose.generate()).resolves.toBe(1)

    expect(compose.questions.value).toHaveLength(1)
    expect(compose.readyAvailableCount.value).toBe(1)
    expect(compose.readyPendingCount.value).toBe(0)
    expect(compose.generationNotice.value).not.toContain('待审核')
    expect(compose.coverage.value.missing).toEqual(['k-2'])
    expect(compose.canStart.value).toBe(true)
    expect(compose.viewMode.value).toBe('ready')
    expect(requestMock.mock.calls.some(([o]: any[]) => o.url === '/questions/generate')).toBe(false)
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
