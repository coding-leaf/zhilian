import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
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

import PracticeSessionPage from '@/subpackages/practice/pages/session/index.vue'
import ReportDetailPage from '@/subpackages/report/pages/detail/index.vue'
import AttemptResultCard from '@/subpackages/report/components/AttemptResultCard.vue'
import ReviewPage from '@/pages/review/index.vue'
import WrongRecordCard from '@/pages/review/components/WrongRecordCard.vue'
import { usePracticeStore } from '@/stores/practice'
import { resetLoadingGuardForTest } from '@/utils/loadingGuard'
import type { AttemptResult, WrongRecordItem } from '@/types'

const richTextStub = {
  props: ['nodes'],
  template: '<div class="rt-stub">{{ JSON.stringify(nodes) }}</div>',
}

const scrollViewStub = {
  template: '<div class="scroll-stub"><slot /></div>',
}

let wrapper: VueWrapper | undefined

describe('Practice, Report & Review Closed-Loop Integration Flows', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    resetLoadingGuardForTest()
    mocks.request.mockReset()
    mocks.uploadFile.mockReset()
    mocks.loadCallbacks.length = 0
    mocks.showCallbacks.length = 0
    mocks.pullCallbacks.length = 0
    mocks.unloadCallbacks.length = 0
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    vi.restoreAllMocks()
    resetLoadingGuardForTest()
  })

  it('submits canonical 正确/错误 for true_false, upgrades legacy A/B drafts, and passes KP context to AiCoachDrawer', async () => {
    const savedPayloads: Array<{ url: string; data: any }> = []
    mocks.request.mockImplementation(async (options: { url: string; method?: string; data?: any }) => {
      if (options.url === '/practices/p-tf') {
        return {
          id: 'p-tf',
          practice_id: 'p-tf',
          title: '贝叶斯专项测验',
          folder_id: 'f-1',
          material_id: 'm-1',
          status: 'in_progress',
          total_count: 3,
          items: [
            {
              attempt_item_id: 'ai-1',
              question_id: 'q-tf',
              order_index: 1,
              status: 'answered',
              is_answered: true,
              user_answer: 'A',
              max_score: 1,
              question_snapshot: {
                id: 'q-tf',
                question_type: 'true_false',
                knowledge_point_id: 'kp-tf',
                knowledge_point_name: '先验概率性质',
                stem: '概率和为 $1$ 总是成立。',
                options: [
                  { key: 'A', content: '正确' },
                  { key: 'B', content: '错误' },
                ],
                answer: '正确',
              },
            },
            {
              attempt_item_id: 'ai-2',
              question_id: 'q-mc',
              order_index: 2,
              status: 'answered',
              is_answered: true,
              user_answer: '["A"]',
              max_score: 2,
              question_snapshot: {
                id: 'q-mc',
                question_type: 'multiple_choice',
                knowledge_point_id: 'kp-mc',
                knowledge_point_name: '条件独立假设',
                stem: '多选题干',
                options: [
                  { key: 'A', content: '选项一' },
                  { key: 'B', content: '选项二' },
                ],
                answer: 'A,B',
              },
            },
            {
              attempt_item_id: 'ai-3',
              question_id: 'q-fb',
              order_index: 3,
              status: 'not_started',
              is_answered: false,
              user_answer: null,
              max_score: 2,
              question_snapshot: {
                id: 'q-fb',
                question_type: 'fill_in_blank',
                knowledge_point_id: 'kp-fb',
                knowledge_point_name: '贝叶斯公式',
                stem: '分子是____，分母是____。',
                options: [],
                answer: '联合概率; 边缘概率',
              },
            },
          ],
        }
      }
      if (options.url.endsWith('/answers')) {
        savedPayloads.push({ url: options.url, data: options.data })
        return { success: true }
      }
      if (options.url.endsWith('/submit')) {
        return { practice_id: 'p-tf', status: 'completed' }
      }
      throw new Error(`unexpected: ${options.url}`)
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(PracticeSessionPage, {
      global: {
        plugins: [pinia],
        stubs: {
          'rich-text': richTextStub,
          AiCoachDrawer: {
            props: ['visible', 'title', 'questionId', 'knowledgePointId', 'contextText'],
            template: '<div class="coach-stub" :data-kp="knowledgePointId" :data-qid="questionId" :data-title="title" />',
          },
          AnswerCardDrawer: true,
        },
      },
    })

    await mocks.loadCallbacks[0]({ practice_id: 'p-tf' })
    await flushPromises()

    // 1. Legacy 'A' draft highlighted '正确' and auto-upgraded to canonical '正确'
    expect(wrapper.text()).toContain('考点：先验概率性质')
    expect(wrapper.findAll('.option-btn.selected')).toHaveLength(1)
    expect(wrapper.find('.option-btn.selected').text()).toContain('正确')
    expect(savedPayloads.some((p) => p.data.question_id === 'q-tf' && p.data.user_answer === '正确')).toBe(
      true,
    )

    // 2. Selecting '错误' records canonical '错误'
    const tfOptions = wrapper.findAll('.option-btn')
    await tfOptions[1].trigger('tap')
    await flushPromises()
    expect(usePracticeStore().userAnswers['q-tf']).toBe('错误')
    expect(savedPayloads[savedPayloads.length - 1].data.user_answer).toBe('错误')

    // 3. AiCoachDrawer receives questionId + knowledgePointId + KP title
    const coachStub = wrapper.find('.coach-stub')
    expect(coachStub.attributes('data-qid')).toBe('q-tf')
    expect(coachStub.attributes('data-kp')).toBe('kp-tf')
    expect(coachStub.attributes('data-title')).toContain('先验概率性质')

    // 4. Multi-choice question displays [多选题 · 可选多项] and restores ['A']
    usePracticeStore().jumpTo(1)
    await flushPromises()
    expect(wrapper.text()).toContain('[多选题 · 可选多项]')
    expect(wrapper.findAll('.option-btn.selected')).toHaveLength(1)

    // 5. Multi-blank question renders 2 indexed inputs
    usePracticeStore().jumpTo(2)
    await flushPromises()
    expect(wrapper.findAll('.fill-blank-input')).toHaveLength(2)
  })

  it('guards garbled PDF snippets in AttemptResultCard and links report page to review tab', async () => {
    const result: AttemptResult = {
      attemptItemId: 'ai-1',
      questionId: 'q-1',
      knowledgePointId: 'kp-1',
      knowledgePointName: '朴素贝叶斯',
      orderIndex: 1,
      type: 'short_answer',
      stem: '公式 $P(Y=c_k|X=x)$ 的含义',
      options: [],
      userAnswer: '后验概率',
      correctAnswer: '类条件概率与先验概率之积',
      isAnswered: true,
      gradingStatus: 'graded',
      isPending: false,
      score: 3,
      maxScore: 5,
      isCorrect: false,
      hitKeywords: ['后验'],
      missingKeywords: ['条件独立'],
      gradingPoints: ['说明先验概率', '说明条件独立假设'],
      analysis: '需要补充**条件独立假设**。',
      sourceQuote: 'AB&A&\n"#$"$\n!"!#"',
    }

    const card = mount(AttemptResultCard, {
      props: { result },
      global: { stubs: { 'rich-text': richTextStub } },
    })
    expect(card.text()).toContain('采分点与评分细则')
    expect(card.text()).toContain('说明条件独立假设')
    expect(card.text()).toContain('已自动屏蔽')
    expect(card.text()).not.toContain('AB&A&')
    card.unmount()

    const switchTabSpy = vi.spyOn(uni, 'switchTab')
    mocks.request.mockResolvedValue({
      id: 'p-done',
      practice_id: 'p-done',
      title: '完成练习',
      status: 'completed',
      total_count: 1,
      completed_at: '2026-11-17T10:00:00',
      items: [],
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(ReportDetailPage, {
      global: {
        plugins: [pinia],
        stubs: { 'rich-text': richTextStub, AiCoachDrawer: true },
      },
    })

    await mocks.loadCallbacks[0]({ practice_id: 'p-done' })
    await flushPromises()

    const reviewBtn = wrapper.findAll('button').find((b) => b.text().includes('查看学情总览'))
    expect(reviewBtn).toBeDefined()
    await reviewBtn!.trigger('tap')
    expect(switchTabSpy).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/pages/review/index' }),
    )
  })

  it('refreshes review page onShow, shows visible error+retry, and binds real KP name on WrongRecordCard', async () => {
    const wrongItem: WrongRecordItem = {
      id: 'w-real',
      folder_id: 'f-1',
      material_id: 'm-1',
      material_title: '贝叶斯分类器.pdf',
      practice_id: 'p-1',
      attempt_item_id: 'ai-1',
      question_id: 'q-1',
      knowledge_point_id: 'kp-1',
      knowledge_point_name: '拉普拉斯平滑',
      is_mastered: false,
      wrong_count: 2,
      question_snapshot: {
        stem: '为何要引入 $P(x_j|c_k)$ 拉普拉斯平滑？',
        question_type: 'single_choice',
      },
    }

    const wrongCard = mount(WrongRecordCard, {
      props: { record: wrongItem },
      global: { stubs: { 'rich-text': richTextStub } },
    })
    expect(wrongCard.get('.kp-tag').text()).toBe('拉普拉斯平滑')
    expect(wrongCard.text()).toContain('贝叶斯分类器.pdf')
    expect(wrongCard.text()).toContain('标为已掌握')
    expect(wrongCard.get('.wrong-type-pill').text()).toBe('单选题')
    wrongCard.unmount()

    let failMastery = true
    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url.startsWith('/folders')) return { items: [{ id: 'f-1', name: '机器学习' }], total: 1 }
      if (url.startsWith('/materials')) return []
      if (url.startsWith('/questions/jobs')) return { items: [], total: 0 }
      if (url.startsWith('/questions/batches')) return { items: [], total: 0 }
      if (url.startsWith('/mastery')) {
        if (failMastery) throw new Error('mastery service down')
        return {
          total_knowledge_points: 4,
          proficient_count: 1,
          basic_count: 1,
          weak_count: 1,
          unlearned_count: 1,
          overall_mastery_score: 0.52,
          weak_knowledge_points: [
            {
              knowledge_point_id: 'kp-1',
              knowledge_name: '拉普拉斯平滑',
              mastery_score: 0.25,
              level: 'weak',
              practice_count: 4,
              correct_count: 1,
            },
          ],
        }
      }
      if (url.startsWith('/wrong-records')) {
        return {
          items: [wrongItem],
          groups: [{ folder_id: 'f-1', folder_name: '机器学习', material_id: null, material_title: null, count: 1 }],
          total: 1,
        }
      }
      if (url.startsWith('/practices')) {
        return {
          items: [
            {
              id: 'p-1',
              title: '贝叶斯测验',
              status: 'completed',
              question_count: 5,
              score_rate: 0.8,
              created_at: '2026-11-17T10:00:00',
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        }
      }
      throw new Error(`unexpected: ${url}`)
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(ReviewPage, {
      global: {
        plugins: [pinia],
        stubs: {
          'rich-text': richTextStub,
          'scroll-view': scrollViewStub,
        },
      },
    })
    await flushPromises()

    // 1. Visible error + retry banner appears on API error
    expect(wrapper.text()).toContain('掌握度总览加载失败，请重试')
    expect(wrapper.find('.top-error-banner').exists()).toBe(true)

    // 2. Retry via onShow recovers mastery overview & weak point list
    failMastery = false
    expect(mocks.showCallbacks.length).toBeGreaterThanOrEqual(1)
    await mocks.showCallbacks[0]()
    await flushPromises()

    expect(wrapper.find('.top-error-banner').exists()).toBe(false)
    expect(wrapper.text()).toContain('52%')
    expect(wrapper.text()).toContain('针对薄弱考点强化练习')
    expect(wrapper.text()).toContain('拉普拉斯平滑')
    expect(wrapper.text()).toContain('去突破')
    expect(wrapper.text()).toContain('正确率 25% (1/4)')

    // 3. Switch to 错题本, 练习记录, and 我的题库 segments
    const tabs = wrapper.findAll('.segment-item')
    expect(tabs.map((t) => t.text())).toEqual([
      expect.stringContaining('考点掌握'),
      expect.stringContaining('错题本'),
      expect.stringContaining('练习记录'),
      expect.stringContaining('我的题库'),
    ])

    await tabs[1].trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('发起错题重练')
    expect(wrapper.get('.kp-tag').text()).toBe('拉普拉斯平滑')

    await tabs[2].trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('贝叶斯测验')
    expect(wrapper.text()).toContain('正确率 80%')
    expect(wrapper.text()).toContain('查看解析报告')

    // 4. Switching to 我的题库 and triggering onShow refreshes QuestionBankSection
    await tabs[3].trigger('tap')
    await flushPromises()
    const batchCallsBefore = mocks.request.mock.calls.filter(([o]) =>
      String(o.url).includes('/questions/batches'),
    ).length
    await mocks.showCallbacks[0]()
    await flushPromises()
    const batchCallsAfter = mocks.request.mock.calls.filter(([o]) =>
      String(o.url).includes('/questions/batches'),
    ).length
    expect(batchCallsAfter).toBeGreaterThan(batchCallsBefore)
  })
})
