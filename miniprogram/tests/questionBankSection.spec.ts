/**
 * 题库区块的**取数接线**与刷新/展开详情测试。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import QuestionBankSection from '@/pages/review/components/QuestionBankSection.vue'

const requestedUrls = (): string[] => requestMock.mock.calls.map((c) => String(c[0]?.url ?? ''))

describe('QuestionBankSection 取数接线', () => {
  beforeEach(() => {
    requestMock.mockReset()
    requestMock.mockResolvedValue({ items: [], total: 0 })
  })

  it('挂载后自动拉取题目批次，而不是只能靠手点「刷新」', async () => {
    mount(QuestionBankSection, { props: { wrongRecords: [] } })
    await flushPromises()

    const urls = requestedUrls()
    expect(
      urls.some((u) => u.includes('/questions/batches')),
      `挂载后应请求批次列表，实际请求：${JSON.stringify(urls)}`,
    ).toBe(true)
  })

  it('exposes refresh() via defineExpose and supports lazy answer/analysis expansion', async () => {
    requestMock.mockImplementation(async ({ url }: { url: string }) => {
      if (url.startsWith('/questions/batches')) {
        return {
          items: [
            {
              batch_id: 'batch_1',
              question_count: 1,
              available_count: 1,
              pending_review_count: 0,
              created_at: '2026-11-17T08:00:00',
              sources: [{ material_id: 'm-1', material_title: '贝叶斯分类器.pdf' }],
            },
          ],
          total: 1,
        }
      }
      if (url.startsWith('/questions?')) {
        return {
          items: [
            {
              id: 'q-1',
              question_type: 'single_choice',
              stem: '公式 $P(Y=c_k|X=x)$ 的含义？',
              batch_id: 'batch_1',
              status: 'available',
            },
          ],
          total: 1,
        }
      }
      if (url === '/questions/q-1') {
        return {
          id: 'q-1',
          question_type: 'single_choice',
          stem: '公式 $P(Y=c_k|X=x)$ 的含义？',
          options: [{ key: 'A', content: '后验概率' }],
          answer: 'A',
          analysis: '由贝叶斯定理直接可得后验概率表达式。',
        }
      }
      throw new Error(`unexpected: ${url}`)
    })

    const wrapper = mount(QuestionBankSection, {
      props: { wrongRecords: [] },
      global: {
        stubs: {
          'rich-text': {
            props: ['nodes'],
            template: '<div class="rt-stub">{{ JSON.stringify(nodes) }}</div>',
          },
        },
      },
    })
    await flushPromises()

    expect(typeof (wrapper.vm as { refresh?: unknown }).refresh).toBe('function')

    await wrapper.get('.bank-expand-btn').trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('查看解析')

    await wrapper.get('.bank-detail-btn').trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('参考答案：')
    expect(wrapper.text()).toContain('后验概率')
    expect(wrapper.text()).toContain('深度解析：')

    await (wrapper.vm as { refresh: () => Promise<void> }).refresh()
    await flushPromises()
    expect(requestedUrls().filter((u) => u.includes('/questions/batches')).length).toBeGreaterThanOrEqual(2)
  })
})
