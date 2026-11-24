import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  uploadFile: vi.fn(),
}))

vi.mock('@/utils/request', () => ({
  request: mocks.request,
  uploadFile: mocks.uploadFile,
}))

import QuestionBankSection from '@/pages/review/components/QuestionBankSection.vue'
import CollectionPickerDrawer from '@/components/CollectionPickerDrawer.vue'
import AttemptResultCard from '@/subpackages/report/components/AttemptResultCard.vue'
import type { AttemptResult } from '@/types'

let wrapper: VueWrapper | undefined

const richTextStub = {
  props: ['nodes'],
  template: '<div class="rt-stub">{{ JSON.stringify(nodes) }}</div>',
}

const scrollViewStub = {
  template: '<div class="scroll-stub"><slot /></div>',
}

describe('Question Bank Three-View & Collections', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    mocks.request.mockReset()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    vi.restoreAllMocks()
  })

  it('supports grouped view (material -> KP) and launching practice from selected questions', async () => {
    mocks.request.mockImplementation(async (options: { url: string; method?: string; data?: any }) => {
      if (options.url.startsWith('/questions/batches')) return { items: [], total: 0 }
      if (options.url.startsWith('/questions/grouped-summary')) {
        return {
          total_questions: 3,
          materials: [
            {
              material_id: 'm-1',
              material_title: '第五章 - SVM.pdf',
              folder_id: 'f-1',
              folder_name: '机器学习',
              question_count: 3,
              knowledge_points: [{ kp_id: 'kp-1', kp_name: '核技巧', question_count: 3 }],
            },
          ],
        }
      }
      if (options.url.startsWith('/questions?')) {
        return {
          items: [
            {
              id: 'q-svm-1',
              question_type: 'single_choice',
              stem: '核函数的作用是什么？',
              status: 'available',
            },
          ],
          total: 1,
        }
      }
      if (options.url === '/practices' && options.method === 'POST') {
        return {
          id: 'p-grp-1',
          practice_id: 'p-grp-1',
          title: options.data.title,
          status: 'not_started',
          total_count: 1,
          items: [],
        }
      }
      throw new Error(`unexpected: ${options.url}`)
    })

    wrapper = mount(QuestionBankSection, {
      props: { wrongRecords: [], folderId: 'f-1', isActive: true },
      global: { stubs: { 'rich-text': richTextStub } },
    })
    await flushPromises()

    // Switch to 讲义考点 tab
    const groupedTab = wrapper.findAll('.bank-view-tab')[1]
    await groupedTab.trigger('tap')
    await flushPromises()

    expect(wrapper.text()).toContain('第五章 - SVM.pdf')
    expect(wrapper.text()).toContain('核技巧')
    expect(wrapper.text()).toContain('3 题')

    // Expand KP -> loads questions
    await wrapper.find('.grp-kp-row').trigger('tap')
    await flushPromises()
    expect(mocks.request.mock.calls.some(([o]) => String(o.url).includes('knowledge_point_id=kp-1'))).toBe(true)

    // Select question and start practice
    await wrapper.find('.bank-checkbox').trigger('tap')
    await wrapper.find('.quick-gen-btn').trigger('tap')
    await flushPromises()

    const practiceCall = mocks.request.mock.calls.find(([o]) => o.url === '/practices')
    expect(practiceCall?.[0].data.question_ids).toEqual(['q-svm-1'])
  })

  it('supports collections CRUD (no PATCH), delete warning, item removal, and whole-collection practice', async () => {
    const collections = [
      {
        id: 'col-1',
        name: '期中必刷',
        description: '',
        folder_id: 'f-1',
        folder_name: '机器学习',
        color_token: null,
        is_pinned: false,
        sort_order: 0,
        question_count: 2,
        created_at: '2026-11-24T10:00:00',
        updated_at: '2026-11-24T10:00:00',
      },
    ]

    mocks.request.mockImplementation(async (options: { url: string; method?: string; data?: any }) => {
      expect(options.method).not.toBe('PATCH')
      if (options.url.startsWith('/questions/batches')) return { items: [], total: 0 }
      if (options.url.startsWith('/collections') && options.method === 'GET' && !options.url.includes('/questions')) {
        return { items: collections, total: collections.length }
      }
      if (options.url === '/collections' && options.method === 'POST') {
        const created = {
          id: 'col-2',
          name: options.data.name,
          description: '',
          folder_id: 'f-1',
          folder_name: '机器学习',
          color_token: null,
          is_pinned: false,
          sort_order: 0,
          question_count: 0,
          created_at: '2026-11-24T11:00:00',
          updated_at: '2026-11-24T11:00:00',
        }
        collections.unshift(created)
        return created
      }
      if (options.url === '/collections/col-1' && options.method === 'PUT') {
        return { ...collections[0], name: options.data.name }
      }
      if (options.url.startsWith('/collections/col-1/questions') && options.method === 'GET') {
        return {
          items: [
            {
              id: 'ci-1',
              collection_id: 'col-1',
              question_id: 'q-1',
              question_type: 'single_choice',
              difficulty: 2,
              content: '支持向量机的间隔最大化目标是什么？',
              options: [{ key: 'A', content: '最大间隔' }],
              answer: 'A',
              explanation: '几何间隔最大化',
              kp_id: 'kp-1',
              kp_name: '超平面',
              material_id: 'm-1',
              material_title: 'SVM.pdf',
              note: null,
              added_at: '2026-11-24T10:00:00',
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        }
      }
      if (options.url === '/collections/col-1/items/q-1' && options.method === 'DELETE') {
        return undefined
      }
      if (options.url === '/collections/col-1' && options.method === 'DELETE') {
        return undefined
      }
      if (options.url === '/practices' && options.method === 'POST') {
        return {
          id: 'p-col-1',
          practice_id: 'p-col-1',
          title: options.data.title,
          status: 'not_started',
          total_count: 2,
          items: [],
        }
      }
      throw new Error(`unexpected: ${options.method} ${options.url}`)
    })

    wrapper = mount(QuestionBankSection, {
      props: { wrongRecords: [], folderId: 'f-1', isActive: true },
      global: { stubs: { 'rich-text': richTextStub } },
    })
    await flushPromises()

    // Switch to 题单收纳 tab
    await wrapper.findAll('.bank-view-tab')[0].trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('期中必刷')

    // Expand collection questions & remove item
    await wrapper.find('.col-action-link').trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('超平面')
    await wrapper.find('.col-q-remove').trigger('tap')
    await flushPromises()
    expect(wrapper.text()).not.toContain('超平面')

    // Whole collection practice uses collection_id
    await wrapper.find('.col-practice-btn').trigger('tap')
    await flushPromises()
    const practiceCall = mocks.request.mock.calls.find(([o]) => o.url === '/practices')
    expect(practiceCall?.[0].data.collection_id).toBe('col-1')

    // Delete collection confirms with "仅删除题单，不删除题目"
    const modalSpy = vi.spyOn(uni as any, 'showModal')
    await wrapper.find('.col-action-danger').trigger('tap')
    await flushPromises()
    expect(modalSpy).toHaveBeenCalled()
    expect(String((modalSpy.mock.calls[0]?.[0] as { content?: string })?.content)).toContain(
      '仅删除题单，不删除题目',
    )
  })

  it('CollectionPickerDrawer loads memberships, quick-creates, and saves, and AttemptResultCard triggers collect', async () => {
    mocks.request.mockImplementation(async (options: { url: string; method?: string; data?: any }) => {
      if (options.url === '/collections' && options.method === 'GET') {
        return {
          items: [
            {
              id: 'col-1',
              name: '易错集',
              description: '',
              folder_id: null,
              folder_name: null,
              color_token: null,
              is_pinned: false,
              sort_order: 0,
              question_count: 3,
              created_at: '',
              updated_at: '',
            },
          ],
          total: 1,
        }
      }
      if (options.url === '/questions/q-1/collections' && options.method === 'GET') {
        return { question_id: 'q-1', collection_ids: ['col-1'] }
      }
      if (options.url === '/collections' && options.method === 'POST') {
        return {
          id: 'col-new',
          name: options.data.name,
          description: '',
          folder_id: null,
          folder_name: null,
          color_token: null,
          is_pinned: false,
          sort_order: 0,
          question_count: 0,
          created_at: '',
          updated_at: '',
        }
      }
      if (options.url === '/questions/q-1/collections' && options.method === 'POST') {
        return {
          question_id: 'q-1',
          collection_ids: options.data.collection_ids,
          added_count: 1,
          removed_count: 0,
        }
      }
      throw new Error(`unexpected: ${options.method} ${options.url}`)
    })

    const drawer = mount(CollectionPickerDrawer, {
      props: { visible: true, questionId: 'q-1', folderId: 'all' },
      global: { stubs: { 'scroll-view': scrollViewStub } },
    })
    await flushPromises()

    expect(drawer.text()).toContain('易错集')
    expect(drawer.text()).toContain('已选 1')

    // Quick create new collection
    await drawer.find('.picker-create-input').setValue('考前冲刺')
    await drawer.find('.picker-create-btn').trigger('tap')
    await flushPromises()

    expect(drawer.text()).toContain('考前冲刺')
    expect(drawer.text()).toContain('已选 2')

    // Save membership
    await drawer.find('.picker-save-btn').trigger('tap')
    await flushPromises()
    const syncCall = mocks.request.mock.calls.find(
      ([o]) => o.url === '/questions/q-1/collections' && o.method === 'POST',
    )
    expect(syncCall?.[0].data.collection_ids).toEqual(['col-1', 'col-new'])
    expect(drawer.emitted('saved')?.[0]?.[0]).toEqual({
      questionId: 'q-1',
      collectionIds: ['col-1', 'col-new'],
    })
    drawer.unmount()

    // AttemptResultCard emits collect when clicking 收纳
    const sampleResult: AttemptResult = {
      attemptItemId: 'ai-1',
      questionId: 'q-1',
      orderIndex: 1,
      type: 'single_choice',
      stem: '测试题干',
      options: [],
      userAnswer: 'A',
      correctAnswer: 'A',
      isAnswered: true,
      gradingStatus: 'graded',
      isPending: false,
      score: 1,
      maxScore: 1,
      isCorrect: true,
      hitKeywords: [],
      missingKeywords: [],
      gradingPoints: [],
    }
    const card = mount(AttemptResultCard, {
      props: { result: sampleResult },
      global: { stubs: { 'rich-text': richTextStub } },
    })
    await card.find('.collect-action-btn').trigger('tap')
    expect(card.emitted('collect')?.[0]?.[0]).toEqual(sampleResult)
    card.unmount()
  })
})
