/**
 * 题库区块的页面本地状态与编排。
 *
 * 刻意不进 Pinia store：批次列表、分页游标、展开集合与勾选集合只在题库区块内有意义，
 * 没有任何第二个页面读它（`spec/frontend/state-management.md` 的「提升到全局 store」判据）。
 *
 * 两条硬约束体现在实现里：
 * - **未展开的批次不预取题目**：渲染路径只读批次摘要，题目列表仅在展开时按需拉取，
 *   整批选中的题目 ID 只在「立即开练」内解析。
 * - **可选题目只有 available**：待审核题目可见（带徽标）但不可勾选，因此「已选 N 题」
 *   与进入练习的题数结构上恒等，不依赖额外校验。
 */

import { computed, ref } from 'vue'
import { apiCreatePractice, apiListQuestionBankItems, apiListQuestionBatches } from '@/api'
import type { PracticeSession, QuestionBankItem, QuestionBatchSummary } from '@/types'
import { RequestError } from '@/utils/requestError'
import {
  buildPracticeTitle,
  countSelectedBatches,
  countSelectedQuestions,
  createBatchSelection,
  resolveBatchCheckState,
  resolveWholeBatchQuestionIds,
  selectedQuestionIds,
  toggleBatchSelection,
  toggleQuestionSelection,
  type BatchCheckState,
  type BatchKey,
  type BatchSelectionState,
} from '@/utils/questionBatch'

const BATCH_PAGE_SIZE = 20
const QUESTION_PAGE_SIZE = 50
/** 单次展开/解析最多翻页数，防止异常 total 导致无限翻页。 */
const MAX_QUESTION_PAGES = 20
/**
 * 单次练习题数上限。
 *
 * 后端 `PracticeCreateRequest.question_count` 为 `ge=1, le=50`，且显式题目路径
 * （`app/services/practice.py` 的 `ordered_explicit[: options.question_count]`）**会**按
 * `question_count` 截断——它的语义是「候选题目 + 目标题数」，不是「就练这些」。
 * 所以开练必须显式传 `question_count`，否则后端默认 10 题，用户选 12 题只会进 10 题，
 * 且没有任何错误信号。
 */
const MAX_PRACTICE_QUESTIONS = 50
const SESSION_PAGE_URL = '/subpackages/practice/pages/session/index'

/** 从失败对象取出可直接展示的短文案。 */
function describeFailure(error: unknown, fallback: string): string {
  if (error instanceof RequestError) return error.userMessage
  return fallback
}

