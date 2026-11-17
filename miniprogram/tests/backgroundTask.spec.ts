import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import BackgroundTaskBar from '@/components/BackgroundTaskBar.vue'
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
    const store = useBackgroundTaskStore()
    store.trackQuestionJob({
      id: 'job-done',
      status: 'completed',
      material_id: 'm-9',
      folder_id: null,
      total_kps: 3,
      completed_kps: 3,
      generated_count: 5,
      batch_id: 'b-9',
      question_ids: ['q-1'],
      error_message: null,
      created_at: '',
      updated_at: '',
      completed_at: '2026-11-17T10:00:00',
    })

    const wrapper = mount(BackgroundTaskBar)
    expect(wrapper.text()).toContain('去查看')
    await wrapper.find('.task-action-btn').trigger('tap')
    expect(navSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/subpackages/material/pages/questions/index?material_id=m-9&view=generated&batch_id=b-9',
      }),
    )
    expect(store.visibleTasks).toEqual([])
    wrapper.unmount()

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
})
