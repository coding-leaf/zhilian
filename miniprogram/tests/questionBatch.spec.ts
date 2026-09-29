import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { BatchSource, QuestionBankItem, QuestionBatchSummary } from '@/types'
import {
  buildPracticeTitle,
  countSelectedBatches,
  countSelectedQuestions,
  createBatchSelection,
  describeBatchLabel,
  describeBatchSource,
  formatBatchTime,
  resolveBatchCheckState,
  resolveWholeBatchQuestionIds,
  selectedQuestionIds,
  toggleBatchSelection,
  toggleQuestionSelection,
} from '@/utils/questionBatch'

/** 测试用「现在」：与用例中的批次时间同一年，避免跨年分支干扰。 */
const NOW = new Date('2026-06-01T00:00:00')

function makeSource(overrides: Partial<BatchSource> = {}): BatchSource {
  return {
    materialId: 'm-1',
    materialTitle: '软件工程导论.pdf',
    folderId: null,
    folderName: null,
    ...overrides,
  }
}

function makeBatch(overrides: Partial<QuestionBatchSummary> = {}): QuestionBatchSummary {
  return {
    batchId: 'batch_a',
    questionCount: 3,
    availableCount: 2,
    pendingReviewCount: 1,
    // 不带时区偏移，避免用例结果随运行机器的时区漂移
    createdAt: '2026-03-01T08:00:00',
    sources: [makeSource()],
    ...overrides,
  }
}

function makeItem(id: string, selectable = true): QuestionBankItem {
  return { id, stem: '题干', type: 'single_choice', selectable, batchId: 'batch_a' }
}

describe('批次三态选择', () => {
  it('未选 → 全选 → 取消一题变半选 → 恢复 → 再点取消全选', () => {
    let selection = createBatchSelection()
    expect(resolveBatchCheckState('batch_a', selection)).toBe('none')

    selection = toggleBatchSelection(selection, 'batch_a')
    expect(resolveBatchCheckState('batch_a', selection)).toBe('all')

    selection = toggleQuestionSelection(selection, 'batch_a', 'q-1')
    expect(resolveBatchCheckState('batch_a', selection)).toBe('partial')

    selection = toggleQuestionSelection(selection, 'batch_a', 'q-1')
    expect(resolveBatchCheckState('batch_a', selection)).toBe('all')

    selection = toggleBatchSelection(selection, 'batch_a')
    expect(resolveBatchCheckState('batch_a', selection)).toBe('none')
  })

  it('半选状态下点批次行直接变成全选，并清掉逐题记录', () => {
    let selection = createBatchSelection()
    selection = toggleQuestionSelection(selection, 'batch_a', 'q-1')
    expect(resolveBatchCheckState('batch_a', selection)).toBe('partial')

    selection = toggleBatchSelection(selection, 'batch_a')

    expect(resolveBatchCheckState('batch_a', selection)).toBe('all')
    expect(selection.unpicked.get('batch_a')).toBeUndefined()
  })

  it('batch_id 为 null（未分批的历史题目）能参与三态判定与计数', () => {
    const batches = [
      makeBatch({ batchId: null, questionCount: 2, availableCount: 2, pendingReviewCount: 0 }),
    ]
    let selection = createBatchSelection()
    expect(resolveBatchCheckState(null, selection)).toBe('none')
    expect(countSelectedQuestions(batches, selection)).toBe(0)

    selection = toggleBatchSelection(selection, null)
    expect(resolveBatchCheckState(null, selection)).toBe('all')
    expect(countSelectedQuestions(batches, selection)).toBe(2)

    selection = toggleQuestionSelection(selection, null, 'q-1')
    expect(resolveBatchCheckState(null, selection)).toBe('partial')
    expect(countSelectedQuestions(batches, selection)).toBe(1)
  })

  it('三个批次各自独立：批次数只统计被涉及的那些', () => {
    const batches = [
      makeBatch({ batchId: 'batch_a' }),
      makeBatch({ batchId: 'batch_b' }),
      makeBatch({ batchId: null, availableCount: 1, questionCount: 1, pendingReviewCount: 0 }),
    ]
    let selection = createBatchSelection()
    selection = toggleBatchSelection(selection, 'batch_a')
    selection = toggleQuestionSelection(selection, null, 'q-9')

    expect(countSelectedBatches(batches, selection)).toBe(2)
    expect(resolveBatchCheckState('batch_b', selection)).toBe('none')
  })
})

