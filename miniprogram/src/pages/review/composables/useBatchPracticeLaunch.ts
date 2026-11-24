import { ref, type ComputedRef, type Ref } from 'vue'
import { MAX_PRACTICE_QUESTIONS, apiCreatePractice } from '@/api'
import type { PracticeSession, QuestionBankItem, QuestionBatchSummary } from '@/types'
import { describeFailure } from '@/utils/requestError'
import {
  buildPracticeTitle,
  resolveBatchCheckState,
  resolveWholeBatchQuestionIds,
  type BatchKey,
  type BatchSelectionState,
} from '@/utils/questionBatch'

const SESSION_PAGE_URL = '/subpackages/practice/pages/session/index'

interface BatchLaunchDeps {
  batches: Ref<QuestionBatchSummary[]>
  selection: Ref<BatchSelectionState>
  selectedCount: ComputedRef<number>
  selectedBatchCount: ComputedRef<number>
  fetchBatchQuestions: (
    batchId: BatchKey,
    reviewStatus?: 'available',
  ) => Promise<QuestionBankItem[]>
}

/** 创建练习前的确认：实际要练的题数与界面显示不一致时，按成因向用户说明。 */
function confirmPracticeCountMismatch(params: {
  displayed: number
  planned: number
  resolved: number
}): Promise<boolean> {
  return new Promise((resolve) => {
    let reason = '其中部分题目在勾选之后才变为可选。'
    if (params.resolved > params.planned) {
      reason = `单次练习最多 ${MAX_PRACTICE_QUESTIONS} 题，超出的题目本次不会进入练习。`
    } else if (params.planned < params.displayed) {
      reason = '其中部分题目可能已被删除。'
    }
    uni.showModal({
      title: '可练题目有变化',
      content: `你已选 ${params.displayed} 题，本次将按 ${params.planned} 题创建练习。${reason}是否继续？`,
      success: (result: { confirm?: boolean }) => resolve(Boolean(result?.confirm)),
      fail: () => resolve(false),
    })
  })
}

/** 题库区块「立即开练」编排：实时回查 available ID、处理上限差异并跳转作答页。 */
export function useBatchPracticeLaunch(deps: BatchLaunchDeps) {
  const isStarting = ref(false)

  const resolveSelectedQuestionIds = async (): Promise<string[]> => {
    const collected: string[] = []
    const seen = new Set<string>()
    const push = (id: string) => {
      if (!id || seen.has(id)) return
      seen.add(id)
      collected.push(id)
    }

    for (const batch of deps.batches.value) {
      const batchId = batch.batchId
      if (resolveBatchCheckState(batchId, deps.selection.value) === 'none') continue
      const unpicked = deps.selection.value.unpicked.get(batchId) ?? new Set<string>()

      if (deps.selection.value.whole.has(batchId)) {
        const questions = await deps.fetchBatchQuestions(batchId, 'available')
        for (const id of resolveWholeBatchQuestionIds(questions, unpicked)) push(id)
        continue
      }

      const pickedIds = deps.selection.value.picked.get(batchId)
      if (!pickedIds || pickedIds.size === 0) continue
      const questions = await deps.fetchBatchQuestions(batchId, 'available')
      const availableIds = new Set(questions.map((question) => question.id))
      for (const id of pickedIds) {
        if (availableIds.has(id) && !unpicked.has(id)) push(id)
      }
    }
    return collected
  }

  /** 开练：解析 → 校验题数 → 创建练习 → 进作答页。返回 null 表示未创建。 */
  const startPractice = async (): Promise<PracticeSession | null> => {
    if (isStarting.value) return null
    if (deps.selectedCount.value === 0) {
      uni.showToast({ title: '请先选择要练习的题目', icon: 'none' })
      return null
    }
    isStarting.value = true
    try {
      const displayedCount = deps.selectedCount.value
      const resolved = await resolveSelectedQuestionIds()
      if (resolved.length === 0) {
        uni.showToast({ title: '选中的题目已不可用，请刷新后重试', icon: 'none' })
        return null
      }
      const questionIds = resolved.slice(0, MAX_PRACTICE_QUESTIONS)
      if (questionIds.length !== displayedCount) {
        const confirmed = await confirmPracticeCountMismatch({
          displayed: displayedCount,
          planned: questionIds.length,
          resolved: resolved.length,
        })
        if (!confirmed) return null
      }

      const session = await apiCreatePractice({
        title: buildPracticeTitle(deps.selectedBatchCount.value, questionIds.length),
        question_ids: questionIds,
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

  return { isStarting, startPractice }
}
