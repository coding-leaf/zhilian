import { computed, ref } from 'vue'
import {
  apiGenerateQuestions,
  apiGetQuestionsByMaterial,
  apiListQuestionBatches,
  computeKnowledgeCoverage,
  dedupeQuestions,
  planGenerationBatches,
} from '@/api'
import type { CoverageResult } from '@/api/adapters/question'
import { describeBatchLabel } from '@/utils/questionBatch'
import type { FolderKnowledgePointItem, QuestionItem, QuestionBatchSummary, QuestionType } from '@/types'

export interface ComposeScope {
  folderId?: string
  materialId?: string
}

export interface KnowledgePointOption {
  id: string
  name: string
}

const DEFAULT_TYPES: QuestionType[] = [
  'single_choice',
  'multiple_choice',
  'true_false',
  'short_answer',
]

export function useQuestionCompose() {
  const scope = ref<ComposeScope>({})
  const availableKpList = ref<KnowledgePointOption[]>([])
  const selectedKpIds = ref<string[]>([])
  const selectedTypes = ref<QuestionType[]>([...DEFAULT_TYPES])
  const questionCount = ref<number>(5)
  const difficulty = ref<number>(3)

  const questions = ref<QuestionItem[]>([])
  const removedIds = ref<string[]>([])
  const hasGenerated = ref(false)
  const isGenerating = ref(false)
  const isStarting = ref(false)

  /** 本次生成的批次摘要：标签由 describeBatchLabel 统一推导（与题库区块同一函数）。 */
  const generatedBatches = ref<QuestionBatchSummary[]>([])
  const generatedBatchFallback = ref('')

  const remainingQuestions = computed(() =>
    questions.value.filter((question) => question.id && !removedIds.value.includes(question.id)),
  )

  const coverage = computed<CoverageResult>(() =>
    computeKnowledgeCoverage(remainingQuestions.value, selectedKpIds.value),
  )

  const canStart = computed(
    () => remainingQuestions.value.length > 0 && coverage.value.missing.length === 0,
  )

  const plannedCount = computed(() =>
    Math.max(selectedKpIds.value.length, questionCount.value),
  )

  /** 生成前后都据实披露题量调整与合格题覆盖缺口，剔除题目后自动重算。 */
  const generationNotice = computed(() => {
    if (!hasGenerated.value) return ''
    const parts: string[] = []
    if (plannedCount.value > questionCount.value) {
      parts.push(`为覆盖全部 ${selectedKpIds.value.length} 个考点，本次按 ${plannedCount.value} 题目标生成`)
    }
    if (coverage.value.missing.length > 0) {
      parts.push(`合格题未覆盖 ${coverage.value.missing.length} 个考点，需补齐后才能开始作答`)
    }
    return parts.join('；')
  })

  const isAllKpSelected = computed(
    () =>
      availableKpList.value.length > 0 &&
      selectedKpIds.value.length === availableKpList.value.length,
  )

  const setKnowledgePoints = (list: KnowledgePointOption[]) => {
    availableKpList.value = list
    selectedKpIds.value = list.map((point) => point.id)
  }

  const isKpSelected = (id: string) => selectedKpIds.value.includes(id)
  const toggleKp = (id: string) => {
    selectedKpIds.value = isKpSelected(id)
      ? selectedKpIds.value.filter((value) => value !== id)
      : [...selectedKpIds.value, id]
  }
  const toggleSelectAllKp = () => {
    selectedKpIds.value = isAllKpSelected.value
      ? []
      : availableKpList.value.map((point) => point.id)
  }

  const isTypeSelected = (type: QuestionType) => selectedTypes.value.includes(type)
  const toggleType = (type: QuestionType) => {
    if (isTypeSelected(type)) {
      if (selectedTypes.value.length === 1) {
        uni.showToast({ title: '至少选择一种题型', icon: 'none' })
        return
      }
      selectedTypes.value = selectedTypes.value.filter((value) => value !== type)
      return
    }
    selectedTypes.value = [...selectedTypes.value, type]
  }

  const generateForKnowledgePoints = async (knowledgePointIds: string[], desiredCount: number) => {
    const batches = planGenerationBatches(knowledgePointIds, desiredCount)
    const collected: QuestionItem[] = []
    const batchIds: string[] = []
    let pending = 0
    for (const batch of batches) {
      const result = await apiGenerateQuestions({
        folder_id: scope.value.folderId,
        material_id: scope.value.folderId ? undefined : scope.value.materialId,
        knowledge_point_ids: batch.knowledgePointIds,
        question_types: selectedTypes.value,
        count: batch.count,
        difficulty: difficulty.value,
      })
      collected.push(...result.qualified_questions)
      if (result.batch_id) batchIds.push(result.batch_id)
      pending += result.pending_count
    }
    return { questions: dedupeQuestions(collected), pending, batchIds }
  }

  /**
   * 拉取本次生成批次的摘要用于展示。
   *
   * 标签只在题库批次接口上有完整输入（一个批次可以横跨多份资料，「来源」不是生成
   * 响应能拼出来的），所以这里回查同一份数据，保证两处说的「同一个批次」一致。
   * 回查失败只降级提示，不影响核对与开练。
   */
  const loadGeneratedBatches = async (batchIds: string[]) => {
    generatedBatchFallback.value = ''
    if (batchIds.length === 0) {
      generatedBatches.value = []
      return
    }
    try {
      const wanted = new Set(batchIds)
      const result = await apiListQuestionBatches({ page: 1, page_size: 50 })
      generatedBatches.value = result.items.filter(
        (batch) => batch.batchId !== null && wanted.has(batch.batchId),
      )
      if (generatedBatches.value.length === 0) {
        generatedBatchFallback.value = '本次生成已归入题库，可稍后在学情页确认。'
      }
    } catch (error) {
      console.error('Failed to load generated batch summaries', error)
      generatedBatches.value = []
      generatedBatchFallback.value = '本次生成已归入题库，但批次信息暂时取不到。'
    }
  }

  const generatedBatchLabels = computed(() =>
    generatedBatches.value.map((batch) => describeBatchLabel(batch)),
  )

  /** 核对视图顶部的一行提示：有批次就报批次，取不到就如实说明。 */
  const generatedBatchNotice = computed(() => {
    if (generatedBatchLabels.value.length > 0) {
      return `本次生成批次：${generatedBatchLabels.value.join('；')}。已归入「学情 - 我的题目」，可在那里按批次再练。`
    }
    return generatedBatchFallback.value
  })

  /**
   * 生成题目。
   *
   * 返回值即「本次合格题数量」，调用方据此决定是否切到核对视图：
   * 失败与零合格题都返回 0，使调用方无需自行区分异常与空结果——
   * 两种情况都必须留在配置区，展示一个空核对列表比留在配置区更糟。
   */
  const generate = async (): Promise<number> => {
    if (selectedKpIds.value.length === 0) {
      uni.showToast({ title: '请至少勾选一个知识点', icon: 'none' })
      return 0
    }
    isGenerating.value = true
    try {
      const { questions: generated, batchIds } = await generateForKnowledgePoints(
        selectedKpIds.value,
        questionCount.value,
      )
      if (generated.length === 0) {
        uni.showToast({ title: '未生成合格题目，请调整配置后重试', icon: 'none' })
        return 0
      }
      questions.value = generated
      removedIds.value = []
      hasGenerated.value = true
      await loadGeneratedBatches(batchIds)
      uni.showToast({ title: `已生成 ${generated.length} 道题目`, icon: 'success' })
      return generated.length
    } catch (error: any) {
      uni.showToast({ title: error?.message || '生成失败', icon: 'none' })
      return 0
    } finally {
      isGenerating.value = false
    }
  }

  /**
   * 载入该资料已持久化的题目，供「继续核对已生成题目」入口直接进入核对视图。
   *
   * 选中考点取自已加载题目**实际覆盖**的考点集合，因此覆盖率缺口必然为空——
   * 这批题本来就只为这些考点生成过，「缺口」在这里不是缺口，不该拦住作答。
   * 一条都没载到时返回 0，由调用方留在配置区。
   */
  const loadExistingQuestions = async (materialId: string): Promise<number> => {
    const loaded = await apiGetQuestionsByMaterial(materialId)
    if (loaded.length === 0) return 0
    selectedKpIds.value = Array.from(
      new Set(
        loaded
          .map((item) => item.knowledge_point_id)
          .filter((id): id is string => Boolean(id)),
      ),
    )
    questions.value = loaded
    removedIds.value = []
    hasGenerated.value = true
    return loaded.length
  }

  const removeQuestion = (target: QuestionItem | string) => {
    const questionId = typeof target === 'string' ? target : target.id
    if (!questionId || removedIds.value.includes(questionId)) return
    removedIds.value = [...removedIds.value, questionId]
  }

  const restoreQuestion = (questionId: string) => {
    removedIds.value = removedIds.value.filter((id) => id !== questionId)
  }

  /** 对不合格题目按原考点重新生成，补齐后替换该题。 */
  const regenerateQuestion = async (question: QuestionItem) => {
    const knowledgePointId = question.knowledge_point_id || selectedKpIds.value[0]
    if (!knowledgePointId) return
    isGenerating.value = true
    try {
      const { questions: generated } = await generateForKnowledgePoints([knowledgePointId], 1)
      const replacement = generated.find((item) => item.id !== question.id)
      if (!replacement) {
        uni.showToast({ title: '未能生成替代题目，请稍后重试', icon: 'none' })
        return
      }
      questions.value = questions.value.map((item) => (item.id === question.id ? replacement : item))
      removedIds.value = removedIds.value.filter((id) => id !== question.id)
    } catch (error: any) {
      uni.showToast({ title: error?.message || '重新生成失败', icon: 'none' })
    } finally {
      isGenerating.value = false
    }
  }

  const fillCoverageGap = async () => {
    const missing = coverage.value.missing
    if (missing.length === 0) return
    isGenerating.value = true
    try {
      const { questions: generated } = await generateForKnowledgePoints(missing, missing.length)
      questions.value = dedupeQuestions([...questions.value, ...generated])
      // 若补齐题与已剔除题为同一条目，则以生成结果恢复其可见性
      const generatedIds = new Set(generated.map((item) => item.id))
      removedIds.value = removedIds.value.filter((id) => !generatedIds.has(id))
    } catch (error: any) {
      uni.showToast({ title: error?.message || '补齐失败', icon: 'none' })
    } finally {
      isGenerating.value = false
    }
  }

  const setScope = (next: ComposeScope) => {
    scope.value = next
  }

  const flattenKnowledgePoints = (list: FolderKnowledgePointItem[]): KnowledgePointOption[] =>
    list.map((point) => ({ id: point.id, name: point.name }))

  return {
    scope,
    setScope,
    availableKpList,
    selectedKpIds,
    selectedTypes,
    questionCount,
    difficulty,
    questions,
    remainingQuestions,
    removedIds,
    generationNotice,
    generatedBatches,
    generatedBatchLabels,
    generatedBatchNotice,
    coverage,
    canStart,
    plannedCount,
    isAllKpSelected,
    isGenerating,
    isStarting,
    setKnowledgePoints,
    flattenKnowledgePoints,
    isKpSelected,
    toggleKp,
    toggleSelectAllKp,
    isTypeSelected,
    toggleType,
    generate,
    loadExistingQuestions,
    removeQuestion,
    restoreQuestion,
    regenerateQuestion,
    fillCoverageGap,
  }
}
