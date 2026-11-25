import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import BackgroundTaskBar from '@/components/BackgroundTaskBar.vue'
import { useAuthStore } from '@/stores/auth'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useMaterialStore } from '@/stores/material'

describe('useBackgroundTaskStore & BackgroundTaskBar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
  })

  afterEach(() => {
    const store = useBackgroundTaskStore()
    store.reset()
    vi.restoreAllMocks()
  })

  it('tracks material parse with optional force=true and updates to ready on poll', async () => {
    requestMock.mockImplementation(async ({ url, method }: { url: string; method?: string }) => {
      if (url === '/materials/m-1/parse?force=true' && method === 'POST') {
        return { message: 'queued' }
      }
      if (url === '/materials/m-1' && method === 'GET') {
        return {
          id: 'm-1',
          title: '贝叶斯分类器.pdf',
          status: 'ready',
          parse_status: 'ready',
          progress_percentage: 100,
          created_at: '2026-11-17T00:00:00',
        }
      }
      throw new Error(`unexpected: ${url}`)
    })

    const matStore = useMaterialStore()
    matStore.materialList = [
      { id: 'm-1', title: '贝叶斯分类器.pdf', status: 'pending', created_at: '2026-11-17T00:00:00' },
    ]

    const store = useBackgroundTaskStore()
    await store.startMaterialParse('m-1', '贝叶斯分类器.pdf', true)

    expect(store.activeMaterialIds).toEqual(['m-1'])
    expect(store.visibleTasks[0]).toMatchObject({
      key: 'mat:m-1',
      status: 'active',
      dismissible: false,
    })

    const done = await store.pollOnce()
    expect(done).toBe(true)
    expect(matStore.materialList[0].status).toBe('ready')
    expect(store.visibleTasks[0]).toMatchObject({
      key: 'mat:m-1',
      status: 'completed',
      actionLabel: '去查看',
      dismissible: true,
    })
  })

  it('tracks async question generation job progress and supports dismissing completed notices', async () => {
    let pollStep = 0
    requestMock.mockImplementation(async ({ url, method }: { url: string; method?: string }) => {
      if (url === '/questions/jobs' && method === 'POST') {
        return {
          id: 'job-1',
          status: 'queued',
          material_id: 'm-1',
          folder_id: null,
          total_kps: 7,
          completed_kps: 0,
          generated_count: 0,
          batch_id: null,
          question_ids: [],
          error_message: null,
          created_at: '2026-11-17T10:00:00',
          updated_at: '2026-11-17T10:00:00',
          completed_at: null,
        }
      }
      if (url === '/questions/jobs/job-1' && method === 'GET') {
        pollStep += 1
        if (pollStep === 1) {
          return {
            id: 'job-1',
            status: 'running',
            material_id: 'm-1',
            folder_id: null,
            total_kps: 7,
            completed_kps: 3,
            generated_count: 4,
            batch_id: null,
            question_ids: [],
            error_message: null,
            created_at: '2026-11-17T10:00:00',
            updated_at: '2026-11-17T10:00:10',
            completed_at: null,
          }
        }
        return {
          id: 'job-1',
          status: 'completed',
          material_id: 'm-1',
          folder_id: null,
          total_kps: 7,
          completed_kps: 7,
          generated_count: 9,
          batch_id: 'batch-1',
          question_ids: ['q-1', 'q-2'],
          error_message: null,
          created_at: '2026-11-17T10:00:00',
          updated_at: '2026-11-17T10:00:20',
          completed_at: '2026-11-17T10:00:20',
        }
      }
      throw new Error(`unexpected: ${url}`)
    })

    const store = useBackgroundTaskStore()
    await store.startQuestionJob({ material_id: 'm-1', knowledge_point_ids: ['k-1'], count: 9 })

    expect(store.visibleTasks[0].detailText).toContain('0/7')

    await store.ensurePolling(0, 5)

    expect(pollStep).toBe(2)
    expect(store.isPolling).toBe(false)
    expect(store.visibleTasks[0]).toMatchObject({
      key: 'job:job-1',
      status: 'completed',
      actionLabel: '去查看',
      dismissible: true,
    })
    expect(store.visibleTasks[0].detailText).toContain('9 题')

    store.dismissTask('job:job-1')
    expect(store.visibleTasks).toEqual([])
  })

  it('refreshes active tasks from backend lists and renders BackgroundTaskBar', async () => {
    requestMock.mockImplementation(async ({ url }: { url: string }) => {
      if (url === '/materials') {
        return {
          items: [
            { id: 'm-2', title: '降维算法.pdf', status: 'parsing', parse_status: 'ocr_processing', progress_percentage: 40, created_at: '' },
          ],
        }
      }
      if (url === '/questions/jobs?active_only=true') {
        return {
          items: [
            {
              id: 'job-2',
              status: 'running',
              material_id: 'm-1',
              total_kps: 5,
              completed_kps: 2,
              generated_count: 2,
              question_ids: [],
              created_at: '',
              updated_at: '',
            },
          ],
          total: 1,
        }
      }
      return {}
    })

    const store = useBackgroundTaskStore()
    await store.refreshActiveTasks()

    expect(store.visibleTasks).toHaveLength(2)
    const wrapper = mount(BackgroundTaskBar)
    expect(wrapper.text()).toContain('降维算法.pdf')
    expect(wrapper.text()).toContain('2/5 考点')
    wrapper.unmount()
  })

  it('handles open-task navigation and dismiss action on completed BackgroundTaskBar notices', async () => {
    const navSpy = vi.spyOn(uni, 'navigateTo')
    const switchTabSpy = vi.spyOn(uni, 'switchTab')
    const store = useBackgroundTaskStore()
    store.trackQuestionJob({
      id: 'job-done-practice',
      status: 'completed',
      material_id: 'm-9',
      folder_id: null,
      total_kps: 3,
      completed_kps: 3,
      generated_count: 5,
      batch_id: 'b-9',
      question_ids: ['q-1'],
      result_practice_id: 'p-ready-9',
      source_type: 'wrong_record',
      practice_title: '错题巩固练习',
      error_message: null,
      created_at: '',
      updated_at: '',
      completed_at: '2026-11-17T10:00:00',
    })

    const wrapper = mount(BackgroundTaskBar)
    expect(wrapper.text()).toContain('错题巩固卷已就绪')
    expect(wrapper.text()).toContain('立即作答')
    await wrapper.find('.task-action-btn').trigger('tap')
    expect(navSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/subpackages/practice/pages/session/index?practice_id=p-ready-9',
      }),
    )
    expect(store.visibleTasks).toEqual([])
    wrapper.unmount()

    store.trackQuestionJob({
      id: 'job-done-fallback',
      status: 'completed',
      material_id: 'm-9',
      folder_id: null,
      total_kps: 3,
      completed_kps: 3,
      generated_count: 2,
      batch_id: 'b-10',
      question_ids: ['q-2'],
      result_practice_id: null,
      error_message: null,
      created_at: '',
      updated_at: '',
      completed_at: '2026-11-17T10:00:00',
    })
    const wrapperFallback = mount(BackgroundTaskBar)
    await wrapperFallback.find('.task-action-btn').trigger('tap')
    expect(switchTabSpy).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/pages/review/index' }),
    )
    wrapperFallback.unmount()

    store.trackMaterialParse({
      id: 'm-10',
      title: '解析完了.pdf',
      status: 'ready',
      created_at: '',
    })
    const wrapper2 = mount(BackgroundTaskBar)
    await wrapper2.find('.task-dismiss-btn').trigger('tap')
    expect(store.visibleTasks).toEqual([])
    wrapper2.unmount()
  })

  it('uses >=15m staged polling, flags timedOut on exhaustion, and resumes via refreshMaterialTask', async () => {
    vi.useFakeTimers()
    try {
      let detailCalls = 0
      let readyAfterRefresh = false
      requestMock.mockImplementation(async ({ url, method }: { url: string; method?: string }) => {
        if (url.startsWith('/materials/m-slow/parse') && method === 'POST') {
          return { message: 'queued' }
        }
        if (url === '/materials/m-slow' && method === 'GET') {
          detailCalls += 1
          return {
            id: 'm-slow',
            title: '长文档.pdf',
            status: readyAfterRefresh ? 'ready' : 'parsing',
            parse_status: readyAfterRefresh ? 'ready' : 'extracting_knowledge',
            progress_percentage: readyAfterRefresh ? 100 : 60,
            created_at: '',
          }
        }
        if (url === '/questions/jobs/job-other') {
          return {
            id: 'job-other',
            status: 'running',
            material_id: 'm-2',
            total_kps: 2,
            completed_kps: 1,
            generated_count: 0,
            question_ids: [],
            created_at: '',
            updated_at: '',
          }
        }
        throw new Error(`unexpected: ${url}`)
      })

      const store = useBackgroundTaskStore()
      await store.startMaterialParse('m-slow', '长文档.pdf', false)
      // 取消 schedulePolling 的初始延迟 timer，直接测试 ensurePolling 分段退避
      store.stopPolling()

      const pollPromise = store.ensurePolling()
      // 48 * 2500ms + 157 * 5000ms = 905,000ms (> 15 分钟)
      await vi.advanceTimersByTimeAsync(910_000)
      await pollPromise

      expect(detailCalls).toBe(205)
      expect(store.materialTasks.get('m-slow')?.timedOut).toBe(true)
      expect(store.visibleTasks[0]).toMatchObject({
        key: 'mat:m-slow',
        timedOut: true,
        actionLabel: '刷新',
      })
      expect(store.visibleTasks[0].detailText).toContain('进度同步已暂停')

      // 手动刷新一次仍在解析中 -> 清除 timedOut 并重新调度轮询
      const stillParsing = await store.refreshMaterialTask('m-slow')
      expect(stillParsing?.status).toBe('parsing')
      expect(store.materialTasks.get('m-slow')?.timedOut).toBe(false)

      // 再次手动刷新且后端已就绪 -> 变为 ready
      readyAfterRefresh = true
      const done = await store.refreshMaterialTask('m-slow')
      expect(done?.status).toBe('ready')
      expect(store.activeMaterialIds).toEqual([])
    } finally {
      vi.useRealTimers()
    }
  })

  it('passes silentToast: true on polling/refreshActiveTasks, throttles poll concurrency <= 2, and removes 404/403 tasks', async () => {
    let inflight = 0
    let maxInflight = 0
    const pollOptions: any[] = []

    requestMock.mockImplementation(async (options: any) => {
      pollOptions.push(options)
      inflight += 1
      maxInflight = Math.max(maxInflight, inflight)
      await new Promise((r) => setTimeout(r, 5))
      inflight -= 1

      if (options.url === '/materials/m-404') {
        const err: any = new Error('not found')
        err.statusCode = 404
        throw err
      }
      if (options.url === '/questions/jobs/job-403') {
        const err: any = new Error('forbidden')
        err.statusCode = 403
        throw err
      }
      if (options.url.startsWith('/materials/')) {
        const id = options.url.split('/').pop()
        return { id, title: id, status: 'parsing', parse_status: 'ocr_processing', progress_percentage: 20, created_at: '' }
      }
      if (options.url.startsWith('/questions/jobs/')) {
        const id = options.url.split('/').pop()
        return { id, status: 'running', total_kps: 2, completed_kps: 1, generated_count: 1, question_ids: [], created_at: '', updated_at: '' }
      }
      return { items: [], total: 0 }
    })

    const store = useBackgroundTaskStore()
    store.trackMaterialParse({ id: 'm-1', title: 'M1', status: 'parsing', created_at: '' })
    store.trackMaterialParse({ id: 'm-404', title: 'M404', status: 'parsing', created_at: '' })
    store.trackQuestionJob({ id: 'job-1', status: 'running', total_kps: 2, completed_kps: 0, generated_count: 0, question_ids: [], created_at: '', updated_at: '' })
    store.trackQuestionJob({ id: 'job-403', status: 'running', total_kps: 2, completed_kps: 0, generated_count: 0, question_ids: [], created_at: '', updated_at: '' })
    store.stopPolling()

    await store.pollOnce()
    expect(maxInflight).toBeLessThanOrEqual(2)
    expect(pollOptions.every((opt) => opt.silentToast === true)).toBe(true)
    expect(store.materialTasks.has('m-404')).toBe(false)
    expect(store.questionJobs.has('job-403')).toBe(false)
    expect(store.materialTasks.has('m-1')).toBe(true)
    expect(store.questionJobs.has('job-1')).toBe(true)

    pollOptions.length = 0
    await store.refreshActiveTasks()
    expect(pollOptions.some((opt) => opt.url === '/materials' && opt.silentToast === true)).toBe(true)
    expect(pollOptions.some((opt) => opt.url.startsWith('/questions/jobs') && opt.silentToast === true)).toBe(true)
  })

  it('marks active questionJobs timedOut on exhaustion, supports refreshQuestionJob, and excludes active job in BackgroundTaskBar', async () => {
    vi.useFakeTimers()
    try {
      let completedAfterRefresh = false
      requestMock.mockImplementation(async ({ url }: { url: string }) => {
        if (url === '/questions/jobs/job-slow') {
          return {
            id: 'job-slow',
            status: completedAfterRefresh ? 'completed' : 'running',
            material_id: 'm-1',
            total_kps: 4,
            completed_kps: completedAfterRefresh ? 4 : 1,
            generated_count: completedAfterRefresh ? 4 : 0,
            result_practice_id: completedAfterRefresh ? 'p-slow-1' : null,
            source_type: 'initial_compose',
            question_ids: [],
            created_at: '',
            updated_at: '',
          }
        }
        if (url === '/questions/jobs/job-other') {
          return {
            id: 'job-other',
            status: 'running',
            material_id: 'm-2',
            total_kps: 2,
            completed_kps: 1,
            generated_count: 0,
            question_ids: [],
            created_at: '',
            updated_at: '',
          }
        }
        throw new Error(`unexpected: ${url}`)
      })

      const store = useBackgroundTaskStore()
      store.trackQuestionJob({
        id: 'job-slow',
        status: 'running',
        material_id: 'm-1',
        total_kps: 4,
        completed_kps: 0,
        generated_count: 0,
        source_type: 'initial_compose',
        question_ids: [],
        created_at: '',
        updated_at: '',
      })
      store.trackQuestionJob({
        id: 'job-other',
        status: 'running',
        material_id: 'm-2',
        total_kps: 2,
        completed_kps: 1,
        generated_count: 0,
        question_ids: [],
        created_at: '',
        updated_at: '',
      })
      store.stopPolling()

      const excludedBar = mount(BackgroundTaskBar, { props: { excludeJobId: 'job-slow' } })
      expect(excludedBar.text()).not.toContain('0/4 考点')
      expect(excludedBar.text()).toContain('1/2 考点')
      excludedBar.unmount()

      const pollPromise = store.ensurePolling(100, 2)
      await vi.advanceTimersByTimeAsync(500)
      await pollPromise

      expect(store.questionJobs.get('job-slow')?.timedOut).toBe(true)
      const slowItem = store.visibleTasks.find((t) => t.key === 'job:job-slow')
      expect(slowItem).toMatchObject({ timedOut: true, actionLabel: '刷新' })

      completedAfterRefresh = true
      const bar = mount(BackgroundTaskBar)
      const slowRefreshBtn = bar.findAll('.task-strip').find((el) => el.text().includes('进度同步已暂停'))?.find('.task-action-btn')
      expect(slowRefreshBtn).toBeDefined()
      await slowRefreshBtn!.trigger('tap')
      await vi.waitFor(() => {
        expect(store.questionJobs.get('job-slow')?.status).toBe('completed')
      })
      expect(store.questionJobs.get('job-slow')?.result_practice_id).toBe('p-slow-1')
      expect(bar.text()).toContain('试卷已就绪')
      expect(bar.text()).toContain('立即作答')
      bar.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('skips autoRefresh in BackgroundTaskBar when user is not logged in', async () => {
    const wrapper = mount(BackgroundTaskBar, { props: { autoRefresh: true } })
    await Promise.resolve()
    expect(requestMock).not.toHaveBeenCalled()
    wrapper.unmount()

    const authStore = useAuthStore()
    authStore.setToken('tok-bg')
    requestMock.mockResolvedValue({ items: [], total: 0 })
    const loggedInWrapper = mount(BackgroundTaskBar, { props: { autoRefresh: true } })
    await Promise.resolve()
    expect(requestMock).toHaveBeenCalled()
    loggedInWrapper.unmount()
  })
})
