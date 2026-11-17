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
  request: mocks.request,
  uploadFile: mocks.uploadFile,
}))

vi.mock('@dcloudio/uni-app', () => ({
  onLoad: (cb: (options: Record<string, string>) => Promise<void>) => mocks.loadCallbacks.push(cb),
  onShow: (cb: () => void) => mocks.showCallbacks.push(cb),
  onPullDownRefresh: (cb: () => Promise<void>) => mocks.pullCallbacks.push(cb),
}))

import { adaptKnowledgeSnippet, apiGetKnowledgePointSnippets, apiUploadAvatar } from '@/api'
import { useAuthStore } from '@/stores/auth'
import CoursePage from '@/subpackages/material/pages/course/index.vue'

let wrapper: VueWrapper | undefined

describe('knowledge snippet adaptation & course page rendering', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    mocks.request.mockReset()
    mocks.uploadFile.mockReset()
    mocks.loadCallbacks.length = 0
    mocks.showCallbacks.length = 0
    mocks.pullCallbacks.length = 0
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  it('adapts 1-based page_index and optional chapter_title from SnippetSourceResponse', async () => {
    const first = adaptKnowledgeSnippet({
      id: 's-1',
      page_index: 3,
      chapter_title: ' 第三章 进程调度 ',
      content: '时间片轮转调度适用于分时系统。',
    })
    const second = adaptKnowledgeSnippet({
      id: 's-2',
      page_index: 0,
      chapter_title: '   ',
      content: '回退页码示例。',
    })

    expect(first).toMatchObject({ page_index: 3, chapter_title: '第三章 进程调度' })
    expect(second).toMatchObject({ page_index: 1, chapter_title: null })

    mocks.request.mockResolvedValueOnce({
      knowledge_point_id: 'kp-1',
      snippets: [
        { id: 's-1', page_index: 3, chapter_title: '第三章', content: '内容一' },
        { id: 's-2', page_index: 7, chapter_title: '', content: '内容二' },
      ],
    })

    const res = await apiGetKnowledgePointSnippets('kp-1')
    expect(res.snippets.map((s) => s.page_index)).toEqual([3, 7])
    expect(res.snippets[0].chapter_title).toBe('第三章')
    expect(res.snippets[1].chapter_title).toBeNull()
  })

  it('renders structured study card, real mastery badge, collapsed snippets, and garbled snippet guard', async () => {
    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url === '/materials/m-1') {
        return {
          id: 'm-1',
          title: '操作系统讲义.pdf',
          status: 'ready',
          created_at: '2026-11-17T08:00:00',
        }
      }
      if (url === '/materials/m-1/knowledge-tree') {
        return {
          material_id: 'm-1',
          version_id: 'v-1',
          nodes: [
            {
              id: 'kp-1',
              material_id: 'm-1',
              version_id: 'v-1',
              parent_id: null,
              name: '进程调度',
              description: '**CPU** 调度算法与 $T_w$ 分析',
              structured_content: {
                core_summary: '按就绪队列策略分配 CPU 时间片，优化吞吐与响应。',
                key_takeaways: ['短作业优先平均等待时间最短', '时间片轮转兼顾交互响应'],
                key_formulas: ['T_w = T_{turn} - T_{service}'],
                boundary_notes: ['时间片过小会增加上下文切换开销'],
              },
              level: 1,
              sort_order: 1,
              is_low_confidence: false,
              children: [],
            },
          ],
        }
      }
      if (url === '/questions?material_id=m-1') {
        return { items: [] }
      }
      if (url.startsWith('/mastery')) {
        return {
          total_points: 1,
          points: [
            {
              knowledge_point_id: 'kp-1',
              knowledge_name: '进程调度',
              mastery_score: 0.85,
              level: 'proficient',
              practice_count: 3,
              correct_count: 3,
            },
          ],
        }
      }
      if (url === '/knowledge/kp-1') {
        return {
          id: 'kp-1',
          material_id: 'm-1',
          version_id: 'v-1',
          parent_id: null,
          name: '进程调度',
          description: 'CPU 调度算法与周转时间分析',
          structured_content: {
            core_summary: '按就绪队列策略分配 CPU 时间片，优化吞吐与响应。',
            key_takeaways: ['短作业优先平均等待时间最短', '时间片轮转兼顾交互响应'],
            key_formulas: ['T_w = T_{turn} - T_{service}'],
            boundary_notes: ['时间片过小会增加上下文切换开销'],
          },
          level: 1,
          is_low_confidence: false,
          batch_id: 'b-1',
          created_at: '2026-11-17T08:00:00',
        }
      }
      if (url === '/knowledge/kp-1/snippets') {
        return {
          knowledge_point_id: 'kp-1',
          snippets: [
            {
              id: 's-1',
              material_id: 'm-1',
              version_id: 'v-1',
              page_index: 3,
              snippet_index: 0,
              chapter_title: '第 3 章 调度策略',
              content: '短作业优先可最小化平均等待时间。',
              char_length: 16,
            },
            {
              id: 's-2',
              material_id: 'm-1',
              version_id: 'v-1',
              page_index: 7,
              snippet_index: 1,
              chapter_title: '',
              content: 'AB&A&\n"#$"$\n!" ! #',
              char_length: 17,
            },
          ],
        }
      }
      throw new Error(`unexpected request: ${url}`)
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(CoursePage, {
      global: {
        plugins: [pinia],
        stubs: {
          BackgroundTaskBar: true,
          AiCoachDrawer: true,
          RichContent: {
            props: ['content'],
            template: '<div class="stub-rich">{{ content }}</div>',
          },
          'scroll-view': { template: '<div><slot /></div>' },
        },
      },
    })

    expect(mocks.loadCallbacks).toHaveLength(1)
    await mocks.loadCallbacks[0]({ id: 'm-1' })
    await flushPromises()

    expect(wrapper.find('.mastery-pill').text()).toBe('熟练 85%')
    expect(wrapper.text()).not.toContain('高频必考')
    expect(wrapper.text()).not.toContain('L1')

    await wrapper.find('.tree-node-card').trigger('tap')
    await flushPromises()

    // 原文溯源默认折叠，且结构化要点已直接呈现
    expect(wrapper.findAll('.snip-page')).toHaveLength(0)
    expect(wrapper.text()).toContain('核心定义')
    expect(wrapper.text()).toContain('关键结论')
    expect(wrapper.text()).toContain('核心公式与符号')
    expect(wrapper.text()).toContain('适用条件与易错边界')
    expect(wrapper.text()).toContain('查看教材原文依据 (2处)')

    await wrapper.find('.snippet-toggle-row').trigger('tap')
    await flushPromises()

    const pages = wrapper.findAll('.snip-page').map((node) => node.text())
    const chapters = wrapper.findAll('.snip-chapter').map((node) => node.text())
    expect(pages).toEqual(['第 3 页', '第 7 页'])
    expect(chapters).toEqual(['第 3 章 调度策略'])
    // 第 2 条乱码切片被安全折叠提示替换，不再直接倾倒 AB&A& 乱码
    expect(wrapper.text()).toContain('检测到旧版讲义公式编码异常')
    expect(wrapper.text()).not.toContain('AB&A&')
  })

  it('encapsulates avatar upload in apiUploadAvatar and authStore.updateAvatar', async () => {
    const updatedUser = {
      id: 'u-1',
      nickname: '学员',
      avatar_url: 'https://cdn.example.com/avatar.png',
    }
    mocks.uploadFile.mockResolvedValue(updatedUser)

    const direct = await apiUploadAvatar('/tmp/avatar.png')
    expect(direct).toEqual(updatedUser)
    expect(mocks.uploadFile).toHaveBeenCalledWith('/tmp/avatar.png', 'file', undefined, '/users/me/avatar')

    const authStore = useAuthStore()
    const result = await authStore.updateAvatar('/tmp/avatar2.png')
    expect(result).toEqual(updatedUser)
    expect(authStore.user).toEqual(updatedUser)
  })
})
