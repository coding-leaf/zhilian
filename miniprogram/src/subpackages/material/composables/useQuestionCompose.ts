import { computed, ref } from 'vue'
import { apiGenerateQuestions, computeKnowledgeCoverage, dedupeQuestions, planGenerationBatches } from '@/api'
import type { CoverageResult } from '@/api/adapters/question'
import type { FolderKnowledgePointItem, QuestionItem, QuestionType } from '@/types'

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
      pending += result.pending_count
    }
    return { questions: dedupeQuestions(collected), pending }
  }

  const generate = async () => {
    if (selectedKpIds.value.length === 0) {
      uni.showToast({ title: '请至少勾选一个知识点', icon: 'none' })
      return
    }
    isGenerating.value = true
    try {
      const { questions: generated } = await generateForKnowledgePoints(
        selectedKpIds.value,
        questionCount.value,
      )
      if (generated.length === 0) {
        uni.showToast({ title: '未生成合格题目，请调整配置后重试', icon: 'none' })
        return
      }
      questions.value = generated
      removedIds.value = []
      hasGenerated.value = true
    } catch (error: any) {
      uni.showToast({ title: error?.message || '生成失败', icon: 'none' })
    } finally {
      isGenerating.value = false
    }
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
    removeQuestion,
    restoreQuestion,
    regenerateQuestion,
    fillCoverageGap,
  }
}
