import { computed, ref } from 'vue'
import {
  adaptQuestion,
  apiGetQuestionsByMaterial,
  apiListQuestionBatches,
  computeKnowledgeCoverage,
  dedupeQuestions,
  MAX_QUESTION_BATCH,
  planGenerationBatches,
  type GenerationBatch,
  type WireQuestion,
} from '@/api'
import type { CoverageResult } from '@/api/adapters/question'
import { isQuestionJobActive, useBackgroundTaskStore } from '@/stores/backgroundTask'
import { safeShowToast } from '@/utils/loadingGuard'
import { describeFailure, RequestError } from '@/utils/requestError'
import { request } from '@/utils/request'
import { describeBatchLabel } from '@/utils/questionBatch'
import type {
  QuestionBatchSummary,
  QuestionGenerationJob,
  QuestionItem,
} from '@/types'
import {
  useComposeConfig,
  type ComposeMode,
  type ComposeScope,
  type KnowledgePointOption,
} from './useComposeConfig'

export type { ComposeMode, ComposeScope, KnowledgePointOption }

export function useQuestionCompose() {
  const config = useComposeConfig()
  const taskStore = useBackgroundTaskStore()
  const {
    scope,
    selectedKpIds,
    effectiveKpIds,
    composeMode,
    selectedTypes,
    questionCount,
    difficulty,
    plannedCount,
    exceedsPracticeLimit,
  } = config

  const questions = ref<QuestionItem[]>([])
  const removedIds = ref<string[]>([])
  const activeTargetKpIds = ref<string[]>([])
  const hasGenerated = ref(false)
  const isGenerating = ref(false)
  const isStarting = ref(false)
  const activeJobId = ref<string | null>(null)
  const jobMode = ref<'compose' | 'fill_gap' | 'regenerate'>('compose')
  const replacingQuestionId = ref<string | null>(null)
  const pendingReviewNoticeCount = ref(0)

  const pendingBatches = ref<GenerationBatch[]>([])
  const batchAvailableBuffer = ref<QuestionItem[]>([])
  const batchPendingCountBuffer = ref(0)
  const batchIdsBuffer = ref<string[]>([])
  const totalBatchKps = ref(0)
  const completedBatchKps = ref(0)

  const generatedBatches = ref<QuestionBatchSummary[]>([])
  const generatedBatchFallback = ref('')
  const applyingJobIds = new Set<string>()

  const activeJob = computed<QuestionGenerationJob | null>(() =>
    activeJobId.value ? taskStore.questionJobs.get(activeJobId.value) ?? null : null,
  )

  const isJobInFlight = computed(() =>
    Boolean(activeJob.value && isQuestionJobActive(activeJob.value)),
  )

  const jobProgressText = computed(() => {
    const job = activeJob.value
    if (!job || !isQuestionJobActive(job)) return ''
    const totalKps = totalBatchKps.value > 0 ? totalBatchKps.value : job.total_kps
    const doneKps =
      totalBatchKps.value > 0 ? completedBatchKps.value + job.completed_kps : job.completed_kps
    return `正在后台生成题目 (${doneKps} / ${totalKps} 考点)... 您可以留在当前页等待，或随时返回浏览讲义`
  })

  const jobProgressPercent = computed(() => {
    const job = activeJob.value
    if (!job) return 0
    const totalKps = totalBatchKps.value > 0 ? totalBatchKps.value : job.total_kps
    if (totalKps <= 0) return 0
    const doneKps =
      totalBatchKps.value > 0 ? completedBatchKps.value + job.completed_kps : job.completed_kps
    return Math.min(100, Math.round((doneKps / totalKps) * 100))
  })

  const remainingQuestions = computed(() =>
    questions.value.filter((question) => question.id && !removedIds.value.includes(question.id)),
  )

  const targetKpIdsForCoverage = computed(() =>
    activeTargetKpIds.value.length > 0 ? activeTargetKpIds.value : effectiveKpIds.value,
  )

  const coverage = computed<CoverageResult>(() =>
    computeKnowledgeCoverage(remainingQuestions.value, targetKpIdsForCoverage.value),
  )

  const canStart = computed(
    () => remainingQuestions.value.length > 0 && coverage.value.missing.length === 0,
  )

  const generationNotice = computed(() => {
    if (!hasGenerated.value) return ''
    const parts: string[] = []
    if (
      composeMode.value === 'smart_sample'
      && selectedKpIds.value.length > targetKpIdsForCoverage.value.length
    ) {
      parts.push(
        `已从所选 ${selectedKpIds.value.length} 个考点中均匀抽取 ${targetKpIdsForCoverage.value.length} 个考点出题`,
      )
    } else if (composeMode.value === 'full_coverage' && plannedCount.value > questionCount.value) {
      parts.push(
        `为覆盖全部 ${targetKpIdsForCoverage.value.length} 个考点，本次按 ${plannedCount.value} 题目标生成`,
      )
    }
    if (pendingReviewNoticeCount.value > 0) {
      parts.push(`另有 ${pendingReviewNoticeCount.value} 道题待审核，本次展示全部可作答题目`)
    }
    if (coverage.value.missing.length > 0) {
      parts.push(`合格题未覆盖 ${coverage.value.missing.length} 个考点，需补齐后才能开始作答`)
    }
    return parts.join('；')
  })

  const enrichKpNames = (items: QuestionItem[]): QuestionItem[] => {
    const kpNameById = new Map(config.availableKpList.value.map((kp) => [kp.id, kp.name]))
    return items.map((item) => {
      const resolvedName =
        item.knowledge_point_name
        || (item.knowledge_point_id ? kpNameById.get(item.knowledge_point_id) : undefined)
        || item.knowledge_point
        || null
      return resolvedName
        ? { ...item, knowledge_point_name: resolvedName, knowledge_point: item.knowledge_point || resolvedName }
        : item
    })
  }

  const fetchBatchQuestions = async (
    batchId: string,
  ): Promise<{ available: QuestionItem[]; pendingCount: number }> => {
    const pageSize = 100
    const allRaw: WireQuestion[] = []
    let page = 1
    while (page <= 10) {
      const res = await request<{ items?: WireQuestion[]; total?: number } | WireQuestion[]>({
        url: `/questions?batch_id=${encodeURIComponent(batchId)}&page=${page}&page_size=${pageSize}`,
        method: 'GET',
      })
      const pageItems = Array.isArray(res) ? res : res?.items || []
      allRaw.push(...pageItems)
      const total = Array.isArray(res) ? pageItems.length : (res?.total ?? pageItems.length)
      if (pageItems.length < pageSize || allRaw.length >= total) break
      page += 1
    }
    const pendingCount = allRaw.filter((item) => item.status === 'pending_review').length
    const usable = allRaw.filter((item) => !item.status || item.status === 'available')
    return { available: enrichKpNames(usable.map(adaptQuestion)), pendingCount }
  }

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

  const generatedBatchNotice = computed(() => {
    if (generatedBatchLabels.value.length > 0) {
      return `本次生成批次：${generatedBatchLabels.value.join('；')}。已归入「学情 - 我的题库」，可在那里按批次再练。`
    }
    return generatedBatchFallback.value
  })

  const resetBatchPipeline = () => {
    pendingBatches.value = []
    batchAvailableBuffer.value = []
    batchPendingCountBuffer.value = 0
    batchIdsBuffer.value = []
    totalBatchKps.value = 0
    completedBatchKps.value = 0
  }

  const clearActiveJob = () => {
    activeJobId.value = null
    replacingQuestionId.value = null
    jobMode.value = 'compose'
    resetBatchPipeline()
  }

  const startBatchJob = (batch: GenerationBatch) =>
    taskStore.startQuestionJob({
      folder_id: scope.value.folderId,
      material_id: scope.value.folderId ? undefined : scope.value.materialId,
      knowledge_point_ids: [...batch.knowledgePointIds],
      question_types: [...selectedTypes.value],
      count: batch.count,
      difficulty: difficulty.value,
    })

  const loadJobResultItems = async (
    job: QuestionGenerationJob,
  ): Promise<{ available: QuestionItem[]; pendingCount: number }> => {
    if (job.batch_id) {
      return fetchBatchQuestions(job.batch_id)
    }
    if (scope.value.materialId) {
      const list = await apiGetQuestionsByMaterial(scope.value.materialId)
      const idSet = new Set(job.question_ids)
      const matched = idSet.size > 0 ? list.filter((item) => idSet.has(item.id)) : list
      return { available: enrichKpNames(matched), pendingCount: 0 }
    }
    return { available: [], pendingCount: 0 }
  }

  const applyCompletedJob = async (job: QuestionGenerationJob): Promise<number> => {
    if (applyingJobIds.has(job.id)) return 0
    applyingJobIds.add(job.id)
    const mode = jobMode.value
    const targetReplaceId = replacingQuestionId.value
    try {
      const { available, pendingCount } = await loadJobResultItems(job)
      taskStore.dismissTask(`job:${job.id}`)

      if (mode === 'regenerate' && targetReplaceId) {
        const replacement = available.find((item) => item.id !== targetReplaceId) || available[0]
        if (!replacement) {
          safeShowToast('未能生成替代题目，请稍后重试')
          clearActiveJob()
          return 0
        }
        questions.value = questions.value.map((item) =>
          item.id === targetReplaceId ? replacement : item,
        )
        removedIds.value = removedIds.value.filter((id) => id !== targetReplaceId)
        clearActiveJob()
        return available.length
      }

      batchAvailableBuffer.value = dedupeQuestions([...batchAvailableBuffer.value, ...available])
      batchPendingCountBuffer.value += pendingCount
      if (job.batch_id) batchIdsBuffer.value = [...batchIdsBuffer.value, job.batch_id]
      completedBatchKps.value += job.total_kps || 0

      if (pendingBatches.value.length > 0) {
        const [nextBatch, ...rest] = pendingBatches.value
        pendingBatches.value = rest
        const nextJob = await startBatchJob(nextBatch)
        if (nextJob.status === 'completed') {
          return await applyCompletedJob(nextJob)
        }
        if (nextJob.status === 'failed') {
          safeShowToast(nextJob.error_message || '后台出题失败，请重试')
          clearActiveJob()
          return 0
        }
        activeJobId.value = nextJob.id
        return 0
      }

      const mergedAvailable = batchAvailableBuffer.value
      const totalPending = batchPendingCountBuffer.value
      const allBatchIds = [...batchIdsBuffer.value]

      if (mode === 'fill_gap') {
        questions.value = dedupeQuestions([...questions.value, ...mergedAvailable])
        const addedIds = new Set(mergedAvailable.map((item) => item.id))
        removedIds.value = removedIds.value.filter((id) => !addedIds.has(id))
        hasGenerated.value = true
        clearActiveJob()
        return mergedAvailable.length
      }

      if (mergedAvailable.length === 0) {
        safeShowToast('未生成合格题目，请调整配置后重试')
        clearActiveJob()
        return 0
      }
      questions.value = mergedAvailable
      removedIds.value = []
      hasGenerated.value = true
      pendingReviewNoticeCount.value = totalPending
      clearActiveJob()
      if (allBatchIds.length > 0) await loadGeneratedBatches(allBatchIds)
      return mergedAvailable.length
    } catch (error: any) {
      if (!(error instanceof RequestError)) {
        safeShowToast(describeFailure(error, '加载生成题目失败'))
      }
      taskStore.dismissTask(`job:${job.id}`)
      clearActiveJob()
      return 0
    } finally {
      applyingJobIds.delete(job.id)
    }
  }

  /** 提交后台异步出题任务；若任务当场完成则返回合格题数，进行中返回 0 并由任务流续接。 */
  const generate = async (): Promise<number> => {
    if (selectedKpIds.value.length === 0) {
      safeShowToast('请至少勾选一个知识点')
      return 0
    }
    if (exceedsPracticeLimit.value) {
      safeShowToast('单次练习最多 50 题，请改用按题量抽考或缩减至 50 个考点以内')
      return 0
    }
    const targetIds = [...effectiveKpIds.value]
    const targetTotal = Math.max(1, plannedCount.value)
    const batches: GenerationBatch[] =
      targetIds.length > MAX_QUESTION_BATCH
        ? planGenerationBatches(targetIds, targetTotal)
        : [{ knowledgePointIds: targetIds, count: Math.min(MAX_QUESTION_BATCH, targetTotal) }]

    isGenerating.value = true
    try {
      resetBatchPipeline()
      activeTargetKpIds.value = targetIds
      pendingBatches.value = batches.slice(1)
      totalBatchKps.value = batches.length > 1 ? targetIds.length : 0
      jobMode.value = 'compose'
      replacingQuestionId.value = null

      const job = await startBatchJob(batches[0])
      if (job.status === 'completed') {
        return await applyCompletedJob(job)
      }
      if (job.status === 'failed') {
        safeShowToast(job.error_message || '出题任务失败，请重试')
        clearActiveJob()
        return 0
      }
      activeJobId.value = job.id
      return 0
    } catch (error: any) {
      if (!(error instanceof RequestError)) {
        safeShowToast(describeFailure(error, '创建出题任务失败'))
      }
      clearActiveJob()
      return 0
    } finally {
      isGenerating.value = false
    }
  }

  const attachActiveJobForScope = () => {
    if (activeJobId.value && isJobInFlight.value) return
    for (const job of taskStore.questionJobs.values()) {
      if (!isQuestionJobActive(job)) continue
      const matchesFolder = scope.value.folderId && job.folder_id === scope.value.folderId
      const matchesMaterial =
        !scope.value.folderId && scope.value.materialId && job.material_id === scope.value.materialId
      if (matchesFolder || matchesMaterial) {
        jobMode.value = 'compose'
        activeJobId.value = job.id
        return
      }
    }
  }

  const loadBatchQuestions = async (batchId: string): Promise<number> => {
    const { available, pendingCount } = await fetchBatchQuestions(batchId)
    if (available.length === 0) return 0
    const loadedKpIds = Array.from(
      new Set(
        available
          .map((item) => item.knowledge_point_id)
          .filter((id): id is string => Boolean(id)),
      ),
    )
    selectedKpIds.value = loadedKpIds
    activeTargetKpIds.value = loadedKpIds
    questions.value = available
    removedIds.value = []
    hasGenerated.value = true
    pendingReviewNoticeCount.value = pendingCount
    await loadGeneratedBatches([batchId])
    return available.length
  }

  /** 载入该资料已持久化的题目，供「继续核对已生成题目」入口直接进入核对视图。 */
  const loadExistingQuestions = async (materialId: string): Promise<number> => {
    const loaded = enrichKpNames(await apiGetQuestionsByMaterial(materialId))
    if (loaded.length === 0) return 0
    const loadedKpIds = Array.from(
      new Set(
        loaded
          .map((item) => item.knowledge_point_id)
          .filter((id): id is string => Boolean(id)),
      ),
    )
    selectedKpIds.value = loadedKpIds
    activeTargetKpIds.value = loadedKpIds
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

  const regenerateQuestion = async (question: QuestionItem) => {
    const knowledgePointId = question.knowledge_point_id || selectedKpIds.value[0]
    if (!knowledgePointId) return
    isGenerating.value = true
    try {
      const job = await taskStore.startQuestionJob({
        folder_id: scope.value.folderId,
        material_id: scope.value.folderId ? undefined : (question.material_id || scope.value.materialId),
        knowledge_point_ids: [knowledgePointId],
        question_types: [question.type],
        count: 1,
        difficulty: difficulty.value,
      })
      jobMode.value = 'regenerate'
      replacingQuestionId.value = question.id
      if (job.status === 'completed') {
        await applyCompletedJob(job)
      } else if (job.status === 'failed') {
        safeShowToast(job.error_message || '重新生成失败')
        clearActiveJob()
      } else {
        activeJobId.value = job.id
      }
    } catch (error: any) {
      if (!(error instanceof RequestError)) {
        safeShowToast(describeFailure(error, '重新生成失败'))
      }
    } finally {
      isGenerating.value = false
    }
  }

  const fillCoverageGap = async () => {
    const missing = coverage.value.missing
    if (missing.length === 0) return
    const batches: GenerationBatch[] =
      missing.length > MAX_QUESTION_BATCH
        ? planGenerationBatches(missing, missing.length)
        : [{ knowledgePointIds: missing, count: Math.min(MAX_QUESTION_BATCH, Math.max(1, missing.length)) }]

    isGenerating.value = true
    try {
      resetBatchPipeline()
      pendingBatches.value = batches.slice(1)
      totalBatchKps.value = batches.length > 1 ? missing.length : 0
      jobMode.value = 'fill_gap'
      replacingQuestionId.value = null

      const job = await startBatchJob(batches[0])
      if (job.status === 'completed') {
        await applyCompletedJob(job)
      } else if (job.status === 'failed') {
        safeShowToast(job.error_message || '补齐失败')
        clearActiveJob()
      } else {
        activeJobId.value = job.id
      }
    } catch (error: any) {
      if (!(error instanceof RequestError)) {
        safeShowToast(describeFailure(error, '补齐失败'))
      }
      clearActiveJob()
    } finally {
      isGenerating.value = false
    }
  }

  return {
    ...config,
    questions,
    remainingQuestions,
    removedIds,
    activeTargetKpIds,
    targetKpIdsForCoverage,
    generationNotice,
    generatedBatches,
    generatedBatchLabels,
    generatedBatchNotice,
    coverage,
    canStart,
    isGenerating,
    isStarting,
    activeJobId,
    activeJob,
    isJobInFlight,
    jobProgressText,
    jobProgressPercent,
    generate,
    applyCompletedJob,
    clearActiveJob,
    attachActiveJobForScope,
    loadBatchQuestions,
    loadExistingQuestions,
    removeQuestion,
    regenerateQuestion,
    fillCoverageGap,
  }
}
