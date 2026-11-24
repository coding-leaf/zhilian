import fs from 'node:fs'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  loadCallbacks: [] as Array<(options: Record<string, string>) => Promise<void>>,
  showCallbacks: [] as Array<() => Promise<void> | void>,
  pullCallbacks: [] as Array<() => Promise<void>>,
}))

vi.mock('@/utils/request', () => ({
  request: (options: { url: string }) => mocks.request(options),
  uploadFile: vi.fn(),
}))

vi.mock('@dcloudio/uni-app', () => ({
  onLoad: (cb: (options: Record<string, string>) => Promise<void>) => mocks.loadCallbacks.push(cb),
  onShow: (cb: () => Promise<void> | void) => mocks.showCallbacks.push(cb),
  onPullDownRefresh: (cb: () => Promise<void>) => mocks.pullCallbacks.push(cb),
  onUnload: vi.fn(),
}))

import CoachMessageList from '@/components/CoachMessageList.vue'
import ReviewPage from '@/pages/review/index.vue'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import QuestionsPage from '@/subpackages/material/pages/questions/index.vue'
import PracticeQuestionBody from '@/subpackages/practice/components/PracticeQuestionBody.vue'
import { useReportDetail } from '@/subpackages/report/composables/useReportDetail'
import { resetLoadingGuardForTest } from '@/utils/loadingGuard'
import { RequestError } from '@/utils/requestError'
import { generatedQuestionFixture } from './fixtures/backendResponses'

const SRC_ROOT = path.resolve(__dirname, '../src')
const uniHost = (globalThis as unknown as {
  uni: { showToast: (opts: Record<string, unknown>) => void; setClipboardData?: unknown }
}).uni

const collectFiles = (dir: string, ext: string): string[] => {
  const results: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) results.push(...collectFiles(full, ext))
    else if (entry.name.endsWith(ext)) results.push(full)
  }
  return results
}

let wrapper: VueWrapper | undefined

