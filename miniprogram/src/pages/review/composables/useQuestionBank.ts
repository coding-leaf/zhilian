/**
 * 题库区块的页面本地状态与编排（协调批次分页、三态选择、按需题目缓存与开练）。
 */

import { computed, ref } from 'vue'
import { apiListQuestionBatches } from '@/api'
import type { QuestionBatchSummary } from '@/types'
import { describeFailure } from '@/utils/requestError'
import {
  countSelectedBatches,
  countSelectedQuestions,
  createBatchSelection,
  resolveBatchCheckState,
  selectedQuestionIds,
  toggleBatchSelection,
  toggleQuestionSelection,
  type BatchCheckState,
  type BatchKey,
  type BatchSelectionState,
} from '@/utils/questionBatch'
import { useBatchQuestionsCache } from './useBatchQuestionsCache'
import { useBatchPracticeLaunch } from './useBatchPracticeLaunch'

const BATCH_PAGE_SIZE = 20

export function useQuestionBank() {
  const batches = ref<QuestionBatchSummary[]>([])
  const batchTotal = ref(0)
  const isLoading = ref(false)
  const isLoadingMore = ref(false)
  const loadError = ref('')
  const reachedEnd = ref(false)
  const loadedPages = ref(0)
  const selection = ref<BatchSelectionState>(createBatchSelection())

  const cache = useBatchQuestionsCache()

  const selectedCount = computed(() => countSelectedQuestions(batches.value, selection.value))
  const selectedBatchCount = computed(() => countSelectedBatches(batches.value, selection.value))
  const hasMore = computed(() => !reachedEnd.value && batches.value.length < batchTotal.value)

  const checkState = (batchId: BatchKey): BatchCheckState =>
    resolveBatchCheckState(batchId, selection.value)
  const selectedIdsFor = (batchId: BatchKey): string[] =>
    selectedQuestionIds(batchId, cache.questionsFor(batchId), selection.value)

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

  const toggleBatch = (batchId: BatchKey) => {
    selection.value = toggleBatchSelection(selection.value, batchId)
  }

  const toggleQuestion = (batchId: BatchKey, questionId: string) => {
    const question = cache.questionsFor(batchId).find((item) => item.id === questionId)
    if (question && !question.selectable) return
    selection.value = toggleQuestionSelection(selection.value, batchId, questionId)
  }

  const { isStarting, startPractice } = useBatchPracticeLaunch({
    batches,
    selection,
    selectedCount,
    selectedBatchCount,
    fetchBatchQuestions: cache.fetchBatchQuestions,
  })

  return {
    batches,
    batchTotal,
    hasMore,
    isLoading,
    isLoadingMore,
    loadError,
    expanded: cache.expanded,
    loadingQuestions: cache.loadingQuestions,
    questionErrors: cache.questionErrors,
    selection,
    isStarting,
    selectedCount,
    selectedBatchCount,
    isExpanded: cache.isExpanded,
    isLoadingQuestions: cache.isLoadingQuestions,
    questionError: cache.questionError,
    questionsFor: cache.questionsFor,
    checkState,
    selectedIdsFor,
    loadBatches,
    loadMoreBatches,
    toggleExpand: cache.toggleExpand,
    retryBatchQuestions: cache.retryBatchQuestions,
    toggleBatch,
    toggleQuestion,
    startPractice,
  }
}
