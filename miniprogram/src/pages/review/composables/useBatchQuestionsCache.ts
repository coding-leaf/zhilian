import { ref } from 'vue'
import { apiListQuestionBankItems } from '@/api'
import type { QuestionBankItem } from '@/types'
import { describeFailure } from '@/utils/requestError'
import type { BatchKey } from '@/utils/questionBatch'

const QUESTION_PAGE_SIZE = 50
/** 单次展开/解析最多翻页数，防止异常 total 导致无限翻页。 */
const MAX_QUESTION_PAGES = 20

/** 按批次缓存与按需展开题目列表（未展开的批次不预取）。 */
export function useBatchQuestionsCache() {
  const expanded = ref<BatchKey[]>([])
  const questionsByBatch = ref<Map<BatchKey, QuestionBankItem[]>>(new Map())
  const loadingQuestions = ref<BatchKey[]>([])
  const questionErrors = ref<Map<BatchKey, string>>(new Map())

  const isExpanded = (batchId: BatchKey): boolean => expanded.value.includes(batchId)
  const questionsFor = (batchId: BatchKey): QuestionBankItem[] =>
    questionsByBatch.value.get(batchId) ?? []
  const isLoadingQuestions = (batchId: BatchKey): boolean =>
    loadingQuestions.value.includes(batchId)
  const questionError = (batchId: BatchKey): string => questionErrors.value.get(batchId) ?? ''

  const setQuestionError = (batchId: BatchKey, message: string) => {
    const next = new Map(questionErrors.value)
    if (message) next.set(batchId, message)
    else next.delete(batchId)
    questionErrors.value = next
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

  return {
    expanded,
    loadingQuestions,
    questionErrors,
    isExpanded,
    isLoadingQuestions,
    questionError,
    questionsFor,
    fetchBatchQuestions,
    toggleExpand,
    retryBatchQuestions,
  }
}