describe('M2 mp-weixin Vue/WXML/WXSS compatibility fixes', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    resetLoadingGuardForTest()
    mocks.request.mockReset()
    mocks.loadCallbacks.length = 0
    mocks.showCallbacks.length = 0
    mocks.pullCallbacks.length = 0
  })

  afterEach(() => {
    useBackgroundTaskStore().reset()
    wrapper?.unmount()
    wrapper = undefined
    delete uniHost.setClipboardData
    vi.restoreAllMocks()
  })

  it('PracticeQuestionBody hides native inputs when overlayOpen=true and buffers multi-blank drafts locally', async () => {
    wrapper = mount(PracticeQuestionBody, {
      props: {
        question: {
          id: 'q-fill-1',
          type: 'fill_in_blank',
          stem: '先验概率是____，后验概率是____。',
          answer: 'P(Y); P(Y|X)',
        },
        userAnswer: undefined,
        saveStatusText: '已保存',
        overlayOpen: false,
      },
      global: {
        stubs: { RichContent: { props: ['content'], template: '<div>{{ content }}</div>' } },
      },
    })

    const inputs = wrapper.findAll('input.fill-blank-input')
    expect(inputs).toHaveLength(2)
    expect(inputs[0].attributes('cursor-spacing')).toBe('24')
    expect(inputs[0].attributes('show-confirm-bar')).toBe('false')

    await inputs[0].trigger('input', { detail: { value: '  alpha;' } })
    expect(wrapper.emitted('input-answer')?.[0]).toEqual(['  alpha ; '])

    // Simulate parent echoing normalized value back through props.userAnswer
    await wrapper.setProps({ userAnswer: '  alpha ; ' })
    const rawValue = (wrapper.findAll('input.fill-blank-input')[0].element as HTMLInputElement).value
    expect(rawValue).toBe('  alpha;')

    // Opening drawer unmounts native inputs and displays static preview text
    await wrapper.setProps({ overlayOpen: true })
    expect(wrapper.findAll('input.fill-blank-input')).toHaveLength(0)
    expect(wrapper.findAll('.input-overlay-preview')).toHaveLength(2)
    expect(wrapper.findAll('.input-overlay-preview')[0].text()).toContain('alpha;')

    // Switching question.id syncs local drafts from new question's userAnswer
    await wrapper.setProps({
      overlayOpen: false,
      question: {
        id: 'q-essay-2',
        type: 'short_answer',
        stem: '简述正则化作用。',
      },
      userAnswer: '抑制过拟合',
    })
    const textarea = wrapper.find('textarea.essay-input')
    expect(textarea.exists()).toBe(true)
    expect((textarea.element as HTMLTextAreaElement).value).toBe('抑制过拟合')
    expect(textarea.attributes('cursor-spacing')).toBe('24')
    expect(textarea.attributes('show-confirm-bar')).toBe('false')

    await wrapper.setProps({ overlayOpen: true })
    expect(wrapper.find('textarea.essay-input').exists()).toBe(false)
    expect(wrapper.find('.essay-overlay-preview').text()).toContain('抑制过拟合')
  })

  it('questions/index.vue guards onShow during async onLoad on ?view=generated and avoids >7-char success Toast', async () => {
    let resolveKps!: (val: unknown) => void
    const kpPromise = new Promise((resolve) => {
      resolveKps = resolve
    })
    const toastSpy = vi.spyOn(uniHost, 'showToast')

    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url === '/materials/m-1/knowledge-tree') return kpPromise
      if (url.startsWith('/questions?batch_id=b-1')) {
        return {
          items: [
            generatedQuestionFixture({
              id: 'q-1',
              knowledge_point_id: 'kp-1',
              batch_id: 'b-1',
              status: 'available',
            }),
          ],
        }
      }
      if (url.startsWith('/questions/batches')) return { items: [], total: 0 }
      return { items: [], total: 0 }
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    const taskStore = useBackgroundTaskStore()
    taskStore.trackQuestionJob({
      id: 'job-active-m1',
      status: 'running',
      material_id: 'm-1',
      total_kps: 2,
      completed_kps: 1,
      generated_count: 1,
      question_ids: [],
      created_at: '',
      updated_at: '',
    })

    wrapper = mount(QuestionsPage, {
      global: {
        plugins: [pinia],
        stubs: { BackgroundTaskBar: true, RichContent: true },
      },
    })

    const loadDone = mocks.loadCallbacks[0]({
      material_id: 'm-1',
      view: 'generated',
      batch_id: 'b-1',
    })
    // Simulate WeChat onShow firing while async onLoad is suspended
    await mocks.showCallbacks[0]()
    await flushPromises()

    expect(wrapper.find('.job-progress-banner').exists()).toBe(false)
    expect(wrapper.find('.ready-card').exists()).toBe(true)

    resolveKps({
      material_id: 'm-1',
      version_id: 'v-1',
      nodes: [{ id: 'kp-1', name: '梯度下降', level: 1, sort_order: 1, children: [] }],
    })
    await loadDone
    await flushPromises()

    expect(wrapper.find('.ready-card').exists()).toBe(true)
    expect(wrapper.text()).toContain('已为你准备好 1 道题目')

    // Complete an active job via watcher and verify no >7-char toast uses icon: 'success'
    taskStore.trackQuestionJob({
      id: 'job-done-m1',
      status: 'completed',
      material_id: 'm-1',
      total_kps: 1,
      completed_kps: 1,
      generated_count: 3,
      batch_id: 'b-1',
      question_ids: ['q-1'],
      created_at: '',
      updated_at: '2026-11-24T12:00:00',
      completed_at: '2026-11-24T12:00:00',
    })
    await flushPromises()
    for (const call of toastSpy.mock.calls) {
      const arg = call[0] as { title?: string; icon?: string }
      if (arg?.title && arg.title.length > 7) {
        expect(arg.icon).toBe('none')
      }
    }
  })

  it('review/index.vue deduplicates cold-start onShow/onMounted, lazy-mounts QuestionBankSection, and removes sticky overlap', async () => {
    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url.startsWith('/folders')) return { items: [], total: 0 }
      if (url.startsWith('/materials')) return []
      if (url.startsWith('/questions/jobs')) {
        return {
          items: [
            {
              id: 'job-review-active',
              status: 'running',
              material_id: 'm-1',
              total_kps: 2,
              completed_kps: 1,
              generated_count: 0,
              question_ids: [],
              created_at: '',
              updated_at: '',
            },
          ],
          total: 1,
        }
      }
      if (url.startsWith('/questions/batches')) return { items: [], total: 0 }
      if (url.startsWith('/mastery')) {
        return {
          total_knowledge_points: 0,
          proficient_count: 0,
          basic_count: 0,
          weak_count: 0,
          unlearned_count: 0,
          overall_mastery_score: 0,
          weak_knowledge_points: [],
        }
      }
      if (url.startsWith('/wrong-records')) return { items: [], groups: [], total: 0 }
      if (url.startsWith('/practices')) return { items: [], total: 0, limit: 20, offset: 0 }
      throw new Error(`unexpected: ${url}`)
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(ReviewPage, {
      global: {
        plugins: [pinia],
        stubs: {
          'rich-text': true,
          'scroll-view': { template: '<div><slot /></div>' },
        },
      },
    })

    // Cold-start onShow before onMounted completes is ignored
    await mocks.showCallbacks[0]()
    await flushPromises()

    const masteryCalls = mocks.request.mock.calls.filter(([o]) =>
      String((o as { url: string }).url).startsWith('/mastery'),
    )
    const batchCallsBeforeBank = mocks.request.mock.calls.filter(([o]) =>
      String((o as { url: string }).url).startsWith('/questions/batches'),
    )
    expect(masteryCalls).toHaveLength(1)
    expect(batchCallsBeforeBank).toHaveLength(0)

    // Active BackgroundTaskBar prevents .segment-bar from also carrying .sticky-surface
    expect(wrapper.find('.task-bar-container').exists()).toBe(true)
    expect(wrapper.find('.segment-bar').classes()).not.toContain('sticky-surface')

    // Switching to bank tab mounts QuestionBankSection and fetches batches exactly once
    const bankTab = wrapper.findAll('.segment-item')[3]
    await bankTab.trigger('tap')
    await flushPromises()
    const batchCallsOnFirstVisit = mocks.request.mock.calls.filter(([o]) =>
      String((o as { url: string }).url).startsWith('/questions/batches'),
    )
    expect(batchCallsOnFirstVisit).toHaveLength(1)
  })

  it('useReportDetail avoids >7-char success Toast and never leaks RequestError URLs', async () => {
    const toastSpy = vi.spyOn(uniHost, 'showToast')
    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url === '/practices/p-1') {
        throw new RequestError('timeout', 'http://127.0.0.1:8000/api/v1/practices/p-1', 'GET', '请求超时（15秒）')
      }
      if (url === '/grading/regrade') {
        return { message: '已根据采分点重新完成 AI 复核', attempt_item_id: 'ai-1' }
      }
      return {}
    })

    const detail = useReportDetail()
    detail.practiceId.value = 'p-1'
    await detail.bootstrap()
    expect(detail.loadError.value).toBe('请求超时（15秒）')
    expect(detail.loadError.value).not.toContain('http://')

    detail.openGrading('regrade', {
      attemptItemId: 'ai-1',
      questionId: 'q-1',
      orderIndex: 1,
      stem: '题干',
      type: 'short_answer',
      options: [],
      userAnswer: '作答',
      correctAnswer: '标准答案',
      isAnswered: true,
      gradingStatus: 'graded',
      isPending: false,
      score: 1,
      maxScore: 5,
      isCorrect: false,
      hitKeywords: [],
      missingKeywords: ['关键术语'],
      gradingPoints: ['关键术语'],
    })
    await detail.submitGrading({ reason: '包含关键术语', score: 0 })

    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '已根据采分点重新完成 AI 复核',
        icon: 'none',
      }),
    )
  })

  it('CoachMessageList omits duplicate toast on clipboard copy and rotates scroll-into-view anchor IDs', async () => {
    const toastSpy = vi.spyOn(uniHost, 'showToast')
    const setClipboardData = vi.fn(({ success }: { success?: () => void }) => {
      success?.()
    })
    uniHost.setClipboardData = setClipboardData

    wrapper = mount(CoachMessageList, {
      props: {
        messages: [
          { id: 'm-1', role: 'assistant', content: '这是解析内容' },
        ],
        isThinking: false,
      },
      global: {
        stubs: {
          RichContent: { props: ['content'], template: '<div>{{ content }}</div>' },
          'scroll-view': {
            props: ['scrollIntoView'],
            template: '<div class="sv-stub" :data-scroll-id="scrollIntoView"><slot /></div>',
          },
        },
      },
    })
    await flushPromises()

    const firstAnchor = wrapper.get('.sv-stub').attributes('data-scroll-id')
    expect(firstAnchor).toMatch(/^coach-bottom-anchor-\d+$/)

    await wrapper.setProps({
      messages: [
        { id: 'm-1', role: 'assistant', content: '这是解析内容' },
        { id: 'm-2', role: 'user', content: '再解释一下' },
      ],
    })
    await flushPromises()
    const secondAnchor = wrapper.get('.sv-stub').attributes('data-scroll-id')
    expect(secondAnchor).toMatch(/^coach-bottom-anchor-\d+$/)
    expect(secondAnchor).not.toBe(firstAnchor)

    await wrapper.get('.copy-btn').trigger('tap')
    expect(setClipboardData).toHaveBeenCalledWith(expect.objectContaining({ data: '这是解析内容' }))
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('static guard: zero [disabled] selectors and every <button :loading> binds :disabled', () => {
    const scssFiles = collectFiles(SRC_ROOT, '.scss')
    const vueFiles = collectFiles(SRC_ROOT, '.vue')

    for (const file of [...scssFiles, ...vueFiles]) {
      const content = fs.readFileSync(file, 'utf-8')
      expect(content, `Unexpected [disabled] selector in ${file}`).not.toMatch(/\[disabled\]/)
    }

    const buttonTagRe = /<button\b[\s\S]*?>/g
    for (const file of vueFiles) {
      const content = fs.readFileSync(file, 'utf-8')
      const matches = (content.match(buttonTagRe) || []).filter((tag) => /:loading=/.test(tag))
      for (const tag of matches) {
        expect(tag, `Missing :disabled alongside :loading in ${file}: ${tag}`).toMatch(/:disabled=/)
      }
      const lineCount = content.split(/\r?\n/).length
      expect(lineCount, `${file} exceeds 300 lines (${lineCount})`).toBeLessThanOrEqual(300)
    }

    const coachContent = fs.readFileSync(path.join(SRC_ROOT, 'components/AiCoachDrawer.vue'), 'utf-8')
    expect(coachContent).toContain(':fixed="true"')
    expect(coachContent).toContain('confirm-type="send"')

    const gradingModalContent = fs.readFileSync(
      path.join(SRC_ROOT, 'subpackages/report/components/GradingActionModal.vue'),
      'utf-8',
    )
    expect(gradingModalContent.match(/:fixed="true"/g)?.length).toBe(2)
  })
})
