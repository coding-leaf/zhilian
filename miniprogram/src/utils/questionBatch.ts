/**
 * 题库批次的标签推导与三态选择模型（纯函数，无副作用、无网络）。
 *
 * 两条硬约束决定了这里的数据结构：
 * 1. 未展开的批次**不得**预取题目列表（否则请求数随题目总量增长）。因此选择状态
 *    只存「意图」——整批选中、逐题勾选、逐题取消——而不存题目 ID 集合：
 *    三态与已选题数都能只靠批次摘要里的计数算出来。
 * 2. `batch_id` 可以为 `null`（历史题目未分批），且必须能被看见。所以所有以
 *    批次标识为键的 Set/Map 一律使用 `string | null`，绝不用哨兵值替换。
 *
 * 不变量（由本模块的 toggle 函数维持）：
 * - 批次在 `whole` 中时，`picked` 不持有该批次，只有 `unpicked` 可能非空；
 * - 批次不在 `whole` 中时，`unpicked` 不持有该批次，只有 `picked` 可能非空。
 * 两条互斥保证「已选题数」不会被重复计入。
 *
 * 事实源：`.trellis/tasks/09-29-question-bank-page/design.md` 决策 3 / 决策 4 / 决策 6。
 */

import type { BatchSource, QuestionBankItem, QuestionBatchSummary } from '@/types'

/** 批次标识；`null` 表示未分批的历史题目。 */
export type BatchKey = string | null

export interface BatchSelectionState {
  /** 整批选中的批次（展开后未单独取消的题目都算入） */
  whole: Set<BatchKey>
  /** 逐题勾选，按批次分桶 */
  picked: Map<BatchKey, Set<string>>
  /** 在整批选中之上逐题取消，按批次分桶 */
  unpicked: Map<BatchKey, Set<string>>
}

export type BatchCheckState = 'all' | 'partial' | 'none'

export function createBatchSelection(): BatchSelectionState {
  return { whole: new Set(), picked: new Map(), unpicked: new Map() }
}

/** 三态判定：只依赖计数与选择意图，不需要该批次的题目 ID 列表。 */
export function resolveBatchCheckState(
  batchId: BatchKey,
  selection: BatchSelectionState,
): BatchCheckState {
  if (selection.whole.has(batchId)) {
    const unpickedCount = selection.unpicked.get(batchId)?.size ?? 0
    return unpickedCount === 0 ? 'all' : 'partial'
  }
  const pickedCount = selection.picked.get(batchId)?.size ?? 0
  return pickedCount === 0 ? 'none' : 'partial'
}

/** 单个批次贡献的已选题数（整批按 `availableCount` 减取消数；逐题按实际勾中数）。 */
function countSelectedInBatch(
  batch: QuestionBatchSummary,
  selection: BatchSelectionState,
): number {
  if (selection.whole.has(batch.batchId)) {
    const unpickedCount = selection.unpicked.get(batch.batchId)?.size ?? 0
    return Math.max(0, batch.availableCount - unpickedCount)
  }
  return selection.picked.get(batch.batchId)?.size ?? 0
}

/**
 * 已选题数。
 *
 * 与「实际进入练习的题数」恒等：可选题目只有 `available`（待审核题目可见但不可选），
 * 所以整批选中按 `availableCount` 计数，逐题勾选按实际勾中的题数计数。
 */
export function countSelectedQuestions(
  batches: QuestionBatchSummary[],
  selection: BatchSelectionState,
): number {
  return batches.reduce((total, batch) => total + countSelectedInBatch(batch, selection), 0)
}

/**
 * 涉及选择**且至少贡献 1 题**的批次数（用于构造「跨批次练习」标题）。
 *
 * 不含只贡献 0 题的批次：全勾一个整批待审核的批次同样只贡献 0 题——
 * 它不该出现在标题里，否则「练习标题」宣称的批次数与实际进练习的题目对不上。
 */
export function countSelectedBatches(
  batches: QuestionBatchSummary[],
  selection: BatchSelectionState,
): number {
  return batches.filter((batch) => countSelectedInBatch(batch, selection) > 0).length
}

/** 批次级勾选：未选/半选 → 全选，全选 → 取消。整批意图覆盖逐题记录。 */
export function toggleBatchSelection(
  selection: BatchSelectionState,
  batchId: BatchKey,
): BatchSelectionState {
  const whole = new Set(selection.whole)
  const picked = new Map(selection.picked)
  const unpicked = new Map(selection.unpicked)
  if (resolveBatchCheckState(batchId, selection) === 'all') {
    whole.delete(batchId)
  } else {
    whole.add(batchId)
  }
  picked.delete(batchId)
  unpicked.delete(batchId)
  return { whole, picked, unpicked }
}

