import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  uploadFile: vi.fn(),
  loadCallbacks: [] as Array<(options: Record<string, string>) => Promise<void>>,
  showCallbacks: [] as Array<() => void>,
  pullCallbacks: [] as Array<() => Promise<void>>,
}))

vi.mock('@/utils/request', () => ({
  request: (options: any) => mocks.request(options),
  uploadFile: (...args: any[]) => mocks.uploadFile(...args),
}))

vi.mock('@dcloudio/uni-app', () => ({
  onLoad: (cb: (options: Record<string, string>) => Promise<void>) => mocks.loadCallbacks.push(cb),
  onShow: (cb: () => void) => mocks.showCallbacks.push(cb),
  onPullDownRefresh: (cb: () => Promise<void>) => mocks.pullCallbacks.push(cb),
}))

import { useMaterialUpload } from '@/pages/index/composables/useMaterialUpload'
import IndexPage from '@/pages/index/index.vue'
import { useAuthStore } from '@/stores/auth'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useMaterialStore } from '@/stores/material'
import CoursePage from '@/subpackages/material/pages/course/index.vue'
import QuestionsPage from '@/subpackages/material/pages/questions/index.vue'
import {
  formatKpSummaryPreview,
  groupKnowledgePointsByChapter,
  resolveMasteryBadge,
} from '@/subpackages/material/utils/courseStudy'
import {
  dedupeKnowledgePointOptions,
  formatQuestionAnswer,
} from '@/subpackages/material/utils/composeHelpers'
import { resetLoadingGuardForTest } from '@/utils/loadingGuard'
import { generatedQuestionFixture } from './fixtures/backendResponses'

const uniGlobal = globalThis as any
let wrapper: VueWrapper | undefined