export function useQuestionBank() {
  const batches = ref<QuestionBatchSummary[]>([])
  const batchTotal = ref(0)
  const isLoading = ref(false)
  const isLoadingMore = ref(false)
  const loadError = ref('')
  /**
   * 已翻到末页。
   *
   * `total` 与列表是两条独立查询（无事务快照），服务端批次增减时 total 可能大于
   * 实际可达行数；那时「加载更多」会一直可见却每次都取回空页——「点了没反应」。
   * 取回空页即判定到底，把按钮收掉。
   */
  const reachedEnd = ref(false)
  /**
   * 已加载到第几页。
   *
   * 刻意不按 `batches.length / page_size` 反推页码：那一推导假定每页都是满页，
   * 一旦服务端返回「非空但不满」的一页（total 与实际行数不一致时就会发生），
   * 页码永远不前进，用户每次点「加载更多」都取回同一页，界面毫无变化。
   */
  const loadedPages = ref(0)

  const expanded = ref<BatchKey[]>([])
  const questionsByBatch = ref<Map<BatchKey, QuestionBankItem[]>>(new Map())
  const loadingQuestions = ref<BatchKey[]>([])
  const questionErrors = ref<Map<BatchKey, string>>(new Map())

  const selection = ref<BatchSelectionState>(createBatchSelection())
  const isStarting = ref(false)

  const selectedCount = computed(() => countSelectedQuestions(batches.value, selection.value))
  const selectedBatchCount = computed(() => countSelectedBatches(batches.value, selection.value))
  const hasMore = computed(() => !reachedEnd.value && batches.value.length < batchTotal.value)

  const isExpanded = (batchId: BatchKey): boolean => expanded.value.includes(batchId)
  const questionsFor = (batchId: BatchKey): QuestionBankItem[] =>
    questionsByBatch.value.get(batchId) ?? []
  const isLoadingQuestions = (batchId: BatchKey): boolean =>
    loadingQuestions.value.includes(batchId)
  const questionError = (batchId: BatchKey): string => questionErrors.value.get(batchId) ?? ''
  const checkState = (batchId: BatchKey): BatchCheckState =>
    resolveBatchCheckState(batchId, selection.value)
  const selectedIdsFor = (batchId: BatchKey): string[] =>
    selectedQuestionIds(batchId, questionsFor(batchId), selection.value)

  const setQuestionError = (batchId: BatchKey, message: string) => {
    const next = new Map(questionErrors.value)
    if (message) next.set(batchId, message)
    else next.delete(batchId)
    questionErrors.value = next
  }

  const appendBatches = (items: QuestionBatchSummary[], total: number) => {
    const seen = new Set(batches.value.map((batch) => batch.batchId))
    batches.value = [...batches.value, ...items.filter((batch) => !seen.has(batch.batchId))]
    batchTotal.value = total
  }

  const loadBatches = async () => {
    isLoading.value = true
    loadError.value = ''
    try {
      const result = await apiListQuestionBatches({ page: 1, page_size: BATCH_PAGE_SIZE })
      batches.value = result.items
      batchTotal.value = result.total
      loadedPages.value = 1
      reachedEnd.value = result.items.length === 0
    } catch (error) {
      console.error('Failed to load question batches', error)
      loadError.value = describeFailure(error, '题目批次加载失败，请重试')
    } finally {
      isLoading.value = false
    }
  }

  const loadMoreBatches = async () => {
    if (isLoadingMore.value || !hasMore.value) return
    isLoadingMore.value = true
    loadError.value = ''
    try {
      const page = loadedPages.value + 1
      const result = await apiListQuestionBatches({ page, page_size: BATCH_PAGE_SIZE })
      appendBatches(result.items, result.total)
      loadedPages.value = page
      if (result.items.length === 0) reachedEnd.value = true
    } catch (error) {
      console.error('Failed to load more question batches', error)
      loadError.value = describeFailure(error, '更多批次加载失败，请重试')
    } finally {
      isLoadingMore.value = false
    }
  }

  /**
   * 按批次的题目列表查询；`batch_id IS NULL` 的未分批分组走 `unbatched` 参数，
   * 因为后端的 `batch_id` 过滤无法表达 `IS NULL`。
   */
  const fetchBatchQuestions = async (
    batchId: BatchKey,
    reviewStatus?: 'available',
  ): Promise<QuestionBankItem[]> => {
    const collected: QuestionBankItem[] = []
    let total = 0
    for (let page = 1; page <= MAX_QUESTION_PAGES; page += 1) {
      const result = await apiListQuestionBankItems({
        batchId,
        unbatched: batchId === null,
        reviewStatus,
        page,
        page_size: QUESTION_PAGE_SIZE,
      })
      const items = result.items || []
      collected.push(...items)
      total = result.total ?? collected.length
      if (items.length === 0 || collected.length >= total) break
    }
    return collected
  }

  const loadBatchQuestions = async (batchId: BatchKey) => {
    loadingQuestions.value = [...loadingQuestions.value, batchId]
    setQuestionError(batchId, '')
    try {
      const items = await fetchBatchQuestions(batchId)
      questionsByBatch.value = new Map(questionsByBatch.value).set(batchId, items)
    } catch (error) {
      console.error('Failed to load batch questions', error)
      setQuestionError(batchId, describeFailure(error, '题目加载失败，请重试'))
    } finally {
      loadingQuestions.value = loadingQuestions.value.filter((key) => key !== batchId)
    }
  }

  /** 展开批次：首次展开才拉取题目，收起不丢已加载结果与勾选状态。 */
  const toggleExpand = async (batchId: BatchKey) => {
    if (isExpanded(batchId)) {
      expanded.value = expanded.value.filter((key) => key !== batchId)
      return
    }
    expanded.value = [...expanded.value, batchId]
    if (questionsByBatch.value.has(batchId) || isLoadingQuestions(batchId)) return
    await loadBatchQuestions(batchId)
  }

  const retryBatchQuestions = (batchId: BatchKey) => loadBatchQuestions(batchId)

  const toggleBatch = (batchId: BatchKey) => {
    selection.value = toggleBatchSelection(selection.value, batchId)
  }

  const toggleQuestion = (batchId: BatchKey, questionId: string) => {
    const question = questionsFor(batchId).find((item) => item.id === questionId)
    if (question && !question.selectable) return
    selection.value = toggleQuestionSelection(selection.value, batchId, questionId)
  }

  /**
   * 解析本次要练的题目 ID。
   *
   * 两条路径都到这一步才去拉题目，且都以服务端此刻的 `available` 为准：
   * - 整批选中的批次到这一步才解析题目 ID——放在渲染路径就等于全量预取；
   * - 逐题勾选的 ID 也要回查一次可用集合，否则「点了开练之后题目变成待审核」
   *   会让界面的题数与实际进入练习的题数对不上（后端会静默丢弃）。
   */
  const resolveSelectedQuestionIds = async (): Promise<string[]> => {
    const collected: string[] = []
    const seen = new Set<string>()
    const push = (id: string) => {
      if (!id || seen.has(id)) return
      seen.add(id)
      collected.push(id)
    }

    for (const batch of batches.value) {
      const batchId = batch.batchId
      if (resolveBatchCheckState(batchId, selection.value) === 'none') continue
      const unpicked = selection.value.unpicked.get(batchId) ?? new Set<string>()

      if (selection.value.whole.has(batchId)) {
        const questions = await fetchBatchQuestions(batchId, 'available')
        for (const id of resolveWholeBatchQuestionIds(questions, unpicked)) push(id)
        continue
      }

      const pickedIds = selection.value.picked.get(batchId)
      if (!pickedIds || pickedIds.size === 0) continue
      const questions = await fetchBatchQuestions(batchId, 'available')
      const availableIds = new Set(questions.map((question) => question.id))
      for (const id of pickedIds) {
        if (availableIds.has(id) && !unpicked.has(id)) push(id)
      }
    }
    return collected
  }

  /**
   * 创建练习前的确认：本次实际要练的题数与界面显示的已选题数不一致时，必须先告知。
   *
   * 三种成因分别说明，不把「超出上限」或「题目变多」说成「题目不可用」误导用户。
   */
  const confirmCountMismatch = (params: {
    displayed: number
    planned: number
    resolved: number
  }): Promise<boolean> =>
    new Promise((resolve) => {
      let reason = '其中部分题目在勾选之后才变为可选。'
      if (params.resolved > params.planned) {
        reason = `单次练习最多 ${MAX_PRACTICE_QUESTIONS} 题，超出的题目本次不会进入练习。`
      } else if (params.planned < params.displayed) {
        reason = '其中部分题目可能已被删除或转为待审核。'
      }
      uni.showModal({
        title: '可练题目有变化',
        content: `你已选 ${params.displayed} 题，本次将按 ${params.planned} 题创建练习。${reason}是否继续？`,
        success: (result: { confirm?: boolean }) => resolve(Boolean(result?.confirm)),
        fail: () => resolve(false),
      })
    })

  /** 开练：解析 → 校验题数 → 创建练习 → 进作答页。返回 null 表示未创建。 */
  const startPractice = async (): Promise<PracticeSession | null> => {
    // 双击去重：开练要先解析题目（有网络往返），只靠按钮 loading 挡不住第二次点击，
    // 两次并发会创建两条练习。
    if (isStarting.value) return null
    if (selectedCount.value === 0) {
      uni.showToast({ title: '请先选择要练习的题目', icon: 'none' })
      return null
    }
    isStarting.value = true
    try {
      const displayedCount = selectedCount.value
      const resolved = await resolveSelectedQuestionIds()
      if (resolved.length === 0) {
        uni.showToast({ title: '选中的题目已不可用，请刷新后重试', icon: 'none' })
        return null
      }
      const questionIds = resolved.slice(0, MAX_PRACTICE_QUESTIONS)
      if (questionIds.length !== displayedCount) {
        const confirmed = await confirmCountMismatch({
          displayed: displayedCount,
          planned: questionIds.length,
          resolved: resolved.length,
        })
        if (!confirmed) return null
      }

      const session = await apiCreatePractice({
        title: buildPracticeTitle(selectedBatchCount.value, questionIds.length),
        question_ids: questionIds,
        // 后端的显式题目路径按 question_count 截断（默认 10），不传就会静默砍题。
        question_count: questionIds.length,
      })
      if (!session?.id) {
        uni.showToast({ title: '练习创建失败，请重试', icon: 'none' })
        return null
      }
      uni.navigateTo({
        url: `${SESSION_PAGE_URL}?practice_id=${session.id}`,
        fail: () => uni.showToast({ title: '打开练习失败，请重试', icon: 'none' }),
      })
      return session
    } catch (error) {
      console.error('Failed to start question bank practice', error)
      uni.showToast({ title: describeFailure(error, '创建练习失败，请重试'), icon: 'none' })
      return null
    } finally {
      isStarting.value = false
    }
  }

  return {
    batches,
    batchTotal,
    hasMore,
    isLoading,
    isLoadingMore,
    loadError,
    expanded,
    loadingQuestions,
    questionErrors,
    selection,
    isStarting,
    selectedCount,
    selectedBatchCount,
    isExpanded,
    isLoadingQuestions,
    questionError,
    questionsFor,
    checkState,
    selectedIdsFor,
    loadBatches,
    loadMoreBatches,
    toggleExpand,
    retryBatchQuestions,
    toggleBatch,
    toggleQuestion,
    startPractice,
  }
}
