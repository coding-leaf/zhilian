import { beforeEach, describe, expect, it, vi } from 'vitest'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import { useQuestionBank } from '@/pages/review/composables/useQuestionBank'
import { practiceDetailFixture, questionBatchListFixture } from './fixtures/backendResponses'

/** 该批次的两道可选题目 + 一道待审核题目。 */
const batchAQuestions = {
  items: [
    {
      id: 'q-1',
      question_type: 'single_choice',
      stem: '题干一',
      batch_id: 'batch_a',
      status: 'available',
    },
    {
      id: 'q-2',
      question_type: 'short_answer',
      stem: '题干二',
      batch_id: 'batch_a',
      status: 'available',
    },
    {
      id: 'q-3',
      question_type: 'true_false',
      stem: '题干三（待审核）',
      batch_id: 'batch_a',
      status: 'pending_review',
    },
  ],
  total: 3,
}

const unbatchedQuestions = {
  items: [
    {
      id: 'q-hist',
      question_type: 'single_choice',
      stem: '历史题干',
      batch_id: null,
      status: 'available',
    },
  ],
  total: 1,
}

let availableForBatchA: { items: unknown[]; total: number }
let batchListForTest: unknown
/** 可选：按页码覆盖批次列表响应（默认每页都返回 batchListForTest）。 */
let batchPageOverridesForTest: Record<number, unknown> | null = null

function isQuestionList(url: string): boolean {
  return url.startsWith('/questions?')
}

function questionListCalls(): any[] {
  return requestMock.mock.calls.filter(([options]: any[]) => isQuestionList(options.url))
}

function mockRequests() {
  requestMock.mockImplementation(async (options: any) => {
    const url: string = options.url
    if (url.startsWith('/questions/batches')) {
      const page = Number(/page=(\d+)/.exec(url)?.[1] ?? 1)
      return batchPageOverridesForTest?.[page] ?? batchListForTest
    }
    if (isQuestionList(url)) {
      if (url.includes('review_status=available')) {
        // 「立即开练」解析整批题目 ID 的路径
        return url.includes('batch_id=batch_a') ? availableForBatchA : unbatchedQuestions
      }
      if (url.includes('batch_id=batch_a')) return batchAQuestions
      if (url.includes('unbatched=true')) return unbatchedQuestions
    }
    if (url === '/practices') return { id: 'p-1' }
    if (url.startsWith('/practices/')) return practiceDetailFixture
    throw new Error(`unexpected request: ${url}`)
  })
}