describe('Home Workbench upload ActionSheet, auto-parse & background task bar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    resetLoadingGuardForTest()
    mocks.request.mockReset()
    mocks.uploadFile.mockReset()
    mocks.loadCallbacks.length = 0
    mocks.showCallbacks.length = 0
    mocks.pullCallbacks.length = 0
  })

  afterEach(() => {
    useBackgroundTaskStore().reset()
    wrapper?.unmount()
    wrapper = undefined
    delete uniGlobal.uni.showActionSheet
    delete uniGlobal.uni.chooseImage
    delete uniGlobal.wx
    vi.restoreAllMocks()
  })

  it('presents ActionSheet for WeChat file (index 0) and photo/album (index 1) and auto-starts parsing', async () => {
    const uploadedIds: string[] = []
    const parseCalls: Array<{ id: string; title?: string }> = []
    let refreshed = 0

    const uploadMaterial = vi.fn(async (_path: string, title?: string) => ({
      id: `m-${uploadedIds.length + 1}`,
      title: title || '默认讲义',
      status: 'pending' as const,
      created_at: '2026-11-17T08:00:00',
    }))

    let actionHandler: ((res: { tapIndex: number }) => void) | null = null
    uniGlobal.uni.showActionSheet = vi.fn(({ success }: any) => {
      actionHandler = success
    })
    const chooseMessageFile = vi.fn(({ success }: any) => {
      success({ tempFiles: [{ path: '/tmp/bayes.pdf', name: '贝叶斯分类器.pdf' }] })
    })
    uniGlobal.wx = { chooseMessageFile }
    uniGlobal.uni.chooseImage = vi.fn(({ success }: any) => {
      success({ tempFilePaths: ['/tmp/camera-note.jpg'] })
    })

    const { chooseFile } = useMaterialUpload({
      getCurrentFolderId: () => 'f-1',
      uploadMaterial,
      startParse: async (id, title) => {
        parseCalls.push({ id, title })
      },
      refreshList: async () => {
        refreshed += 1
      },
      onUploaded: (item) => {
        uploadedIds.push(item.id)
      },
    })

    // 1. 微信聊天文档通道 (tapIndex === 0)
    chooseFile()
    expect(uniGlobal.uni.showActionSheet).toHaveBeenCalledWith(
      expect.objectContaining({
        itemList: ['从微信聊天选择文档 (PDF/Word/TXT)', '拍照或从相册选择讲义图片'],
      }),
    )
    await actionHandler!({ tapIndex: 0 })
    await flushPromises()

    expect(chooseMessageFile).toHaveBeenCalledWith(
      expect.objectContaining({
        count: 1,
        type: 'file',
        extension: ['pdf', 'docx', 'doc', 'txt', 'md'],
      }),
    )
    expect(uploadMaterial).toHaveBeenCalledWith('/tmp/bayes.pdf', '贝叶斯分类器.pdf', 'f-1')
    expect(parseCalls[0]).toEqual({ id: 'm-1', title: '贝叶斯分类器.pdf' })

    // 2. 拍照/相册图片通道 (tapIndex === 1)
    chooseFile()
    await actionHandler!({ tapIndex: 1 })
    await flushPromises()

    expect(uniGlobal.uni.chooseImage).toHaveBeenCalledWith(
      expect.objectContaining({
        count: 1,
        sizeType: ['compressed', 'original'],
        sourceType: ['album', 'camera'],
      }),
    )
    const imageTitle = uploadMaterial.mock.calls[1][1]
    expect(uploadMaterial.mock.calls[1][0]).toBe('/tmp/camera-note.jpg')
    expect(imageTitle).toMatch(/^讲义图片_\d+\.jpg$/)
    expect(parseCalls[1]).toEqual({ id: 'm-2', title: imageTitle })
    expect(uploadedIds).toEqual(['m-1', 'm-2'])
    expect(refreshed).toBe(2)
  })

  it('refreshes active background tasks on IndexPage onShow and keeps BackgroundTaskBar live', async () => {
    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url === '/folders?include_archived=false') return { items: [], total: 0 }
      if (url === '/materials') {
        return {
          items: [
            {
              id: 'm-parsing',
              title: '解析中讲义.pdf',
              status: 'parsing',
              parse_status: 'ocr_processing',
              progress_percentage: 60,
              created_at: '2026-11-17T08:00:00',
            },
          ],
        }
      }
      if (url === '/questions/jobs?active_only=true') {
        return {
          items: [
            {
              id: 'job-home',
              status: 'running',
              material_id: 'm-1',
              total_kps: 4,
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
      throw new Error(`unexpected: ${url}`)
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    const authStore = useAuthStore()
    authStore.setToken('tok-1')

    wrapper = mount(IndexPage, {
      global: {
        plugins: [pinia],
        stubs: {
          AiCoachDrawer: true,
          FolderFilterBar: true,
          FolderFormModal: true,
          MaterialItemCard: true,
        },
      },
    })
    await flushPromises()

    expect(mocks.showCallbacks.length).toBeGreaterThanOrEqual(1)
    mocks.showCallbacks[0]()
    await flushPromises()

    const barText = wrapper.text()
    expect(barText).toContain('解析中讲义.pdf')
    expect(barText).toContain('2/4 考点')
  })
})

describe('Course Study Card helpers, mastery badges, and force re-parse reload', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
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
    vi.restoreAllMocks()
  })

  it('groups L2/L3 KPs under L1 chapters, preserves flat/orphan KPs, maps mastery badges, and strips raw markdown/math', () => {
    const groups = groupKnowledgePointsByChapter([
      {
        id: 'c-2',
        material_id: 'm-1',
        version_id: 'v-1',
        parent_id: null,
        name: '第二章 朴素贝叶斯',
        level: 1,
        sort_order: 2,
      },
      {
        id: 'c-1',
        material_id: 'm-1',
        version_id: 'v-1',
        parent_id: null,
        name: '第一章 概率基础',
        level: 1,
        sort_order: 1,
      },
      {
        id: 'kp-1-1',
        material_id: 'm-1',
        version_id: 'v-1',
        parent_id: 'c-1',
        name: '条件概率',
        level: 2,
        sort_order: 1,
      },
      {
        id: 'kp-2-1',
        material_id: 'm-1',
        version_id: 'v-1',
        parent_id: 'c-2',
        name: '拉普拉斯平滑',
        level: 2,
        sort_order: 1,
      },
      {
        id: 'kp-flat',
        material_id: 'm-1',
        version_id: 'v-1',
        parent_id: null,
        name: '独立总结节点',
        level: 1,
        sort_order: 3,
      },
    ])

    expect(groups.map((g) => g.title)).toEqual(['第一章 概率基础', '第二章 朴素贝叶斯', '其他核心考点'])
    expect(groups[0].points.map((p) => p.id)).toEqual(['kp-1-1'])
    expect(groups[2].points.map((p) => p.id)).toEqual(['kp-flat'])

    expect(resolveMasteryBadge(null)).toEqual({ text: '未练', tone: 'unlearned' })
    expect(resolveMasteryBadge({ score: 0.25, level: 'weak', practiceCount: 2 })).toEqual({
      text: '薄弱 25%',
      tone: 'weak',
    })
    expect(resolveMasteryBadge({ score: 0.65, level: 'basic', practiceCount: 2 })).toEqual({
      text: '基本掌握 65%',
      tone: 'basic',
    })
    expect(resolveMasteryBadge({ score: 0.88, level: 'proficient', practiceCount: 4 })).toEqual({
      text: '熟练 88%',
      tone: 'proficient',
    })

    const preview = formatKpSummaryPreview({
      structured_content: {
        core_summary: '**条件独立**：$$P(X|Y) \\propto \\prod \\alpha$$',
        key_takeaways: [],
        key_formulas: [],
        boundary_notes: [],
      },
      description: '旧描述',
    })
    expect(preview).toBe('条件独立：P(X|Y) ∝ ∏ α')
    expect(preview).not.toContain('**')
    expect(preview).not.toContain('$')
  })

  it('triggers force=true re-parse on CoursePage and auto-reloads KPs when status returns to ready', async () => {
    let reparseRequested = false
    mocks.request.mockImplementation(async ({ url, method }: { url: string; method?: string }) => {
      if (url === '/materials/m-1' && method === 'GET') {
        return {
          id: 'm-1',
          title: '贝叶斯分类器.pdf',
          folder_id: 'f-1',
          status: 'ready',
          created_at: '2026-11-17T08:00:00',
        }
      }
      if (url === '/materials/m-1/parse?force=true' && method === 'POST') {
        reparseRequested = true
        return { message: 'queued' }
      }
      if (url === '/materials/m-1/knowledge-tree') {
        return {
          material_id: 'm-1',
          version_id: reparseRequested ? 'v-2' : 'v-1',
          nodes: [
            {
              id: 'kp-ch',
              material_id: 'm-1',
              version_id: reparseRequested ? 'v-2' : 'v-1',
              parent_id: null,
              name: '第一章 贝叶斯定理',
              level: 1,
              sort_order: 1,
              children: [
                {
                  id: 'kp-leaf',
                  material_id: 'm-1',
                  version_id: reparseRequested ? 'v-2' : 'v-1',
                  parent_id: 'kp-ch',
                  name: reparseRequested ? '干净公式考点' : '旧版考点',
                  description: '定义',
                  level: 2,
                  sort_order: 1,
                  children: [],
                },
              ],
            },
          ],
        }
      }
      if (url === '/questions?material_id=m-1') return { items: [] }
      if (url.startsWith('/mastery')) return { total_points: 1, points: [] }
      throw new Error(`unexpected: ${url}`)
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(CoursePage, {
      global: {
        plugins: [pinia],
        stubs: {
          BackgroundTaskBar: true,
          AiCoachDrawer: true,
          RichContent: { props: ['content'], template: '<div>{{ content }}</div>' },
          'scroll-view': { template: '<div><slot /></div>' },
        },
      },
    })

    await mocks.loadCallbacks[0]({ id: 'm-1' })
    await flushPromises()
    expect(wrapper.text()).toContain('旧版考点')

    await wrapper.find('.reparse-top-btn').trigger('tap')
    await flushPromises()
    expect(reparseRequested).toBe(true)

    await useBackgroundTaskStore().pollOnce()
    await flushPromises()
    expect(wrapper.text()).toContain('干净公式考点')
  })
})

