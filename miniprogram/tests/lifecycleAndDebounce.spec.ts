import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const hooks = vi.hoisted(() => ({
  request: vi.fn(),
  uploadFile: vi.fn(),
  launchCbs: [] as Array<() => void>,
  showCbs: [] as Array<() => void>,
  hideCbs: [] as Array<() => void>,
  loadCbs: [] as Array<(options: Record<string, string>) => Promise<void>>,
  unloadCbs: [] as Array<() => void>,
  pullCbs: [] as Array<() => Promise<void>>,
}))

vi.mock('@/utils/request', () => ({
  request: (options: any) => hooks.request(options),
  uploadFile: (...args: any[]) => hooks.uploadFile(...args),
}))

vi.mock('@dcloudio/uni-app', () => ({
  onLaunch: (cb: () => void) => hooks.launchCbs.push(cb),
  onShow: (cb: () => void) => hooks.showCbs.push(cb),
  onHide: (cb: () => void) => hooks.hideCbs.push(cb),
  onLoad: (cb: (options: Record<string, string>) => Promise<void>) => hooks.loadCbs.push(cb),
  onUnload: (cb: () => void) => hooks.unloadCbs.push(cb),
  onPullDownRefresh: (cb: () => Promise<void>) => hooks.pullCbs.push(cb),
}))

import AppVue from '@/App.vue'
import IndexPage from '@/pages/index/index.vue'
import SessionPage from '@/subpackages/practice/pages/session/index.vue'
import { useAuthStore } from '@/stores/auth'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { usePracticeStore } from '@/stores/practice'
import { resetLoadingGuardForTest } from '@/utils/loadingGuard'

let wrapper: VueWrapper | undefined

const resetHookBuffers = () => {
  hooks.launchCbs.length = 0
  hooks.showCbs.length = 0
  hooks.hideCbs.length = 0
  hooks.loadCbs.length = 0
  hooks.unloadCbs.length = 0
  hooks.pullCbs.length = 0
}

