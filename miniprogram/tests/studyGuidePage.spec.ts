import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  loadCallbacks: [] as Array<(options: Record<string, string>) => Promise<void>>,
}))

vi.mock('@/utils/request', () => ({
  request: (options: any) => mocks.request(options),
  uploadFile: vi.fn(),
}))

vi.mock('@dcloudio/uni-app', () => ({
  onLoad: (cb: (options: Record<string, string>) => Promise<void>) => mocks.loadCallbacks.push(cb),
  onShow: vi.fn(),
  onPullDownRefresh: vi.fn(),
}))

import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import KnowledgePage from '@/subpackages/material/pages/knowledge/index.vue'
import CoursePage from '@/subpackages/material/pages/course/index.vue'
import { LONG_REQUEST_TIMEOUT_MS } from '@/utils/requestError'
import type { StudyGuideContent } from '@/types'

let wrapper: VueWrapper | undefined

const sampleGuide: StudyGuideContent = {
  schema_version: 1,
  exam_positioning: '本章核心压轴推导题来源，常考几何间隔最大化。',
  core_definition: '通过最大化正负样本到超平面的最小几何间隔求取最优决策边界。',
  symbol_table: [
    { symbol: '$w$', meaning: '超平面法向量', note: '$w \\in \\mathbb{R}^d$' },
    { symbol: '$b$', meaning: '截距项', note: '标量偏移' },
  ],
  key_formulas: ['$$\\gamma = \\frac{y_i(w^T x_i + b)}{\\|w\\|}$$'],
  derivation_steps: [
    {
      step_title: '缩放约束标准化',
      formula: '$$y_i(w^T x_i + b) \\ge 1$$',
      explanation: '令最近样本函数间隔为 1，最大化 $1/\\|w\\|$ 等价于最小化 $\\frac{1}{2}\\|w\\|^2$。',
    },
  ],
  worked_examples: [
    {
      title: '典型例题 1：计算最大间隔超平面',
      question_type: '计算题',
      problem: '已知正样本 $(1,1)$，负样本 $(-1,-1)$，求最优超平面。',
      solution_idea: '利用对称性与支持向量等距条件求 $w$ 和 $b$。',
      solution_steps: ['设 $w=(a,a)$，$b=0$', '代入函数间隔为 1 解得 $w=(0.5,0.5)$'],
      final_answer: '$0.5x_1 + 0.5x_2 = 0$',
    },
  ],
  comparisons: [
    {
      target_concept: '感知机',
      similarities: '均寻找线性分离超平面',
      differences: '感知机仅求任意可行解，SVM 求唯一最大间隔解',
      exam_distinction: '有唯一解与间隔最大化的是 SVM',
    },
  ],
  pitfalls: [
    {
      mistake: '混淆函数间隔与几何间隔',
      why_wrong: '忘记除以 $\\|w\\|$ 导致尺度放缩失效',
      correction: '几何间隔必须归一化法向量模长 $\\|w\\|$。',
    },
  ],
  memory_anchors: ['函数间隔定尺度，几何间隔真距离', '支持向量决定边界'],
}

const pageStubs = {
  AiCoachDrawer: true,
  BackgroundTaskBar: true,
  RichContent: {
    props: ['content'],
    template: '<div class="stub-rich">{{ content }}</div>',
  },
}