describe('Non-blocking Question Compose Page, dedup, kp_id preselect & preview card', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetLoadingGuardForTest()
    mocks.request.mockReset()
    mocks.loadCallbacks.length = 0
    mocks.showCallbacks.length = 0
  })

  afterEach(() => {
    useBackgroundTaskStore().reset()
    wrapper?.unmount()
    wrapper = undefined
    vi.restoreAllMocks()
  })

  it('deduplicates KP chips, preselects kp_id, runs async job banner, and switches to RichContent preview', async () => {
    let pollCount = 0
    mocks.request.mockImplementation(async ({ url, method }: { url: string; method?: string }) => {
      if (url === '/materials/m-1/knowledge-tree') {
        return {
          material_id: 'm-1',
          version_id: 'v-1',
          nodes: [
            { id: 'kp-1', name: '朴素贝叶斯分类器', level: 1, sort_order: 1, children: [] },
            { id: 'kp-2', name: '朴素贝叶斯（分类器）', level: 1, sort_order: 2, children: [] },
            { id: 'kp-3', name: '拉普拉斯平滑', level: 1, sort_order: 3, children: [] },
          ],
        }
      }
      if (url === '/questions/jobs?active_only=true' || url === '/materials') {
        return { items: [], total: 0 }
      }
      if (url === '/questions/jobs' && method === 'POST') {
        return {
          id: 'job-q1',
          status: 'queued',
          material_id: 'm-1',
          total_kps: 1,
          completed_kps: 0,
          generated_count: 0,
          question_ids: [],
          created_at: '',
          updated_at: '',
        }
      }
      if (url === '/questions/jobs/job-q1' && method === 'GET') {
        pollCount += 1
        return {
          id: 'job-q1',
          status: 'completed',
          material_id: 'm-1',
          total_kps: 1,
          completed_kps: 1,
          generated_count: 1,
          batch_id: 'b-q1',
          question_ids: ['q-100'],
          created_at: '',
          updated_at: '',
          completed_at: '2026-11-17T12:00:00',
        }
      }
      if (url.startsWith('/questions?batch_id=b-q1')) {
        return {
          items: [
            generatedQuestionFixture({
              id: 'q-100',
              knowledge_point_id: 'kp-3',
              knowledge_point_name: '拉普拉斯平滑',
              batch_id: 'b-q1',
              stem: '计算平滑后概率 $$P(x_j|c_k)$$',
              options: [
                { key: 'A.', content: 'A. 分子加 1，分母加类别数' },
                { key: 'B', content: 'B、直接置零' },
              ],
              answer: 'A',
              analysis: '**拉普拉斯平滑**避免零概率导致连乘坍缩。',
              grading_rubric: { total_score: 2, points: ['分子加 1'] },
            }),
          ],
        }
      }
      if (url.startsWith('/questions/batches')) {
        return { items: [], total: 0 }
      }
      throw new Error(`unexpected: ${url}`)
    })

    const deduped = dedupeKnowledgePointOptions([
      { id: 'kp-1', name: '朴素贝叶斯分类器' },
      { id: 'kp-2', name: '朴素贝叶斯 分类器' },
    ])
    expect(deduped).toHaveLength(1)
    expect(
      formatQuestionAnswer({ type: 'fill_in_blank', answer: '先验概率 ||| P(Y); 似然概率' }),
    ).toBe('先验概率 或 P(Y) ； 似然概率')

    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(QuestionsPage, {
      global: {
        plugins: [pinia],
        stubs: {
          BackgroundTaskBar: true,
          RichContent: { props: ['content'], template: '<div class="stub-rich">{{ content }}</div>' },
        },
      },
    })

    await mocks.loadCallbacks[0]({ material_id: 'm-1', kp_id: 'kp-3' })
    await flushPromises()

    // 考点范围收拢进摘要卡并支持打开抽屉，仅 kp-3 被预选，无死板预设模式
    expect(wrapper.find('.kp-summary-meta').text()).toContain('已选 1 个考点')
    expect(wrapper.findAll('.kp-chip.active')).toHaveLength(1)
    expect(wrapper.find('.kp-chip.active').text()).toContain('拉普拉斯平滑')
    expect(wrapper.text()).not.toContain('闪电速刷')

    await wrapper.find('.picker-open-btn').trigger('tap')
    await flushPromises()
    expect(wrapper.findAll('.acc-body .kp-chip')).toHaveLength(2)
    await wrapper.find('.footer-confirm-btn').trigger('tap')
    await flushPromises()

    await wrapper.find('.full-btn').trigger('tap')
    await flushPromises()

    // 非阻塞进度条与自由返回按钮可见
    expect(wrapper.find('.job-progress-banner').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在后台生成题目 (0 / 1 考点)')
    expect(wrapper.text()).toContain('先去浏览讲义')
    expect(wrapper.text()).toContain('返回工作台')

    await useBackgroundTaskStore().pollOnce()
    await flushPromises()

    expect(pollCount).toBe(1)
    // 完成后自动切入核对视图，渲染知识点徽标、去重前缀选项及可折叠答案/解析/采分点
    expect(wrapper.find('.q-kp-tag').text()).toBe('拉普拉斯平滑')
    expect(wrapper.find('.option-item').text()).toContain('A.')
    expect(wrapper.find('.option-item').text()).not.toContain('A. A.')
    expect(wrapper.find('.answer-panel').exists()).toBe(false)

    await wrapper.find('.answer-toggle-bar').trigger('tap')
    await flushPromises()
    expect(wrapper.find('.answer-panel').exists()).toBe(true)
    expect(wrapper.find('.answer-panel').text()).toContain('分子加 1')
  })

  it('opens generated batch directly when navigated from BackgroundTaskBar with folder_id & batch_id', async () => {
    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url === '/folders/f-1/knowledge-points') {
        return {
          folder_id: 'f-1',
          groups: [
            {
              material_id: 'm-1',
              material_title: '机器学习导论.pdf',
              knowledge_points: [{ id: 'kp-1', name: '交叉验证', level: 1, sort_order: 1 }],
            },
          ],
          total: 1,
        }
      }
      if (url.startsWith('/questions?batch_id=b-folder')) {
        return {
          items: [
            generatedQuestionFixture({
              id: 'q-folder-1',
              knowledge_point_id: 'kp-1',
              knowledge_point_name: '交叉验证',
              batch_id: 'b-folder',
            }),
          ],
        }
      }
      if (url.startsWith('/questions/batches')) return { items: [], total: 0 }
      throw new Error(`unexpected: ${url}`)
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(QuestionsPage, {
      global: {
        plugins: [pinia],
        stubs: {
          BackgroundTaskBar: true,
          RichContent: { props: ['content'], template: '<div class="stub-rich">{{ content }}</div>' },
        },
      },
    })

    await mocks.loadCallbacks[0]({
      folder_id: 'f-1',
      view: 'generated',
      batch_id: 'b-folder',
    })
    await flushPromises()

    expect(wrapper.find('.q-kp-tag').text()).toBe('交叉验证')
    expect(wrapper.find('.start-btn').attributes('disabled')).toBeUndefined()
  })
})