describe('question bank section', () => {
  beforeEach(() => {
    requestMock.mockReset()
    batchListForTest = questionBatchListFixture
    batchPageOverridesForTest = null
    mockRequests()
    availableForBatchA = {
      items: [batchAQuestions.items[0], batchAQuestions.items[1]],
      total: 2,
    }
  })

  it('加载批次只发一次批次请求，未展开的批次不发题目列表请求', async () => {
    const bank = useQuestionBank()

    await bank.loadBatches()

    expect(bank.batches.value).toHaveLength(2)
    expect(bank.selectedCount.value).toBe(0)
    expect(questionListCalls()).toHaveLength(0)
  })

  it('展开时才按需加载题目，收起后再展开走缓存', async () => {
    const bank = useQuestionBank()
    await bank.loadBatches()

    await bank.toggleExpand('batch_a')

    expect(questionListCalls()).toHaveLength(1)
    expect(bank.questionsFor('batch_a').map((item) => item.id)).toEqual(['q-1', 'q-2', 'q-3'])

    await bank.toggleExpand('batch_a')
    expect(bank.isExpanded('batch_a')).toBe(false)

    await bank.toggleExpand('batch_a')
    expect(questionListCalls()).toHaveLength(1)
    expect(bank.isExpanded('batch_a')).toBe(true)
  })

  it('未分批分组用 unbatched 参数拉题，不被当成「不过滤」', async () => {
    const bank = useQuestionBank()
    await bank.loadBatches()

    await bank.toggleExpand(null)

    const call = questionListCalls()[0][0]
    expect(call.url).toContain('unbatched=true')
    expect(call.url).not.toContain('batch_id=')
    expect(bank.questionsFor(null).map((item) => item.id)).toEqual(['q-hist'])
  })

  it('整批选中按可用题数计数，取消一题后变半选，勾选状态跨收起保持', async () => {
    const bank = useQuestionBank()
    await bank.loadBatches()

    bank.toggleBatch('batch_a')

    expect(bank.checkState('batch_a')).toBe('all')
    expect(bank.selectedCount.value).toBe(2)

    await bank.toggleExpand('batch_a')
    bank.toggleQuestion('batch_a', 'q-1')

    expect(bank.checkState('batch_a')).toBe('partial')
    expect(bank.selectedCount.value).toBe(1)

    await bank.toggleExpand('batch_a')
    await bank.toggleExpand('batch_a')

    expect(bank.checkState('batch_a')).toBe('partial')
    expect(bank.selectedCount.value).toBe(1)
    expect(bank.selectedIdsFor('batch_a')).toEqual(['q-2'])
  })

  it('待审核题目可见但不可勾选，因而不计入已选题数', async () => {
    const bank = useQuestionBank()
    await bank.loadBatches()
    await bank.toggleExpand('batch_a')

    bank.toggleQuestion('batch_a', 'q-3')

    expect(bank.checkState('batch_a')).toBe('none')
    expect(bank.selectedCount.value).toBe(0)
    expect(bank.questionsFor('batch_a')).toHaveLength(3)
    expect(bank.questionsFor('batch_a')[2].selectable).toBe(false)
  })

  it('开练解析整批题目 ID，题数与显示一致时不再打扰用户', async () => {
    const showModal = vi.spyOn(uni as any, 'showModal')
    const bank = useQuestionBank()
    await bank.loadBatches()
    bank.toggleBatch('batch_a')

    const session = await bank.startPractice()

    expect(session?.id).toBe('p-1')
    const createCall = requestMock.mock.calls.find(([options]: any[]) => options.url === '/practices')
    expect(createCall?.[0].data.question_ids).toEqual(['q-1', 'q-2'])
    expect(createCall?.[0].data.title).toBe('题库练习 · 2 题')
    expect(showModal).not.toHaveBeenCalled()
    showModal.mockRestore()
  })

  it('开练显式传 question_count：后端默认 10 题会静默截断，12 题必须整批进练习', async () => {
    // 回归：后端显式题目路径是 ordered_explicit[: question_count]，默认 10。
    // 不传 question_count 时用户选 12 题只会进 10 题，且没有任何错误信号。
    const twelve = Array.from({ length: 12 }, (_, index) => ({
      id: `q-big-${index}`,
      question_type: 'single_choice',
      stem: `题干 ${index}`,
      batch_id: 'batch_a',
      status: 'available',
    }))
    batchListForTest = {
      items: [
        {
          batch_id: 'batch_a',
          question_count: 12,
          available_count: 12,
          pending_review_count: 0,
          created_at: '2026-03-01T08:00:00',
          sources: [],
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    }
    availableForBatchA = { items: twelve, total: 12 }
    const bank = useQuestionBank()
    await bank.loadBatches()
    bank.toggleBatch('batch_a')

    expect(bank.selectedCount.value).toBe(12)

    await bank.startPractice()

    const createCall = requestMock.mock.calls.find(([options]: any[]) => options.url === '/practices')
    expect(createCall?.[0].data.question_ids).toHaveLength(12)
    expect(createCall?.[0].data.question_count).toBe(12)
    expect(createCall?.[0].data.title).toBe('题库练习 · 12 题')
  })

  it('超过单次 50 题上限时先告知再按 50 题创建，不静默砍题', async () => {
    const over = Array.from({ length: 51 }, (_, index) => ({
      id: `q-huge-${index}`,
      question_type: 'single_choice',
      stem: `题干 ${index}`,
      batch_id: 'batch_a',
      status: 'available',
    }))
    batchListForTest = {
      items: [
        {
          batch_id: 'batch_a',
          question_count: 51,
          available_count: 51,
          pending_review_count: 0,
          created_at: '2026-03-01T08:00:00',
          sources: [],
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    }
    availableForBatchA = { items: over, total: 51 }
    const showModal = vi.spyOn(uni as any, 'showModal')
    const bank = useQuestionBank()
    await bank.loadBatches()
    bank.toggleBatch('batch_a')

    expect(bank.selectedCount.value).toBe(51)

    const session = await bank.startPractice()

    expect(showModal).toHaveBeenCalledTimes(1)
    expect(showModal.mock.calls[0][0].content).toContain('最多 50 题')
    const createCall = requestMock.mock.calls.find(([options]: any[]) => options.url === '/practices')
    expect(createCall?.[0].data.question_count).toBe(50)
    expect(createCall?.[0].data.question_ids).toHaveLength(50)
    expect(session?.id).toBe('p-1')
    showModal.mockRestore()
  })

  it('连点「立即开练」只创建一条练习', async () => {
    const bank = useQuestionBank()
    await bank.loadBatches()
    bank.toggleBatch('batch_a')

    const [first, second] = await Promise.all([bank.startPractice(), bank.startPractice()])

    expect(requestMock.mock.calls.filter(([options]: any[]) => options.url === '/practices')).toHaveLength(1)
    expect([first, second].filter(Boolean)).toHaveLength(1)
  })

  it('解析出的题目变少时必须告知并让用户确认，取消则不创建练习', async () => {
    availableForBatchA = { items: [batchAQuestions.items[0]], total: 1 }
    const showModal = vi
      .spyOn(uni as any, 'showModal')
      .mockImplementation(({ success }: any) => success && success({ confirm: false }))
    const bank = useQuestionBank()
    await bank.loadBatches()
    bank.toggleBatch('batch_a')

    const session = await bank.startPractice()

    expect(session).toBeNull()
    expect(showModal).toHaveBeenCalledTimes(1)
    expect(requestMock.mock.calls.some(([options]: any[]) => options.url === '/practices')).toBe(
      false,
    )
    showModal.mockRestore()
  })

  it('用户确认少题后再创建，题数为实际可练数', async () => {
    availableForBatchA = { items: [batchAQuestions.items[0]], total: 1 }
    const bank = useQuestionBank()
    await bank.loadBatches()
    bank.toggleBatch('batch_a')

    const session = await bank.startPractice()

    expect(session?.id).toBe('p-1')
    const createCall = requestMock.mock.calls.find(([options]: any[]) => options.url === '/practices')
    expect(createCall?.[0].data.question_ids).toEqual(['q-1'])
  })

  it('逐题勾选也要回查可用集合：题目失效时同样先告知再创建', async () => {
    const showModal = vi.spyOn(uni as any, 'showModal')
    const bank = useQuestionBank()
    await bank.loadBatches()
    await bank.toggleExpand('batch_a')
    bank.toggleQuestion('batch_a', 'q-1')
    bank.toggleQuestion('batch_a', 'q-2')
    availableForBatchA = { items: [batchAQuestions.items[0]], total: 1 }

    const session = await bank.startPractice()

    expect(showModal).toHaveBeenCalledTimes(1)
    const createCall = requestMock.mock.calls.find(([options]: any[]) => options.url === '/practices')
    expect(session?.id).toBe('p-1')
    expect(createCall?.[0].data.question_ids).toEqual(['q-1'])
    showModal.mockRestore()
  })

  it('跨批次开练合成一次练习，标题可辨认', async () => {
    const bank = useQuestionBank()
    await bank.loadBatches()
    bank.toggleBatch('batch_a')
    bank.toggleBatch(null)

    const createCall = () =>
      requestMock.mock.calls.filter(([options]: any[]) => options.url === '/practices')

    await bank.startPractice()

    expect(createCall()).toHaveLength(1)
    expect(createCall()[0][0].data.question_ids).toEqual(['q-1', 'q-2', 'q-hist'])
    expect(createCall()[0][0].data.title).toBe('跨批次练习 · 2 个批次 3 题')
  })

  it('末页取回空页时收掉「加载更多」，不留一个点了没反应的按钮', async () => {
    // 回归：total 与列表是两条独立查询，服务端批次减少时 total 会大于实际可达行数，
    // 「加载更多」会一直可见却每次都取回空页。
    batchListForTest = { ...questionBatchListFixture, total: 5 }
    batchPageOverridesForTest = { 2: { items: [], total: 5, limit: 20, offset: 20 } }
    const bank = useQuestionBank()
    await bank.loadBatches()

    expect(bank.hasMore.value).toBe(true)

    await bank.loadMoreBatches()

    expect(bank.hasMore.value).toBe(false)
  })

  it('加载失败给出可读错误与重试动作', async () => {
    requestMock.mockImplementation(async () => {
      throw new Error('network down')
    })
    const bank = useQuestionBank()

    await bank.loadBatches()

    expect(bank.loadError.value).toBeTruthy()
    expect(bank.batches.value).toEqual([])

    mockRequests()
    await bank.loadBatches()

    expect(bank.loadError.value).toBe('')
    expect(bank.batches.value).toHaveLength(2)
  })

  it('题数为零时开练被拦下，不发创建请求', async () => {
    const bank = useQuestionBank()
    await bank.loadBatches()

    expect(await bank.startPractice()).toBeNull()
    expect(requestMock.mock.calls.some(([options]: any[]) => options.url === '/practices')).toBe(
      false,
    )
  })
})
