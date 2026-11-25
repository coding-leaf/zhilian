import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  uploadFile: vi.fn(),
  loadCallbacks: [] as Array<(options: Record<string, string>) => Promise<void>>,
  showCallbacks: [] as Array<() => Promise<void>>,
  pullCallbacks: [] as Array<() => Promise<void>>,
  unloadCallbacks: [] as Array<() => void>,
}))

vi.mock('@/utils/request', () => ({
  request: mocks.request,
  uploadFile: mocks.uploadFile,
}))

vi.mock('@dcloudio/uni-app', () => ({
  onLoad: (cb: (options: Record<string, string>) => Promise<void>) => mocks.loadCallbacks.push(cb),
  onShow: (cb: () => Promise<void>) => mocks.showCallbacks.push(cb),
  onPullDownRefresh: (cb: () => Promise<void>) => mocks.pullCallbacks.push(cb),
  onUnload: (cb: () => void) => mocks.unloadCallbacks.push(cb),
}))

import ReportDetailPage from '@/subpackages/report/pages/detail/index.vue'
import { useReportDetail } from '@/subpackages/report/composables/useReportDetail'
import { useReviewCenter } from '@/pages/review/composables/useReviewCenter'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { usePracticeStore } from '@/stores/practice'
import { resetLoadingGuardForTest } from '@/utils/loadingGuard'
import { startWrongRegenerateJob } from '@/utils/questionGeneration'
import { practiceDetailFixture } from './fixtures/backendResponses'

