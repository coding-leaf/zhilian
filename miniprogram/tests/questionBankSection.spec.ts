/**
 * 题库区块的**取数接线**测试。
 *
 * 为什么单独有这个文件：`questionBank.spec.ts` 的 16 个用例测的是 `useQuestionBank`
 * 组合式函数本身，它们全绿，而「我的题目」在页面上恒为空——因为组件从未调用过
 * `loadBatches`（只有 `@tap` 引用、无生命周期钩子）。**被测单元正确不等于接线正确**，
 * 只有真正挂载组件才拦得住这一类缺陷。
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
    // 批次列表接口的分页响应形状：{ items, total }
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
})