/** 单题勾选：整批选中时记入 `unpicked` 取消集，否则记入 `picked` 勾选集。 */
export function toggleQuestionSelection(
  selection: BatchSelectionState,
  batchId: BatchKey,
  questionId: string,
): BatchSelectionState {
  const whole = new Set(selection.whole)
  const picked = new Map(selection.picked)
  const unpicked = new Map(selection.unpicked)

  if (whole.has(batchId)) {
    const batchUnpicked = new Set(unpicked.get(batchId) ?? [])
    if (batchUnpicked.has(questionId)) batchUnpicked.delete(questionId)
    else batchUnpicked.add(questionId)
    if (batchUnpicked.size > 0) unpicked.set(batchId, batchUnpicked)
    else unpicked.delete(batchId)
    return { whole, picked, unpicked }
  }

  const batchPicked = new Set(picked.get(batchId) ?? [])
  if (batchPicked.has(questionId)) batchPicked.delete(questionId)
  else batchPicked.add(questionId)
  if (batchPicked.size > 0) picked.set(batchId, batchPicked)
  else picked.delete(batchId)
  return { whole, picked, unpicked }
}

/**
 * 解析整批选中时真正要练的题目 ID。
 *
 * 只认 `selectable`（即 available）的题目——待审核题目进入练习会被后端静默丢弃，
 * 界面上的题数会与练习里的题数对不上，而没有任何错误信号可供归因。
 */
export function resolveWholeBatchQuestionIds(
  questions: QuestionBankItem[],
  unpickedIds: Set<string>,
): string[] {
  return questions
    .filter((question) => question.selectable && !unpickedIds.has(question.id))
    .map((question) => question.id)
}

/**
 * 某个批次内已勾选的题目 ID。
 *
 * 整批选中时按已加载的题目展开（只认可选题目）；未展开的批次返回空数组——
 * 用户还没看到题目时谈不上逐题勾选，题数由 `availableCount` 承担。
 */
export function selectedQuestionIds(
  batchId: BatchKey,
  questions: QuestionBankItem[],
  selection: BatchSelectionState,
): string[] {
  if (resolveBatchCheckState(batchId, selection) === 'none') return []
  const unpicked = selection.unpicked.get(batchId) ?? new Set<string>()
  if (selection.whole.has(batchId)) {
    return questions
      .filter((question) => question.selectable && !unpicked.has(question.id))
      .map((question) => question.id)
  }
  return Array.from(selection.picked.get(batchId) ?? [])
}

/** 跨批次练习标题：必须是可辨认文本，「我的练习」与诊断报告里只靠它识别。 */
export function buildPracticeTitle(batchCount: number, questionCount: number): string {
  return batchCount > 1
    ? `跨批次练习 · ${batchCount} 个批次 ${questionCount} 题`
    : `题库练习 · ${questionCount} 题`
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** 批次时间：`M月D日 HH:mm`，跨年补年份。 */
export function formatBatchTime(iso: string, now: Date = new Date()): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '时间未知'
  const month = date.getMonth() + 1
  const day = date.getDate()
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  if (date.getFullYear() !== now.getFullYear()) {
    return `${date.getFullYear()}年${month}月${day}日 ${clock}`
  }
  return `${month}月${day}日 ${clock}`
}

/**
 * 批次来源可读标签。
 *
 * 一个批次可以横跨多份资料（课程范围出题只分配一个 batch_id），所以：
 * 单资料 → 资料名；多资料同课程 → 课程名；多资料跨课程 → 「N 份资料」；
 * 来源行已缺失或没有任何来源 → 「来源已删除」。
 */
export function describeBatchSource(sources: BatchSource[]): string {
  const materialIds = Array.from(new Set(sources.map((source) => source.materialId)))
  if (materialIds.length === 0) return '来源已删除'
  if (materialIds.length === 1) {
    const title = sources.find((source) => source.materialId === materialIds[0])?.materialTitle
    return title || '来源已删除'
  }
  const folderIds = Array.from(new Set(sources.map((source) => source.folderId)))
  const [singleFolder] = folderIds
  if (folderIds.length === 1 && singleFolder) {
    const folderName = sources.find((source) => source.folderId === singleFolder)?.folderName
    if (folderName) return folderName
  }
  return `${materialIds.length} 份资料`
}

/**
 * 批次可读标签；题库区块与核对出题页共用，禁止第二份实现。
 *
 * 界面上不出现 `batch_3f9a...` 这类原始 ID：它没有时间戳、没有来源、没有序号。
 */
export function describeBatchLabel(
  batch: QuestionBatchSummary,
  now: Date = new Date(),
): string {
  const countText =
    batch.pendingReviewCount > 0
      ? `${batch.availableCount} 题 · ${batch.pendingReviewCount} 题待审核`
      : `${batch.availableCount} 题`
  if (batch.batchId === null) {
    return `未分批题目 · ${countText}`
  }
  return `${formatBatchTime(batch.createdAt, now)} · ${describeBatchSource(batch.sources)} · ${countText}`
}