describe('已选题数', () => {
  it('整批选中按 availableCount 减取消数，逐题勾选按实际勾中数，且与实际会练的题数恒等', () => {
    const batches = [
      makeBatch({ batchId: 'batch_a', questionCount: 5, availableCount: 3, pendingReviewCount: 2 }),
      makeBatch({ batchId: 'batch_b', questionCount: 2, availableCount: 2, pendingReviewCount: 0 }),
    ]
    let selection = createBatchSelection()
    selection = toggleBatchSelection(selection, 'batch_a')
    selection = toggleQuestionSelection(selection, 'batch_a', 'q-2')
    selection = toggleQuestionSelection(selection, 'batch_b', 'q-9')

    expect(countSelectedQuestions(batches, selection)).toBe(3)

    // 与「实际进入练习的题数」对齐：整批按可用题目解析后再去掉取消项
    const resolvedWhole = resolveWholeBatchQuestionIds(
      ['q-1', 'q-2', 'q-3', 'q-pending'].map((id) =>
        makeItem(id, id !== 'q-pending'),
      ),
      selection.unpicked.get('batch_a') ?? new Set(),
    )
    const resolvedPicked = Array.from(selection.picked.get('batch_b') ?? [])
    expect(resolvedWhole.length + resolvedPicked.length).toBe(
      countSelectedQuestions(batches, selection),
    )
  })

  it('待审核题目不计入：只勾待审核的批次计数为 0', () => {
    const batches = [
      makeBatch({ batchId: 'batch_a', questionCount: 2, availableCount: 0, pendingReviewCount: 2 }),
    ]
    let selection = createBatchSelection()
    selection = toggleBatchSelection(selection, 'batch_a')

    expect(resolveBatchCheckState('batch_a', selection)).toBe('all')
    expect(countSelectedQuestions(batches, selection)).toBe(0)
    expect(
      resolveWholeBatchQuestionIds([makeItem('q-1', false)], new Set()),
    ).toEqual([])
  })

  it('只贡献 0 题的批次不计入标题里的批次数（整批待审核也一样）', () => {
    const batches = [
      makeBatch({ batchId: 'batch_pending', questionCount: 2, availableCount: 0, pendingReviewCount: 2 }),
      makeBatch({ batchId: 'batch_ok', questionCount: 2, availableCount: 2, pendingReviewCount: 0 }),
    ]
    let selection = createBatchSelection()
    selection = toggleBatchSelection(selection, 'batch_pending')
    selection = toggleBatchSelection(selection, 'batch_ok')

    expect(countSelectedQuestions(batches, selection)).toBe(2)
    expect(countSelectedBatches(batches, selection)).toBe(1)
    // 标题宣称的批次数与实际进练习的题目一致，不出现「2 个批次」而只练 1 个批次
    expect(buildPracticeTitle(countSelectedBatches(batches, selection), 2)).toBe('题库练习 · 2 题')
  })

  it('整批取消数超过可用数时按 0 兜底，不出现负数', () => {
    const batches = [makeBatch({ batchId: 'batch_a', availableCount: 1, questionCount: 1, pendingReviewCount: 0 })]
    let selection = createBatchSelection()
    selection = toggleBatchSelection(selection, 'batch_a')
    selection = toggleQuestionSelection(selection, 'batch_a', 'q-1')
    selection = toggleQuestionSelection(selection, 'batch_a', 'q-2')

    expect(countSelectedQuestions(batches, selection)).toBe(0)
  })
})

