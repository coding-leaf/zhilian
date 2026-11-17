import { computed, ref } from 'vue'
import {
  apiGetQuestionsByMaterial,
  apiListQuestionBatches,
  computeKnowledgeCoverage,
  dedupeQuestions,
} from '@/api'
import type { CoverageResult } from '@/api/adapters/question'
import { describeBatchLabel } from '@/utils/questionBatch'
import { generateQuestionsInBatches } from '@/utils/questionGeneration'
import type { QuestionBatchSummary, QuestionItem } from '@/types'
import { useComposeConfig, type ComposeScope, type KnowledgePointOption } from './useComposeConfig'

export type { ComposeScope, KnowledgePointOption }

export function useQuestionCompose() {
  const config = useComposeConfig()
  const { scope, selectedKpIds, selectedTypes, questionCount, difficulty, plannedCount } = config

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

  const generateForPoints = (knowledgePointIds: string[], desiredCount: number) =>
    generateQuestionsInBatches({
      folderId: scope.value.folderId,
      materialId: scope.value.materialId,
      knowledgePointIds,
      desiredCount,
      questionTypes: selectedTypes.value,
      difficulty: difficulty.value,
    })

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

  /** 生成题目：返回本次合格题数量（失败或 0 题返回 0）。 */
  const generate = async (): Promise<number> => {
    if (selectedKpIds.value.length === 0) {
      uni.showToast({ title: '请至少勾选一个知识点', icon: 'none' })
      return 0
    }
    isGenerating.value = true
    try {
      const { questions: generated, batchIds } = await generateForPoints(
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

  /** 载入该资料已持久化的题目，供「继续核对已生成题目」入口直接进入核对视图。 */
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

  /** 对不合格题目按原考点重新生成，补齐后替换该题。 */
  const regenerateQuestion = async (question: QuestionItem) => {
    const knowledgePointId = question.knowledge_point_id || selectedKpIds.value[0]
    if (!knowledgePointId) return
    isGenerating.value = true
    try {
      const { questions: generated } = await generateForPoints([knowledgePointId], 1)
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
      const { questions: generated } = await generateForPoints(missing, missing.length)
      questions.value = dedupeQuestions([...questions.value, ...generated])
      const generatedIds = new Set(generated.map((item) => item.id))
      removedIds.value = removedIds.value.filter((id) => !generatedIds.has(id))
    } catch (error: any) {
      uni.showToast({ title: error?.message || '补齐失败', icon: 'none' })
    } finally {
      isGenerating.value = false
    }
  }

  return {
    ...config,
    questions,
    remainingQuestions,
    removedIds,
    generationNotice,
    generatedBatches,
    generatedBatchLabels,
    generatedBatchNotice,
    coverage,
    canStart,
    isGenerating,
    isStarting,
    generate,
    loadExistingQuestions,
    removeQuestion,
    regenerateQuestion,
    fillCoverageGap,
  }
}