describe('App lifecycle polling, homepage cold-start dedup & session text debounce', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    resetLoadingGuardForTest()
    hooks.request.mockReset()
    hooks.uploadFile.mockReset()
    resetHookBuffers()
  })

  afterEach(() => {
    useBackgroundTaskStore().reset()
    wrapper?.unmount()
    wrapper = undefined
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('App.vue pauses backgroundTask polling onHide and resumes onShow when logged in', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const authStore = useAuthStore()
    const bgStore = useBackgroundTaskStore()
    const stopSpy = vi.spyOn(bgStore, 'stopPolling')
    const refreshSpy = vi.spyOn(bgStore, 'refreshActiveTasks').mockResolvedValue(undefined)

    wrapper = mount(AppVue, { global: { plugins: [pinia] } })
    expect(hooks.hideCbs).toHaveLength(1)
    expect(hooks.showCbs).toHaveLength(1)

    // 未登录时 onShow 不应拉取后台任务
    hooks.showCbs[0]()
    expect(refreshSpy).not.toHaveBeenCalled()

    // 登录后 onShow 恢复轮询，onHide 暂停轮询
    authStore.setToken('valid-token')
    hooks.showCbs[0]()
    expect(refreshSpy).toHaveBeenCalledTimes(1)

    hooks.hideCbs[0]()
    expect(stopSpy).toHaveBeenCalledTimes(1)
  })

  it('IndexPage suppresses duplicate initial burst when onMounted and onShow fire together on cold start', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const authStore = useAuthStore()
    authStore.setToken('tok-cold')

    const seenUrls: string[] = []
    const materialResolvers: Array<(val: any) => void> = []
    hooks.request.mockImplementation(({ url }: { url: string }) => {
      seenUrls.push(url)
      if (url.startsWith('/folders')) return Promise.resolve({ items: [], total: 0 })
      if (url.startsWith('/questions/jobs')) return Promise.resolve({ items: [], total: 0 })
      if (url.startsWith('/materials')) {
        return new Promise((resolve) => {
          materialResolvers.push(resolve)
        })
      }
      return Promise.resolve({ items: [] })
    })

    wrapper = mount(IndexPage, {
      global: {
        plugins: [pinia],
        stubs: {
          BackgroundTaskBar: true,
          AiCoachDrawer: true,
          FolderFilterBar: true,
          FolderFormModal: true,
          MaterialItemCard: true,
        },
      },
    })

    // 模拟冷启时 onShow 与 onMounted 重叠触发
    expect(hooks.showCbs).toHaveLength(1)
    hooks.showCbs[0]()

    // 在首次 refreshAll 完成前，onShow 不应再次触发 loadMaterialList 或 refreshActiveTasks
    const materialsBeforeResolve = seenUrls.filter((u) => u.startsWith('/materials')).length
    const jobsBeforeResolve = seenUrls.filter((u) => u.startsWith('/questions/jobs')).length
    expect(jobsBeforeResolve).toBe(1)
    expect(materialsBeforeResolve).toBeLessThanOrEqual(2)

    while (materialResolvers.length > 0) {
      materialResolvers.shift()!({ items: [], total: 0 })
    }
    await flushPromises()

    // 首次加载完成后再次切回页面触发 onShow，应正常刷新
    hooks.showCbs[0]()
    while (materialResolvers.length > 0) {
      materialResolvers.shift()!({ items: [], total: 0 })
    }
    await flushPromises()
    expect(seenUrls.filter((u) => u.startsWith('/questions/jobs')).length).toBe(2)
  })

  it('SessionPage debounces text answers by 500ms and flushes before switch, unload, and submit', async () => {
    vi.useFakeTimers()
    const pinia = createPinia()
    setActivePinia(pinia)

    const savedDrafts: Array<{ url: string; data: any }> = []
    hooks.request.mockImplementation(async (options: any) => {
      if (options.url.endsWith('/answers')) {
        savedDrafts.push({ url: options.url, data: options.data })
        return { success: true }
      }
      if (options.url.endsWith('/submit')) {
        return { practice_id: 'p-deb', status: 'submitted' }
      }
      if (options.url === '/practices/p-deb') {
        return {
          id: 'p-deb',
          practice_id: 'p-deb',
          title: '防抖练习',
          status: 'in_progress',
          total_count: 2,
          question_count: 2,
          items: [
            {
              attempt_item_id: 'a-1',
              id: 'a-1',
              question_id: 'q-1',
              order_index: 1,
              status: 'unanswered',
              user_answer: '',
              max_score: 10,
              question_snapshot: {
                stem: '简述梯度下降',
                question_type: 'short_answer',
                difficulty: 2,
                grading_rubric: {},
              },
            },
            {
              attempt_item_id: 'a-2',
              id: 'a-2',
              question_id: 'q-2',
              order_index: 2,
              status: 'unanswered',
              user_answer: '',
              max_score: 10,
              question_snapshot: {
                stem: '简述正则化',
                question_type: 'short_answer',
                difficulty: 2,
                grading_rubric: {},
              },
            },
          ],
        }
      }
      throw new Error(`unexpected request: ${options.url}`)
    })

    wrapper = mount(SessionPage, {
      global: {
        plugins: [pinia],
        stubs: {
          AiCoachDrawer: true,
          AnswerCardDrawer: true,
          PracticeQuestionBody: {
            name: 'PracticeQuestionBody',
            props: ['question', 'userAnswer', 'saveStatusText'],
            emits: ['input-answer', 'select-single', 'toggle-multiple', 'ask-coach'],
            template: '<div class="stub-body" />',
          },
        },
      },
    })

    const practiceStore = usePracticeStore()
    await hooks.loadCbs[0]({ practice_id: 'p-deb' })
    await flushPromises()

    const body = wrapper.findComponent({ name: 'PracticeQuestionBody' })

    // 连续快速输入 3 次：内存立即更新，但 500ms 内不发 PUT /answers
    body.vm.$emit('input-answer', '梯')
    body.vm.$emit('input-answer', '梯度')
    body.vm.$emit('input-answer', '梯度下降法')
    expect(practiceStore.userAnswers['q-1']).toBe('梯度下降法')
    expect(savedDrafts).toHaveLength(0)

    await vi.advanceTimersByTimeAsync(499)
    expect(savedDrafts).toHaveLength(0)

    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(savedDrafts).toHaveLength(1)
    expect(savedDrafts[0].data).toMatchObject({
      question_id: 'q-1',
      user_answer: '梯度下降法',
    })

    // 再次输入但未满 500ms 时立即点击下一题 -> 必须同步 flush，不丢草稿
    body.vm.$emit('input-answer', '梯度下降法（修订）')
    expect(savedDrafts).toHaveLength(1)
    await wrapper.find('.paper-btn-primary.nav-btn').trigger('tap')
    await flushPromises()
    expect(savedDrafts).toHaveLength(2)
    expect(savedDrafts[1].data).toMatchObject({
      question_id: 'q-1',
      user_answer: '梯度下降法（修订）',
    })
    expect(practiceStore.currentIndex).toBe(1)

    // 在第 2 题输入后触发 onUnload（未满 500ms）-> 卸载前必须立刻 flush 待写草稿
    body.vm.$emit('input-answer', 'L2正则化初稿')
    expect(savedDrafts).toHaveLength(2)
    hooks.unloadCbs[0]()
    await flushPromises()
    expect(savedDrafts).toHaveLength(3)
    expect(savedDrafts[2].data).toMatchObject({
      question_id: 'q-2',
      user_answer: 'L2正则化初稿',
    })

    // 再次编辑后立即点交卷（未满 500ms）-> 交卷前必须 flush 待写草稿
    body.vm.$emit('input-answer', 'L2正则化防止过拟合')
    expect(savedDrafts).toHaveLength(3)
    await wrapper.find('.submit-btn').trigger('tap')
    await flushPromises()
    expect(savedDrafts).toHaveLength(4)
    expect(savedDrafts[3].data).toMatchObject({
      question_id: 'q-2',
      user_answer: 'L2正则化防止过拟合',
    })
  })
})
