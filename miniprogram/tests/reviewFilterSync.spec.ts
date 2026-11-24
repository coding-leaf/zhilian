import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  uploadFile: vi.fn(),
  showCallbacks: [] as Array<() => Promise<void>>,
  pullCallbacks: [] as Array<() => Promise<void>>,
}))

vi.mock('@/utils/request', () => ({
  request: mocks.request,
  uploadFile: mocks.uploadFile,
}))

vi.mock('@dcloudio/uni-app', () => ({
  onShow: (cb: () => Promise<void>) => mocks.showCallbacks.push(cb),
  onPullDownRefresh: (cb: () => Promise<void>) => mocks.pullCallbacks.push(cb),
}))

import ReviewPage from '@/pages/review/index.vue'
import QuestionBankSection from '@/pages/review/components/QuestionBankSection.vue'
import { useReviewCenter } from '@/pages/review/composables/useReviewCenter'
import { useAuthStore } from '@/stores/auth'

let wrapper: VueWrapper | undefined

const richTextStub = {
  props: ['nodes'],
  template: '<div class="rt-stub">{{ JSON.stringify(nodes) }}</div>',
}

const scrollViewStub = {
  template: '<div class="scroll-stub"><slot /></div>',
}

describe('Review 4-Tab Filter Sync & Race Guard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    mocks.request.mockReset()
    mocks.showCallbacks.length = 0
    mocks.pullCallbacks.length = 0
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    vi.restoreAllMocks()
  })

  it('syncs folderId across mastery, wrongs, practices (including __none__), and discards stale responses', async () => {
    let resolveSlowMastery!: (v: unknown) => void
    const slowMasteryPromise = new Promise((resolve) => {
      resolveSlowMastery = resolve
    })

    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url.startsWith('/mastery')) {
        if (url.includes('folder_id=f-1')) return slowMasteryPromise
        if (url.includes('folder_id=f-2')) {
          return {
            total_knowledge_points: 2,
            proficient_count: 1,
            basic_count: 1,
            weak_count: 0,
            unlearned_count: 0,
            overall_mastery_score: 0.78,
            weak_knowledge_points: [],
          }
        }
        return {
          total_knowledge_points: 5,
          proficient_count: 2,
          basic_count: 1,
          weak_count: 1,
          unlearned_count: 1,
          overall_mastery_score: 0.6,
          weak_knowledge_points: [],
        }
      }
      if (url.startsWith('/wrong-records')) {
        return { items: [], groups: [], total: 0 }
      }
      if (url.startsWith('/practices')) {
        return {
          items: [
            {
              id: 'p-1',
              title: '课程练习',
              status: 'completed',
              question_count: 10,
              folder_name: '课程二',
            },
          ],
          total: 35,
          limit: 20,
          offset: 0,
        }
      }
      throw new Error(`unexpected: ${url}`)
    })

    const review = useReviewCenter()
    review.selectedWrongIds.value = ['w-old']
    review.selectedGroupKey.value = 'folder:old'

    // Start slow f-1 switch, then immediately switch to f-2
    const p1 = review.selectFolderFilter('f-1')
    const p2 = review.selectFolderFilter('f-2')
    await p2

    // Resolve slow f-1 AFTER f-2 completed
    resolveSlowMastery({
      total_knowledge_points: 99,
      proficient_count: 0,
      basic_count: 0,
      weak_count: 99,
      unlearned_count: 0,
      overall_mastery_score: 0.1,
      weak_knowledge_points: [],
    })
    await p1

    expect(review.selectedFolderId.value).toBe('f-2')
    expect(review.selectedWrongIds.value).toEqual([])
    expect(review.selectedGroupKey.value).toBe('')
    expect(review.masteryOverview.value?.total_knowledge_points).toBe(2)
    expect(review.practiceTotal.value).toBe(35)

    // Switching to __none__ passes unclassified=true for wrong-records and folder_id=__none__ for practices
    await review.selectFolderFilter('__none__')
    const urls = mocks.request.mock.calls.map(([o]) => String(o.url))
    expect(urls.some((u) => u.includes('/wrong-records') && u.includes('unclassified=true'))).toBe(true)
    expect(urls.some((u) => u.includes('/practices') && u.includes('folder_id=__none__'))).toBe(true)
    expect(urls.some((u) => u.includes('/mastery') && u.includes('folder_id=__none__'))).toBe(true)
  })

  it('updates practice badge with true total and hides redundant single-course wrong group bar', async () => {
    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url.startsWith('/folders')) {
        return { items: [{ id: 'f-1', name: '机器学习' }], total: 1 }
      }
      if (url.startsWith('/materials')) return []
      if (url.startsWith('/questions/jobs')) return { items: [], total: 0 }
      if (url.startsWith('/mastery')) {
        return {
          total_knowledge_points: url.includes('folder_id=f-1') ? 3 : 8,
          proficient_count: 1,
          basic_count: 1,
          weak_count: 1,
          unlearned_count: 0,
          overall_mastery_score: 0.6,
          weak_knowledge_points: [],
        }
      }
      if (url.startsWith('/wrong-records')) {
        const isCourse = url.includes('folder_id=f-1')
        return {
          items: [
            {
              id: 'w-1',
              folder_id: 'f-1',
              material_id: 'm-1',
              practice_id: 'p-1',
              attempt_item_id: 'ai-1',
              question_id: 'q-1',
              knowledge_point_id: 'kp-1',
              knowledge_point_name: '核技巧',
              is_mastered: false,
              question_snapshot: { stem: '错题题干', question_type: 'single_choice' },
            },
          ],
          groups: isCourse
            ? [{ folder_id: 'f-1', folder_name: '机器学习', material_id: null, material_title: null, count: 1 }]
            : [
                { folder_id: 'f-1', folder_name: '机器学习', material_id: null, material_title: null, count: 1 },
                { folder_id: 'f-2', folder_name: '操作系统', material_id: null, material_title: null, count: 2 },
              ],
          total: 1,
        }
      }
      if (url.startsWith('/practices')) {
        return {
          items: Array.from({ length: 20 }, (_, i) => ({
            id: `p-${i}`,
            title: `练习 ${i}`,
            status: 'completed',
            question_count: 5,
          })),
          total: 27,
          limit: 20,
          offset: 0,
        }
      }
      throw new Error(`unexpected: ${url}`)
    })

    useAuthStore().setToken('tok-sync')
    wrapper = mount(ReviewPage, {
      global: {
        stubs: { 'rich-text': richTextStub, 'scroll-view': scrollViewStub },
      },
    })
    await flushPromises()

    // Practice segment badge shows real total 27 instead of items.length (20)
    const practiceTab = wrapper.findAll('.segment-item')[2]
    expect(practiceTab.text()).toContain('27')

    // Switch to wrong-book tab while on 'all': 2 groups shown
    await wrapper.findAll('.segment-item')[1].trigger('tap')
    await flushPromises()
    expect(wrapper.find('.group-scroll').exists()).toBe(true)

    // Filter to single course f-1: secondary group-scroll hides, but regenerate card stays available
    const coursePill = wrapper.findAll('.folder-pill')[1]
    await coursePill.trigger('tap')
    await flushPromises()
    expect(wrapper.find('.group-scroll').exists()).toBe(false)
    expect(wrapper.text()).toContain('错题薄弱点举一反三')
    expect(wrapper.text()).toContain('立即巩固')
  })

  it('resets QuestionBankSection cache and selection when folderId changes and forwards folder_id', async () => {
    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url.startsWith('/questions/batches')) {
        const isF2 = url.includes('folder_id=f-2')
        return {
          items: [
            {
              batch_id: isF2 ? 'b-2' : 'b-1',
              question_count: 1,
              available_count: 1,
              pending_review_count: 0,
              created_at: '2026-11-24T10:00:00',
              sources: [],
            },
          ],
          total: 1,
        }
      }
      if (url.startsWith('/questions?')) {
        return {
          items: [
            { id: 'q-1', question_type: 'single_choice', stem: '题1', batch_id: 'b-1', status: 'available' },
          ],
          total: 1,
        }
      }
      throw new Error(`unexpected: ${url}`)
    })

    wrapper = mount(QuestionBankSection, {
      props: { wrongRecords: [], folderId: 'all', isActive: true },
      global: { stubs: { 'rich-text': richTextStub } },
    })
    await flushPromises()

    // Select batch b-1 and expand
    await wrapper.find('.bank-checkbox').trigger('tap')
    await wrapper.find('.bank-expand-btn').trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('已选 1 题')

    // Change folderId -> clears selection & expanded state, fetches with folder_id=f-2
    await wrapper.setProps({ folderId: 'f-2' })
    await flushPromises()

    expect(wrapper.text()).toContain('已选 0 题')
    const urls = mocks.request.mock.calls.map(([o]) => String(o.url))
    expect(urls.some((u) => u.includes('/questions/batches') && u.includes('folder_id=f-2'))).toBe(true)
  })
})