describe('批次标签推导', () => {
  it('单资料批次用资料名', () => {
    const label = describeBatchLabel(makeBatch(), NOW)

    expect(label).toBe('3月1日 08:00 · 软件工程导论.pdf · 2 题 · 1 题待审核')
  })

  it('多资料同课程批次用课程名，而不是其中某一份资料', () => {
    const label = describeBatchLabel(
      makeBatch({
        pendingReviewCount: 0,
        sources: [
          makeSource({ materialId: 'm-1', materialTitle: '讲义一.pdf', folderId: 'f-1', folderName: '软件工程' }),
          makeSource({ materialId: 'm-2', materialTitle: '讲义二.pdf', folderId: 'f-1', folderName: '软件工程' }),
        ],
      }),
      NOW,
    )

    expect(label).toBe('3月1日 08:00 · 软件工程 · 2 题')
  })

  it('多资料跨课程批次用「N 份资料」', () => {
    const label = describeBatchLabel(
      makeBatch({
        pendingReviewCount: 0,
        sources: [
          makeSource({ materialId: 'm-1', materialTitle: '讲义一.pdf', folderId: 'f-1', folderName: '软件工程' }),
          makeSource({ materialId: 'm-2', materialTitle: '讲义二.pdf', folderId: 'f-2', folderName: '数据结构' }),
        ],
      }),
      NOW,
    )

    expect(label).toBe('3月1日 08:00 · 2 份资料 · 2 题')
  })

  it('多资料都未归课程时也用「N 份资料」，不伪造课程名', () => {
    expect(
      describeBatchSource([
        makeSource({ materialId: 'm-1', materialTitle: '讲义一.pdf' }),
        makeSource({ materialId: 'm-2', materialTitle: '讲义二.pdf' }),
      ]),
    ).toBe('2 份资料')
  })

  it('来源已删除：没有来源行，或资料标题为空', () => {
    expect(describeBatchSource([])).toBe('来源已删除')
    expect(describeBatchSource([makeSource({ materialTitle: null })])).toBe('来源已删除')
    expect(describeBatchLabel(makeBatch({ sources: [], pendingReviewCount: 0 }), NOW)).toBe(
      '3月1日 08:00 · 来源已删除 · 2 题',
    )
  })

  it('未分批的历史题目不伪造时间与来源', () => {
    const label = describeBatchLabel(
      makeBatch({ batchId: null, availableCount: 4, pendingReviewCount: 0, sources: [] }),
      NOW,
    )

    expect(label).toBe('未分批题目 · 4 题')
  })

  it('跨年批次补年份，非法时间给可读降级', () => {
    expect(formatBatchTime('2025-12-03T09:05:00', NOW)).toBe('2025年12月3日 09:05')
    expect(formatBatchTime('', NOW)).toBe('时间未知')
  })

  it('标签里绝不出现原始 batch_id', () => {
    const label = describeBatchLabel(makeBatch({ batchId: 'batch_3f9a1c2b4d5e' }), NOW)

    expect(label).not.toContain('batch_')
  })
})

describe('整批题目的解析与练习标题', () => {
  it('整批解析只取可选题目，并排除逐题取消的题目', () => {
    const questions = [
      makeItem('q-1'),
      makeItem('q-pending', false),
      { ...makeItem('q-2'), batchId: null },
    ]

    expect(resolveWholeBatchQuestionIds(questions, new Set())).toEqual(['q-1', 'q-2'])
    expect(resolveWholeBatchQuestionIds(questions, new Set(['q-2']))).toEqual(['q-1'])
  })

  it('已勾选题目 ID：未展开的整批返回空数组（展开后才知道有哪些题）', () => {
    let selection = createBatchSelection()
    selection = toggleBatchSelection(selection, 'batch_a')

    expect(selectedQuestionIds('batch_a', [], selection)).toEqual([])
    expect(selectedQuestionIds('batch_a', [makeItem('q-1'), makeItem('q-2')], selection)).toEqual([
      'q-1',
      'q-2',
    ])
  })

  it('练习标题可辨认且不含 UUID 式字符串', () => {
    expect(buildPracticeTitle(1, 5)).toBe('题库练习 · 5 题')
    const title = buildPracticeTitle(3, 24)

    expect(title).toBe('跨批次练习 · 3 个批次 24 题')
    expect(title).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/)
  })
})

/**
 * AC-11 的结构守卫：两处显示批次的地方必须 import 同一个 `describeBatchLabel`。
 * 复制一份实现不会报错，只会让「核对页说的批次」和「题库页说的批次」悄悄分叉。
 */
describe('批次标签只有一份实现', () => {
  // vitest 的工作目录即 miniprogram/，直接按仓库相对路径读取源码
  const consumers = [
    'src/pages/review/components/QuestionBatchRow.vue',
    'src/subpackages/material/composables/useQuestionCompose.ts',
  ]

  it.each(consumers)('%s 复用 @/utils/questionBatch 的标签函数', (relativePath) => {
    const source = readFileSync(resolve(process.cwd(), relativePath), 'utf8')

    expect(source).toContain('describeBatchLabel')
    expect(source).toMatch(/import[^;]*describeBatchLabel[^;]*from '@\/utils\/questionBatch'/)
    expect(source).not.toMatch(/function\s+describeBatchLabel/)
  })

  it('标签函数只在 utils/questionBatch.ts 里定义一次', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/utils/questionBatch.ts'), 'utf8')

    expect(source.match(/export function describeBatchLabel/g)).toHaveLength(1)
  })
})