describe('full-screen study guide page and prewarm integration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    mocks.request.mockReset()
    mocks.loadCallbacks.length = 0
  })

  afterEach(() => {
    vi.useRealTimers()
    useBackgroundTaskStore().reset()
    wrapper?.unmount()
    wrapper = undefined
    vi.restoreAllMocks()
  })

  it('shows Stage 1 preview while generating on empty status, passes 60s timeout, and switches across 4 segmented tabs', async () => {
    let generateTimeout: number | undefined
    mocks.request.mockImplementation(async (opts: { url: string; method?: string; timeout?: number }) => {
      if (opts.url === '/knowledge/kp-svm' && opts.method === 'GET') {
        return {
          id: 'kp-svm',
          material_id: 'm-1',
          name: '硬间隔支持向量机',
          description: '最大间隔分类器',
          structured_content: {
            core_summary: 'Stage 1 预览：最大化分类间隔。',
            key_takeaways: [],
            key_formulas: ['$$\\min \\frac{1}{2}\\|w\\|^2$$'],
            boundary_notes: [],
          },
          level: 2,
          created_at: '2026-11-25T00:00:00',
        }
      }
      if (opts.url === '/knowledge/kp-svm/snippets') {
        return {
          knowledge_point_id: 'kp-svm',
          snippets: [
            { id: 's-1', page_index: 6, page_end: 7, chapter_title: 'SVM 推导', content: '原文第 6-7 页内容' },
          ],
        }
      }
      if (opts.url === '/knowledge/kp-svm/study-guide' && opts.method === 'GET') {
        return {
          knowledge_point_id: 'kp-svm',
          status: 'empty',
          study_guide: null,
          generated_at: null,
        }
      }
      if (opts.url === '/knowledge/kp-svm/study-guide/generate' && opts.method === 'POST') {
        generateTimeout = opts.timeout
        return {
          knowledge_point_id: 'kp-svm',
          status: 'ready',
          study_guide: sampleGuide,
          generated_at: '2026-11-25T10:00:00Z',
        }
      }
      if (opts.url.startsWith('/mastery')) return { total_points: 0, points: [] }
      throw new Error(`unexpected: ${opts.method} ${opts.url}`)
    })

    wrapper = mount(KnowledgePage, { global: { stubs: pageStubs } })
    await mocks.loadCallbacks[0]({ kp_id: 'kp-svm', material_id: 'm-1', chapter: '支持向量机' })
    await flushPromises()

    expect(generateTimeout).toBe(LONG_REQUEST_TIMEOUT_MS)
    expect(wrapper.text()).toContain('硬间隔支持向量机')
    expect(wrapper.text()).toContain('支持向量机')
    expect(wrapper.text()).toContain('考法与直觉定位')
    expect(wrapper.text()).toContain('核心符号速查表')
    expect(wrapper.text()).toContain('30 秒考前速记锚点')

    // 切到「典型例题」并展开标准解答
    const tabs = wrapper.findAll('.tab-item')
    await tabs[1].trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('典型例题 1：计算最大间隔超平面')
    expect(wrapper.text()).not.toContain('最终答案')
    await wrapper.get('.solution-toggle-btn').trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('最终答案')
    expect(wrapper.text()).toContain('0.5x_1 + 0.5x_2 = 0')

    // 切到「对比与避坑」
    await tabs[2].trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('感知机')
    expect(wrapper.text()).toContain('混淆函数间隔与几何间隔')

    // 切到「教材原文」
    await tabs[3].trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('查看教材原文依据 (1处)')
  })

  it('polls GET every 2.5s when status is generating, shows Stage 1 preview, and supports force regenerate', async () => {
    vi.useFakeTimers()
    let guidePollCalls = 0
    const forceBodies: Array<unknown> = []

    mocks.request.mockImplementation(async (opts: { url: string; method?: string; data?: unknown }) => {
      if (opts.url === '/knowledge/kp-2') {
        return {
          id: 'kp-2',
          material_id: 'm-1',
          name: '核技巧',
          structured_content: { core_summary: 'Stage 1 核函数预览摘要' },
          level: 2,
          created_at: '',
        }
      }
      if (opts.url === '/knowledge/kp-2/snippets') {
        return { knowledge_point_id: 'kp-2', snippets: [] }
      }
      if (opts.url === '/knowledge/kp-2/study-guide' && opts.method === 'GET') {
        guidePollCalls += 1
        if (guidePollCalls >= 2) {
          return {
            knowledge_point_id: 'kp-2',
            status: 'ready',
            study_guide: sampleGuide,
            generated_at: '2026-11-25T10:05:00Z',
          }
        }
        return { knowledge_point_id: 'kp-2', status: 'generating', study_guide: null, generated_at: null }
      }
      if (opts.url === '/knowledge/kp-2/study-guide/generate' && opts.method === 'POST') {
        forceBodies.push(opts.data)
        return {
          knowledge_point_id: 'kp-2',
          status: 'ready',
          study_guide: sampleGuide,
          generated_at: '2026-11-25T10:06:00Z',
        }
      }
      if (opts.url.startsWith('/mastery')) return { total_points: 0, points: [] }
      throw new Error(`unexpected: ${opts.method} ${opts.url}`)
    })

    wrapper = mount(KnowledgePage, { global: { stubs: pageStubs } })
    await mocks.loadCallbacks[0]({ kp_id: 'kp-2', material_id: 'm-1' })
    await flushPromises()

    expect(wrapper.text()).toContain('正在深度精讲生成中')
    expect(wrapper.text()).toContain('Stage 1 核函数预览摘要')

    await vi.advanceTimersByTimeAsync(2500)
    await flushPromises()
    expect(guidePollCalls).toBe(2)
    expect(wrapper.text()).toContain('考法与直觉定位')

    await wrapper.get('.regen-btn').trigger('tap')
    await flushPromises()
    expect(forceBodies).toEqual([{ force: true }])
  })

  it('starts chapter prewarm from CoursePage and syncs progress via BackgroundTaskStore', async () => {
    let statusCalls = 0
    mocks.request.mockImplementation(async (opts: { url: string; method?: string }) => {
      if (opts.url === '/materials/m-9') {
        return { id: 'm-9', title: '机器学习第3章.pdf', current_version_id: 'v-9', status: 'ready', created_at: '' }
      }
      if (opts.url === '/materials/m-9/knowledge-tree') {
        return {
          material_id: 'm-9',
          version_id: 'v-9',
          nodes: [
            { id: 'kp-a', material_id: 'm-9', version_id: 'v-9', name: '正则化', level: 1, sort_order: 1, has_study_guide: false, children: [] },
            { id: 'kp-b', material_id: 'm-9', version_id: 'v-9', name: '交叉验证', level: 1, sort_order: 2, has_study_guide: true, children: [] },
          ],
        }
      }
      if (opts.url === '/questions?material_id=m-9') return { items: [] }
      if (opts.url.startsWith('/mastery')) return { total_points: 2, points: [] }
      if (opts.url.startsWith('/materials/m-9/study-guides/status')) {
        statusCalls += 1
        if (statusCalls === 1) {
          return { material_id: 'm-9', version_id: 'v-9', status: 'idle', total_kps: 2, ready_kps: 1, failed_kps: 0, current_kp_name: null }
        }
        return { material_id: 'm-9', version_id: 'v-9', status: 'completed', total_kps: 2, ready_kps: 2, failed_kps: 0, current_kp_name: null }
      }
      if (opts.url === '/materials/m-9/study-guides/prewarm' && opts.method === 'POST') {
        return { material_id: 'm-9', version_id: 'v-9', status: 'queued', total_kps: 2, ready_kps: 1 }
      }
      throw new Error(`unexpected: ${opts.method} ${opts.url}`)
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(CoursePage, {
      global: {
        plugins: [pinia],
        stubs: pageStubs,
      },
    })

    await mocks.loadCallbacks[0]({ id: 'm-9' })
    await flushPromises()

    expect(wrapper.text()).toContain('已生成 1/2 项')
    expect(wrapper.get('.prewarm-btn').text()).toBe('一键生成本章精讲')

    await wrapper.get('.prewarm-btn').trigger('tap')
    await flushPromises()

    const taskStore = useBackgroundTaskStore()
    expect(taskStore.activePrewarmMaterialIds).toEqual(['m-9'])
    expect(taskStore.visibleTasks[0]).toMatchObject({
      key: 'guide:m-9',
      kind: 'study_guide_prewarm',
      status: 'active',
    })

    await taskStore.pollOnce()
    await flushPromises()
    expect(taskStore.visibleTasks[0]).toMatchObject({
      key: 'guide:m-9',
      kind: 'study_guide_prewarm',
      status: 'completed',
      actionLabel: '去查看',
    })
    expect(wrapper.text()).toContain('全章精讲已就绪')
  })
})