describe('Async wrong-question regeneration (R1.1, R1.2)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    resetLoadingGuardForTest()
    mocks.request.mockReset()
    mocks.loadCallbacks.length = 0
    mocks.showCallbacks.length = 0
    mocks.pullCallbacks.length = 0
    mocks.unloadCallbacks.length = 0
  })

  afterEach(() => {
    useBackgroundTaskStore().reset()
    vi.restoreAllMocks()
    resetLoadingGuardForTest()
  })

  it('dispatches POST /questions/jobs with auto_create_practice from startWrongRegenerateJob without blocking or calling sync generate', async () => {
    const showLoadingSpy = vi.spyOn(uni as any, 'showLoading')
    const navSpy = vi.spyOn(uni, 'navigateTo')
    const redirectSpy = vi.spyOn(uni, 'redirectTo')

    mocks.request.mockImplementation(async (options: any) => {
      if (options.url === '/questions/jobs' && options.method === 'POST') {
        return {
          id: 'job-wrong-1',
          status: 'queued',
          folder_id: 'f-1',
          total_kps: 2,
          completed_kps: 0,
          generated_count: 0,
          question_ids: [],
          result_practice_id: null,
          source_type: 'wrong_record',
          source_practice_id: 'p-src-1',
          practice_title: '错题巩固练习',
          created_at: '',
          updated_at: '',
        }
      }
      throw new Error(`unexpected: ${options.url}`)
    })

    const job = await startWrongRegenerateJob({
      knowledgePointIds: ['kp-1', 'kp-2', 'kp-1'],
      scope: { folderId: 'f-1' },
      sourcePracticeId: 'p-src-1',
    })

    expect(job.id).toBe('job-wrong-1')
    expect(showLoadingSpy).not.toHaveBeenCalled()
    expect(navSpy).not.toHaveBeenCalled()
    expect(redirectSpy).not.toHaveBeenCalled()
    expect(mocks.request.mock.calls.some(([o]: any[]) => o.url === '/questions/generate')).toBe(false)

    const jobCall = mocks.request.mock.calls.find(([o]: any[]) => o.url === '/questions/jobs')?.[0]
    expect(jobCall.data).toMatchObject({
      folder_id: 'f-1',
      knowledge_point_ids: ['kp-1', 'kp-2'],
      count: 3,
      auto_create_practice: true,
      practice_title: '错题巩固练习',
      source_type: 'wrong_record',
      source_practice_id: 'p-src-1',
    })
  })

  it('mounts BackgroundTaskBar on report detail page and starts async wrong job non-blockingly without auto-redirect', async () => {
    const showLoadingSpy = vi.spyOn(uni as any, 'showLoading')
    const redirectSpy = vi.spyOn(uni, 'redirectTo')
    const toastSpy = vi.spyOn(uni, 'showToast')

    mocks.request.mockImplementation(async (options: any) => {
      if (options.url === '/materials' || options.url.startsWith('/questions/jobs?active_only=true')) {
        return { items: [], total: 0 }
      }
      if (options.url === '/practices/p-report-1') {
        return {
          ...practiceDetailFixture,
          id: 'p-report-1',
          practice_id: 'p-report-1',
          folder_id: 'f-1',
          status: 'completed',
          completed_at: '2026-11-24T10:00:00',
          items: [
            {
              attempt_item_id: 'ai-1',
              question_id: 'q-1',
              order_index: 1,
              status: 'graded',
              is_answered: true,
              is_correct: false,
              score: 0,
              max_score: 2,
              question_snapshot: {
                id: 'q-1',
                question_type: 'single_choice',
                knowledge_point_id: 'kp-wrong-1',
                stem: '错题',
              },
            },
          ],
        }
      }
      if (options.url === '/practices/p-report-1/diagnosis') {
        return {
          id: 'd-1',
          practice_id: 'p-report-1',
          total_score: 0,
          max_score: 2,
          score_rate: 0,
          wrong_count: 1,
          weak_knowledge_points: [],
        }
      }
      if (options.url === '/questions/jobs' && options.method === 'POST') {
        return {
          id: 'job-rep-1',
          status: 'queued',
          folder_id: 'f-1',
          total_kps: 1,
          completed_kps: 0,
          generated_count: 0,
          question_ids: [],
          source_type: 'wrong_record',
          source_practice_id: 'p-report-1',
          practice_title: '错题巩固练习',
          created_at: '',
          updated_at: '',
        }
      }
      throw new Error(`unexpected: ${options.url}`)
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(ReportDetailPage, {
      global: {
        plugins: [pinia],
        stubs: {
          'rich-text': true,
          AiCoachDrawer: true,
          BackgroundTaskBar: {
            props: { autoRefresh: Boolean },
            template: '<div class="task-bar-stub" :data-auto="String(autoRefresh)" />',
          },
        },
      },
    })

    await mocks.loadCallbacks[0]({ practice_id: 'p-report-1' })
    await flushPromises()

    expect(wrapper.find('.task-bar-stub').exists()).toBe(true)
    expect(wrapper.find('.task-bar-stub').attributes('data-auto')).toBe('true')

    const adaptiveBtn = wrapper.findAll('button').find((b) => b.text().includes('错题针对性生题'))
    expect(adaptiveBtn).toBeDefined()
    await adaptiveBtn!.trigger('tap')
    await flushPromises()

    expect(showLoadingSpy.mock.calls.some((call) => String((call[0] as any)?.title).includes('生成中'))).toBe(false)
    expect(redirectSpy).not.toHaveBeenCalled()
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ title: '已在后台生成错题巩固卷，完成后顶部提醒' }),
    )
    expect(wrapper.text()).toContain('后台生题中...')
    wrapper.unmount()
  })

  it('does not clobber active gradingPoller when loadReportIfGraded runs (P2-9)', async () => {
    let sessionCalls = 0
    mocks.request.mockImplementation(async (options: any) => {
      if (options.url === '/practices/p-grade-1') {
        sessionCalls += 1
        return {
          ...practiceDetailFixture,
          id: 'p-grade-1',
          practice_id: 'p-grade-1',
          status: sessionCalls >= 2 ? 'completed' : 'submitted',
          completed_at: sessionCalls >= 2 ? '2026-11-24T10:00:05' : null,
          items: [
            {
              attempt_item_id: 'ai-1',
              question_id: 'q-1',
              order_index: 1,
              status: sessionCalls >= 2 ? 'graded' : 'answered',
              is_answered: true,
              score: sessionCalls >= 2 ? 5 : null,
              max_score: 5,
              question_snapshot: { id: 'q-1', question_type: 'short_answer', stem: '简答' },
            },
          ],
        }
      }
      if (options.url === '/practices/p-grade-1/diagnosis') {
        return { id: 'd-2', practice_id: 'p-grade-1', total_score: 5, max_score: 5, wrong_count: 0 }
      }
      throw new Error(`unexpected: ${options.url}`)
    })

    const detail = useReportDetail()
    detail.practiceId.value = 'p-grade-1'
    const practiceStore = usePracticeStore()
    await practiceStore.refreshSession('p-grade-1')

    const pollPromise = detail.pollGrading()
    // Simulate concurrent report check while grading poller is active
    await detail.loadReportIfGraded()
    await pollPromise

    expect(detail.fullyGraded.value).toBe(true)
    expect(detail.report.value?.id).toBe('d-2')
  })

  it('triggers async POST /questions/jobs from review wrong-book batch & single KP regenerate', async () => {
    const showLoadingSpy = vi.spyOn(uni as any, 'showLoading')
    const navSpy = vi.spyOn(uni, 'navigateTo')
    const jobPayloads: any[] = []

    mocks.request.mockImplementation(async (options: any) => {
      if (options.url === '/questions/jobs' && options.method === 'POST') {
        jobPayloads.push(options.data)
        return {
          id: `job-rev-${jobPayloads.length}`,
          status: 'queued',
          folder_id: options.data.folder_id ?? null,
          material_id: options.data.material_id ?? null,
          total_kps: options.data.knowledge_point_ids.length,
          completed_kps: 0,
          generated_count: 0,
          question_ids: [],
          source_type: options.data.source_type,
          practice_title: options.data.practice_title,
          created_at: '',
          updated_at: '',
        }
      }
      throw new Error(`unexpected: ${options.url}`)
    })

    const review = useReviewCenter()
    review.groupOptions.value = [
      { key: 'folder:f-1', label: '机器学习', folderId: 'f-1', count: 1, unclassified: false },
    ]
    review.selectedGroupKey.value = 'folder:f-1'
    review.wrongRecords.value = [
      {
        id: 'w-1',
        folder_id: 'f-1',
        material_id: 'm-1',
        practice_id: null,
        attempt_item_id: null,
        question_id: null,
        knowledge_point_id: 'kp-1',
        is_mastered: false,
        wrong_count: 1,
        question_snapshot: { stem: '错题', question_type: 'single_choice' },
      },
    ]

    await review.handleBatchRegenerate()
    // Active wrong_record job guards duplicate trigger while in flight
    await review.handleSingleKpPractice(review.wrongRecords.value[0])
    expect(jobPayloads).toHaveLength(1)

    // Once previous job completes, single KP regenerate also dispatches async job
    useBackgroundTaskStore().trackQuestionJob({
      id: 'job-rev-1',
      status: 'completed',
      folder_id: 'f-1',
      total_kps: 1,
      completed_kps: 1,
      generated_count: 3,
      question_ids: ['q-1'],
      result_practice_id: 'p-rev-1',
      source_type: 'wrong_record',
      created_at: '',
      updated_at: '',
    })
    await review.handleSingleKpPractice(review.wrongRecords.value[0])

    expect(jobPayloads).toHaveLength(2)
    expect(jobPayloads[0]).toMatchObject({
      folder_id: 'f-1',
      knowledge_point_ids: ['kp-1'],
      auto_create_practice: true,
      source_type: 'wrong_record',
    })
    expect(jobPayloads[1]).toMatchObject({
      folder_id: 'f-1',
      knowledge_point_ids: ['kp-1'],
      auto_create_practice: true,
      source_type: 'wrong_record',
    })
    expect(showLoadingSpy).not.toHaveBeenCalled()
    expect(navSpy).not.toHaveBeenCalled()
  })
})
