import { computed, ref } from 'vue'
import {
  adaptQuestion,
  apiGetQuestionsByMaterial,
  apiListQuestionBatches,
  computeKnowledgeCoverage,
  dedupeQuestions,
  MAX_PRACTICE_QUESTIONS,
  type WireQuestion,
} from '@/api'
import type { CoverageResult } from '@/api/adapters/question'
import { isQuestionJobActive, useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useFolderStore } from '@/stores/folder'
import { useMaterialStore } from '@/stores/material'
import { usePracticeStore } from '@/stores/practice'
import { safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import { describeFailure, RequestError } from '@/utils/requestError'
import { request } from '@/utils/request'
import { describeBatchLabel } from '@/utils/questionBatch'
import { mapTreeNodesToComposeOptions } from '../utils/composeHelpers'
import { flattenTreeWithParents } from '../utils/courseStudy'
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
export type ComposeViewMode = 'config' | 'generating' | 'ready'

function matchesJobScope(
  job: Pick<QuestionGenerationJob, 'folder_id' | 'material_id'>,
  targetScope: ComposeScope,
): boolean {
  if (targetScope.folderId) return job.folder_id === targetScope.folderId
  if (targetScope.materialId) return !job.folder_id && job.material_id === targetScope.materialId
  return false
}

export function useQuestionCompose() {
  const config = useComposeConfig()
  const taskStore = useBackgroundTaskStore()
  const materialStore = useMaterialStore()
  const folderStore = useFolderStore()
  const practiceStore = usePracticeStore()
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

  const viewMode = ref<ComposeViewMode>('config')
  const questions = ref<QuestionItem[]>([])
  const removedIds = ref<string[]>([])
  const activeTargetKpIds = ref<string[]>([])
  const hasGenerated = ref(false)
  const isGenerating = ref(false)
  const isStarting = ref(false)
  const isLoadingKp = ref(false)
  const isLoadingReady = ref(false)
  const activeJobId = ref<string | null>(null)

  const readyPracticeId = ref<string | null>(null)
  const readyPracticeTitle = ref('')
  const readyAvailableCount = ref(0)
  const readyCoveredKpCount = ref(0)
  const readyPendingCount = ref(0)

  const generatedBatches = ref<QuestionBatchSummary[]>([])
  const generatedBatchFallback = ref('')
  const applyingJobIds = new Set<string>()
  const consumedJobIds = new Set<string>()

  const activeJob = computed<QuestionGenerationJob | null>(() =>
    activeJobId.value ? taskStore.questionJobs.get(activeJobId.value) ?? null : null,
  )

  const isJobInFlight = computed(() =>
    Boolean(activeJob.value && isQuestionJobActive(activeJob.value)),
  )

  const jobProgressText = computed(() => {
    const job = activeJob.value
    if (!job || !isQuestionJobActive(job)) return ''
    return job.total_kps > 0
      ? `正在后台生成题目 (${job.completed_kps} / ${job.total_kps} 考点)...`
      : '正在排队出题，请稍候...'
  })

  const jobProgressPercent = computed(() => {
    const job = activeJob.value
    if (!job || job.total_kps <= 0) return 0
    return Math.min(100, Math.round((job.completed_kps / job.total_kps) * 100))
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

  // 只要存在至少 1 道可用题或已生成练习，绝不因考点覆盖缺口锁死开练
  const canStart = computed(
    () =>
      readyAvailableCount.value > 0
      || remainingQuestions.value.length > 0
      || Boolean(readyPracticeId.value),
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
  ): Promise<QuestionItem[]> => {
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
    const usable = allRaw.filter((item) => !item.status || item.status === 'available')
    return enrichKpNames(usable.map(adaptQuestion))
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
        generatedBatchFallback.value = '本次生成已归入「学情 - 我的题库」。'
      }
    } catch (error) {
      console.error('Failed to load generated batch summaries', error)
      generatedBatches.value = []
      generatedBatchFallback.value = '本次生成已归入「学情 - 我的题库」。'
    }
  }

  const generatedBatchLabels = computed(() =>
    generatedBatches.value.map((batch) => describeBatchLabel(batch)),
  )

  const generatedBatchNotice = computed(() => {
    if (generatedBatchLabels.value.length > 0) {
      return `本次生成批次：${generatedBatchLabels.value.join('；')}。已归入「学情 - 我的题库」。`
    }
    return generatedBatchFallback.value
  })

  const clearActiveJob = () => {
    activeJobId.value = null
  }

  const reconfig = () => {
    viewMode.value = 'config'
    hasGenerated.value = false
    readyPracticeId.value = null
  }

  const countDistinctKps = (items: QuestionItem[]): number => {
    const ids = new Set(items.map((item) => item.knowledge_point_id).filter(Boolean))
    return ids.size
  }

  const loadJobResultItems = async (
    job: QuestionGenerationJob,
  ): Promise<QuestionItem[]> => {
    if (job.batch_id) {
      return fetchBatchQuestions(job.batch_id)
    }
    if (scope.value.materialId) {
      const list = await apiGetQuestionsByMaterial(scope.value.materialId)
      const usable = list.filter((item) => item.status !== 'pending_review')
      const idSet = new Set(job.question_ids)
      const matched = idSet.size > 0 ? usable.filter((item) => idSet.has(item.id)) : usable
      return enrichKpNames(matched)
    }
    return []
  }

  const applyCompletedJob = async (job: QuestionGenerationJob): Promise<number> => {
    if (applyingJobIds.has(job.id)) return 0
    applyingJobIds.add(job.id)
    consumedJobIds.add(job.id)
    try {
      let available: QuestionItem[] = []
      try {
        available = dedupeQuestions(await loadJobResultItems(job))
      } catch (err) {
        // 若后端已建好 result_practice_id，拉取批次明细失败不应阻断就绪提醒卡展示
        if (!job.result_practice_id) throw err
      }

      taskStore.dismissTask(`job:${job.id}`)

      const fallbackTitle = scope.value.folderId ? '课程针对性测验' : '讲义专题测验'
      const resolvedCount =
        available.length > 0
          ? available.length
          : job.result_practice_id
            ? Math.max(0, job.generated_count)
            : 0
      const resolvedKpCount =
        available.length > 0
          ? Math.max(countDistinctKps(available), coverage.value.covered.length)
          : Math.min(job.total_kps || 0, resolvedCount)

      questions.value = available
      removedIds.value = []
      hasGenerated.value = true
      readyPracticeId.value = job.result_practice_id ?? null
      readyPracticeTitle.value = job.practice_title || fallbackTitle
      readyAvailableCount.value = resolvedCount
      readyCoveredKpCount.value = resolvedKpCount
      readyPendingCount.value = 0

      clearActiveJob()
      viewMode.value = 'ready'

      if (resolvedCount === 0) {
        safeShowToast('未生成合格题目，请调整配置后重试')
        return 0
      }
      if (job.batch_id) await loadGeneratedBatches([job.batch_id])
      return resolvedCount
    } catch (error: any) {
      if (!(error instanceof RequestError)) {
        safeShowToast(describeFailure(error, '加载生成题目失败'))
      }
      taskStore.dismissTask(`job:${job.id}`)
      clearActiveJob()
      viewMode.value = 'config'
      return 0
    } finally {
      applyingJobIds.delete(job.id)
    }
  }

  /** 提交单个后台异步出题任务（支持最多 50 题且自动建卷）；进行中切入 generating 态。 */
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
    const targetTotal = Math.min(MAX_PRACTICE_QUESTIONS, Math.max(1, plannedCount.value))
    const practiceTitle = scope.value.folderId ? '课程针对性测验' : '讲义专题测验'

    isGenerating.value = true
    try {
      activeTargetKpIds.value = targetIds
      readyPracticeId.value = null
      readyPracticeTitle.value = practiceTitle
      readyAvailableCount.value = 0
      readyCoveredKpCount.value = 0
      readyPendingCount.value = 0
      hasGenerated.value = false

      const job = await taskStore.startQuestionJob({
        folder_id: scope.value.folderId,
        material_id: scope.value.folderId ? undefined : scope.value.materialId,
        knowledge_point_ids: targetIds,
        question_types: [...selectedTypes.value],
        count: targetTotal,
        difficulty: difficulty.value,
        auto_create_practice: true,
        source_type: 'initial_compose',
        practice_title: practiceTitle,
      })

      if (job.status === 'completed') {
        return await applyCompletedJob(job)
      }
      if (job.status === 'failed') {
        safeShowToast(job.error_message || '出题任务失败，请重试')
        clearActiveJob()
        viewMode.value = 'config'
        return 0
      }
      activeJobId.value = job.id
      viewMode.value = 'generating'
      return 0
    } catch (error: any) {
      if (!(error instanceof RequestError)) {
        safeShowToast(describeFailure(error, '创建出题任务失败'))
      }
      clearActiveJob()
      viewMode.value = 'config'
      return 0
    } finally {
      isGenerating.value = false
    }
  }

  const hasScopeActiveJob = (targetScope: ComposeScope): boolean => {
    for (const job of taskStore.questionJobs.values()) {
      if (isQuestionJobActive(job) && matchesJobScope(job, targetScope)) {
        return true
      }
    }
    return false
  }

  const attachActiveJobForScope = async (): Promise<void> => {
    if (activeJobId.value && isJobInFlight.value) {
      viewMode.value = 'generating'
      return
    }
    const jobs = Array.from(taskStore.questionJobs.values())
    const activeMatch = jobs.find(
      (job) => isQuestionJobActive(job) && matchesJobScope(job, scope.value),
    )
    if (activeMatch) {
      activeJobId.value = activeMatch.id
      viewMode.value = 'generating'
      return
    }

    if (viewMode.value !== 'ready' && !hasGenerated.value) {
      const completedMatch = jobs
        .filter(
          (job) =>
            job.status === 'completed'
            && !consumedJobIds.has(job.id)
            && matchesJobScope(job, scope.value),
        )
        .sort((a, b) => (b.completed_at || b.updated_at).localeCompare(a.completed_at || a.updated_at))[0]
      if (completedMatch) {
        await applyCompletedJob(completedMatch)
      }
    }
  }

  const loadBatchQuestions = async (batchId: string): Promise<number> => {
    const available = await fetchBatchQuestions(batchId)
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
    readyPracticeId.value = null
    readyPracticeTitle.value = scope.value.folderId ? '课程针对性测验' : '讲义专题测验'
    readyAvailableCount.value = available.length
    readyCoveredKpCount.value = loadedKpIds.length
    readyPendingCount.value = 0
    viewMode.value = 'ready'
    await loadGeneratedBatches([batchId])
    return available.length
  }

  /** 载入该资料已持久化的可用题目。 */
  const loadExistingQuestions = async (materialId: string): Promise<number> => {
    const allLoaded = enrichKpNames(await apiGetQuestionsByMaterial(materialId))
    const loaded = allLoaded.filter((item) => item.status !== 'pending_review')
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
    readyPracticeId.value = null
    readyPracticeTitle.value = '讲义专题测验'
    readyAvailableCount.value = loaded.length
    readyCoveredKpCount.value = loadedKpIds.length
    readyPendingCount.value = 0
    viewMode.value = 'ready'
    return loaded.length
  }

  const removeQuestion = (target: QuestionItem | string) => {
    const questionId = typeof target === 'string' ? target : target.id
    if (!questionId || removedIds.value.includes(questionId)) return
    removedIds.value = [...removedIds.value, questionId]
    readyAvailableCount.value = remainingQuestions.value.length
  }

  const loadScopeKnowledgePoints = async (
    options: { folderId?: string; materialId?: string; preselectedKpId?: string },
  ): Promise<void> => {
    if (!options.folderId && !options.materialId) return
    isLoadingKp.value = true
    try {
      if (options.folderId) {
        const res = await folderStore.loadFolderKnowledgePoints(options.folderId)
        const list = (res.groups || []).flatMap((group) =>
          config.flattenKnowledgePoints(group.knowledge_points || [], {
            materialId: group.material_id,
            materialTitle: group.material_title,
          }),
        )
        config.setKnowledgePoints(list, options.preselectedKpId)
      } else if (options.materialId) {
        const tree = await materialStore.loadKnowledgeTree(options.materialId)
        const nodes = flattenTreeWithParents(tree?.nodes)
        config.setKnowledgePoints(mapTreeNodesToComposeOptions(nodes), options.preselectedKpId)
      }
    } finally {
      isLoadingKp.value = false
    }
  }

  const resolvePracticeForReadyCard = async (): Promise<string | null> => {
    if (!canStart.value || isStarting.value) return null
    if (readyPracticeId.value) return readyPracticeId.value
    isStarting.value = true
    try {
      const questionIds = remainingQuestions.value
        .map((question) => question.id)
        .slice(0, MAX_PRACTICE_QUESTIONS)
      const session = await withBlockingLoading('准备考场中...', () =>
        practiceStore.initPractice(undefined, {
          title: readyPracticeTitle.value || (scope.value.folderId ? '课程针对性测验' : '讲义专题测验'),
          folder_id: scope.value.folderId,
          material_id: scope.value.folderId ? undefined : scope.value.materialId,
          knowledge_point_ids: targetKpIdsForCoverage.value,
          question_types: selectedTypes.value,
          question_ids: questionIds.length > 0 ? questionIds : undefined,
          question_count: questionIds.length > 0 ? questionIds.length : undefined,
        }),
      )
      if (!session?.id) {
        safeShowToast('练习初始化失败，请重试')
        return null
      }
      readyPracticeId.value = session.id
      return session.id
    } catch (error: any) {
      if (!(error instanceof RequestError)) {
        safeShowToast(describeFailure(error, '初始化练习失败'))
      }
      return null
    } finally {
      isStarting.value = false
    }
  }

  return {
    ...config,
    viewMode,
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
    isLoadingKp,
    isLoadingReady,
    activeJobId,
    activeJob,
    isJobInFlight,
    jobProgressText,
    jobProgressPercent,
    readyPracticeId,
    readyPracticeTitle,
    readyAvailableCount,
    readyCoveredKpCount,
    readyPendingCount,
    generate,
    applyCompletedJob,
    clearActiveJob,
    attachActiveJobForScope,
    hasScopeActiveJob,
    reconfig,
    loadScopeKnowledgePoints,
    loadBatchQuestions,
    loadExistingQuestions,
    resolvePracticeForReadyCard,
    removeQuestion,
  }
}
