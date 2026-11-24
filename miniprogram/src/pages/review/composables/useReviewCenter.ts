import { computed, ref } from 'vue'
import {
  MAX_PRACTICE_QUESTIONS,
  apiCreatePractice,
  apiGetKnowledgePointDetail,
  apiGetMasteryOverview,
  apiListWrongRecords,
  apiMarkWrongRecordMastered,
} from '@/api'
import {
  buildWrongGroupOptions,
  recordsInGroup,
  resolveRegenerateScope,
  type WrongGroupOption,
} from '@/api/adapters/wrong'
import { isQuestionJobActive, useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useFolderStore } from '@/stores/folder'
import { usePracticeStore } from '@/stores/practice'
import type {
  KnowledgeMasterySummary,
  PracticeSummary,
  UserMasteryOverview,
  WrongRecordItem,
} from '@/types'
import { safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import { startWrongRegenerateJob } from '@/utils/questionGeneration'
import { describeFailure, RequestError } from '@/utils/requestError'
import {
  groupKnowledgePointIds,
  hasScope,
  isResumeable,
  mergeMasteryPoints,
  recordRegenerateScope,
  type ReviewSegment,
} from '../reviewView'

const formatErrorMessage = (error: unknown, fallback: string): string => {
  if (error instanceof RequestError) return error.userMessage
  if (
    error &&
    typeof error === 'object' &&
    'message' in error &&
    typeof (error as { message?: unknown }).message === 'string'
  ) {
    return (error as { message: string }).message || fallback
  }
  return fallback
}

const PAGE_SIZE = 50
const MAX_PAGES = 6

export function useReviewCenter() {
  const practiceStore = usePracticeStore()
  const folderStore = useFolderStore()
  const backgroundTaskStore = useBackgroundTaskStore()

  const activeTab = ref<ReviewSegment>('mastery')
  const selectedFolderId = ref<string>('all')

  const masteryOverview = ref<UserMasteryOverview | null>(null)
  const masteryLoading = ref(false)
  const masteryError = ref('')

  const wrongRecords = ref<WrongRecordItem[]>([])
  const groupOptions = ref<WrongGroupOption[]>([])
  const selectedGroupKey = ref('')
  const isLoadingWrongs = ref(false)
  const wrongError = ref('')
  const selectedWrongIds = ref<string[]>([])
  const markingWrongIds = ref<string[]>([])

  const practices = ref<PracticeSummary[]>([])
  const isLoadingPractices = ref(false)
  const practiceError = ref('')

  const isDispatchingRegenerate = ref(false)
  const isGenerating = computed(
    () =>
      isDispatchingRegenerate.value ||
      Array.from(backgroundTaskStore.questionJobs.values()).some(
        (job) => isQuestionJobActive(job) && job.source_type === 'wrong_record',
      ),
  )
  const bankDirty = ref(false)

  let inFlightRefresh: Promise<void> | null = null

  const sortedMasteryPoints = computed(() => mergeMasteryPoints(masteryOverview.value))
  const weakMasteryPoints = computed(() =>
    sortedMasteryPoints.value.filter((item) => item.level === 'weak'),
  )
  const masteredCount = computed(() => wrongRecords.value.filter((item) => item.is_mastered).length)
  const pendingCount = computed(() => wrongRecords.value.filter((item) => !item.is_mastered).length)
  const activeGroup = computed<WrongGroupOption | null>(
    () => groupOptions.value.find((option) => option.key === selectedGroupKey.value) || null,
  )
  const needsGroupChoice = computed(() => groupOptions.value.length > 1 && !activeGroup.value)
  const visibleRecords = computed(() => {
    if (!activeGroup.value) return wrongRecords.value
    return recordsInGroup(wrongRecords.value, activeGroup.value)
  })
  const activeKpIds = computed(() => groupKnowledgePointIds(visibleRecords.value, activeGroup.value))
  const activeScopeReady = computed(() => {
    const scope = resolveRegenerateScope(activeGroup.value)
    return Boolean(scope && hasScope(scope))
  })
  const topErrorBanner = computed(
    () => masteryError.value || wrongError.value || practiceError.value || '',
  )

  const loadMastery = async () => {
    masteryLoading.value = true
    masteryError.value = ''
    try {
      masteryOverview.value = await apiGetMasteryOverview(selectedFolderId.value)
    } catch (error) {
      console.error('Failed to load mastery overview', error)
      masteryError.value = describeFailure(error, '掌握度总览加载失败，请重试')
    } finally {
      masteryLoading.value = false
    }
  }

  const loadWrongs = async () => {
    isLoadingWrongs.value = true
    wrongError.value = ''
    try {
      const collected: WrongRecordItem[] = []
      let total = 0
      for (let page = 1; page <= MAX_PAGES; page += 1) {
        const res = await apiListWrongRecords({ page, page_size: PAGE_SIZE })
        collected.push(...(res.items || []))
        total = res.total ?? collected.length
        if (page === 1) {
          groupOptions.value = buildWrongGroupOptions(res.groups || [])
        }
        if (collected.length >= total) break
      }
      wrongRecords.value = collected
      const validIds = new Set(collected.filter((r) => !r.is_mastered).map((r) => r.id))
      selectedWrongIds.value = selectedWrongIds.value.filter((id) => validIds.has(id))
      if (groupOptions.value.length === 1) {
        selectedGroupKey.value = groupOptions.value[0].key
      } else if (!groupOptions.value.some((option) => option.key === selectedGroupKey.value)) {
        selectedGroupKey.value = ''
      }
    } catch (error) {
      console.error('Failed to load wrong records', error)
      wrongError.value = describeFailure(error, '错题本加载失败，请重试')
    } finally {
      isLoadingWrongs.value = false
    }
  }

  const loadPractices = async () => {
    isLoadingPractices.value = true
    practiceError.value = ''
    try {
      practices.value = await practiceStore.loadPractices(undefined, 20)
    } catch (error) {
      console.error('Failed to load practices', error)
      practiceError.value = describeFailure(error, '练习记录加载失败，请重试')
    } finally {
      isLoadingPractices.value = false
    }
  }

  const refreshAll = async (options?: {
    fromShow?: boolean
    refreshBank?: () => Promise<void>
  }) => {
    if (inFlightRefresh) {
      await inFlightRefresh
      return
    }
    inFlightRefresh = (async () => {
      try {
        await Promise.all([
          folderStore.loadFolders(),
          backgroundTaskStore.refreshActiveTasks(),
          loadMastery(),
          loadWrongs(),
          loadPractices(),
          activeTab.value === 'bank' && options?.refreshBank
            ? options.refreshBank().then(() => { bankDirty.value = false })
            : Promise.resolve(),
        ])
        if (options?.fromShow && activeTab.value !== 'bank') {
          bankDirty.value = true
        }
      } finally {
        inFlightRefresh = null
      }
    })()
    await inFlightRefresh
  }

  const selectFolderFilter = async (folderId: string) => {
    selectedFolderId.value = folderId
    await loadMastery()
  }

  const switchTab = async (tab: ReviewSegment, refreshBank?: () => Promise<void>) => {
    activeTab.value = tab
    if (tab === 'bank' && bankDirty.value) {
      bankDirty.value = false
      if (refreshBank) await refreshBank()
    }
  }

  const navigateToSession = (practiceId: string) => {
    uni.navigateTo({
      url: `/subpackages/practice/pages/session/index?practice_id=${practiceId}`,
      fail: () => safeShowToast('打开练习失败，请重试'),
    })
  }

  const openPractice = (practice: PracticeSummary) => {
    if (isResumeable(practice)) {
      navigateToSession(practice.id)
      return
    }
    uni.navigateTo({
      url: `/subpackages/report/pages/detail/index?practice_id=${practice.id}`,
      fail: () => safeShowToast('打开结果页失败，请重试'),
    })
  }

  const resolvePointScope = async (
    kpId: string,
  ): Promise<{ folderId?: string; materialId?: string }> => {
    if (selectedFolderId.value && selectedFolderId.value !== 'all' && selectedFolderId.value !== '__none__') {
      return { folderId: selectedFolderId.value }
    }
    if (masteryOverview.value?.material_id) {
      return { materialId: masteryOverview.value.material_id }
    }
    const matchedWrong = wrongRecords.value.find((r) => r.knowledge_point_id === kpId)
    if (matchedWrong) {
      const fromWrong = recordRegenerateScope(matchedWrong)
      if (hasScope(fromWrong)) return fromWrong
    }
    try {
      const detail = await apiGetKnowledgePointDetail(kpId)
      if (detail.material_id) return { materialId: detail.material_id }
    } catch {
      // ignore fallback lookup failure
    }
    return {}
  }

  const handleBreakthroughPoint = async (point: KnowledgeMasterySummary) => {
    const scope = await resolvePointScope(point.knowledge_point_id)
    if (scope.materialId) {
      uni.navigateTo({
        url: `/subpackages/material/pages/questions/index?material_id=${encodeURIComponent(scope.materialId)}&kp_id=${encodeURIComponent(point.knowledge_point_id)}`,
        fail: () => safeShowToast('打开出题页失败，请重试'),
      })
      return
    }
    if (scope.folderId) {
      uni.navigateTo({
        url: `/subpackages/material/pages/questions/index?folder_id=${encodeURIComponent(scope.folderId)}&kp_id=${encodeURIComponent(point.knowledge_point_id)}`,
        fail: () => safeShowToast('打开出题页失败，请重试'),
      })
      return
    }
    try {
      const session = await withBlockingLoading('正在准备突破练习...', () =>
        apiCreatePractice({
          title: `突破 · ${point.knowledge_name}`,
          knowledge_point_ids: [point.knowledge_point_id],
          question_count: 5,
          mode: 'weak_points',
          source_type: 'weakness',
        }),
      )
      navigateToSession(session.id)
    } catch (error: unknown) {
      safeShowToast(formatErrorMessage(error, '暂未找到所属讲义，请从资料详情页发起出题'))
    }
  }

  const handleReinforceWeak = async () => {
    const kpIds = weakMasteryPoints.value.map((p) => p.knowledge_point_id).filter(Boolean)
    if (kpIds.length === 0) {
      safeShowToast('当前没有薄弱考点')
      return
    }
    const scope = await resolvePointScope(kpIds[0])
    try {
      const session = await withBlockingLoading('正在准备薄弱点练习...', () =>
        apiCreatePractice({
          title: '薄弱考点强化练习',
          ...(scope.folderId ? { folder_id: scope.folderId } : {}),
          knowledge_point_ids: kpIds,
          question_count: Math.min(10, Math.max(3, kpIds.length)),
          mode: 'weak_points',
          source_type: 'weakness',
        }),
      )
      navigateToSession(session.id)
    } catch (err: any) {
      if (scope.folderId || scope.materialId) {
        const jobKpIds = scope.folderId ? kpIds : [kpIds[0]]
        try {
          await backgroundTaskStore.startQuestionJob({
            folder_id: scope.folderId,
            material_id: scope.folderId ? undefined : scope.materialId,
            knowledge_point_ids: jobKpIds,
            count: Math.min(10, Math.max(3, jobKpIds.length)),
            auto_create_practice: true,
            practice_title: '薄弱考点强化练习',
            source_type: 'weakness',
          })
          safeShowToast('已在后台生成强化巩固卷，完成后顶部提醒')
          return
        } catch (jobErr: unknown) {
          safeShowToast(formatErrorMessage(jobErr, formatErrorMessage(err, '发起薄弱强化失败')))
          return
        }
      }
      safeShowToast(formatErrorMessage(err, '发起薄弱强化失败'))
    }
  }

  const runRegenerate = async (kpIds: string[], scope: { folderId?: string; materialId?: string }) => {
    if (isGenerating.value) return
    isDispatchingRegenerate.value = true
    try {
      await startWrongRegenerateJob({
        knowledgePointIds: kpIds,
        scope,
        practiceTitle: '错题巩固练习',
      })
      safeShowToast('已在后台生成错题巩固卷，完成后顶部提醒')
    } catch (error: unknown) {
      safeShowToast(formatErrorMessage(error, '生成失败'))
    } finally {
      isDispatchingRegenerate.value = false
    }
  }

  const handleBatchRegenerate = async () => {
    const scope = resolveRegenerateScope(activeGroup.value)
    if (!scope || !activeKpIds.value.length) return
    await runRegenerate(activeKpIds.value, scope)
  }

  const handleSingleKpPractice = async (record: WrongRecordItem) => {
    if (!record.knowledge_point_id) return
    const scope = recordRegenerateScope(record)
    if (!hasScope(scope)) {
      safeShowToast('该错题所属资料未归属课程，暂时无法出题')
      return
    }
    await runRegenerate([record.knowledge_point_id], scope)
  }

  const toggleWrongSelect = (recordId: string) => {
    if (selectedWrongIds.value.includes(recordId)) {
      selectedWrongIds.value = selectedWrongIds.value.filter((id) => id !== recordId)
    } else {
      selectedWrongIds.value = [...selectedWrongIds.value, recordId]
    }
  }

  const toggleSelectAllUnmastered = () => {
    const unmasteredIds = visibleRecords.value.filter((r) => !r.is_mastered).map((r) => r.id)
    if (unmasteredIds.length === 0) return
    const allSelected = unmasteredIds.every((id) => selectedWrongIds.value.includes(id))
    selectedWrongIds.value = allSelected ? [] : unmasteredIds
  }

  const handleMarkWrongMastered = async (record: WrongRecordItem) => {
    if (markingWrongIds.value.includes(record.id)) return
    markingWrongIds.value = [...markingWrongIds.value, record.id]
    try {
      await apiMarkWrongRecordMastered(record.id, true)
      safeShowToast('已标为已掌握', 'success')
      await Promise.all([loadWrongs(), loadMastery()])
    } catch (error: unknown) {
      safeShowToast(formatErrorMessage(error, '操作失败，请重试'))
    } finally {
      markingWrongIds.value = markingWrongIds.value.filter((id) => id !== record.id)
    }
  }

  const handleRestartSelectedWrongs = async () => {
    const pickedRecords = selectedWrongIds.value.length > 0
      ? visibleRecords.value.filter((r) => selectedWrongIds.value.includes(r.id))
      : visibleRecords.value.filter((r) => !r.is_mastered)

    if (pickedRecords.length === 0) {
      safeShowToast('请先选择待巩固的错题')
      return
    }
    const questionIds = Array.from(
      new Set(pickedRecords.map((r) => r.question_id).filter((id): id is string => Boolean(id))),
    ).slice(0, MAX_PRACTICE_QUESTIONS)

    if (questionIds.length > 0) {
      try {
        const session = await withBlockingLoading('正在发起错题重练...', () =>
          apiCreatePractice({
            title: `错题重练 · ${questionIds.length} 题`,
            question_ids: questionIds,
            question_count: questionIds.length,
            source_type: 'wrong_record',
          }),
        )
        navigateToSession(session.id)
        return
      } catch (error: unknown) {
        safeShowToast(formatErrorMessage(error, '创建重练失败，请重试'))
        return
      }
    }
    await handleBatchRegenerate()
  }

  return {
    activeTab,
    selectedFolderId,
    masteryOverview,
    masteryLoading,
    masteryError,
    sortedMasteryPoints,
    weakMasteryPoints,
    wrongRecords,
    groupOptions,
    selectedGroupKey,
    isLoadingWrongs,
    wrongError,
    selectedWrongIds,
    markingWrongIds,
    practices,
    isLoadingPractices,
    practiceError,
    isGenerating,
    bankDirty,
    masteredCount,
    pendingCount,
    activeGroup,
    needsGroupChoice,
    visibleRecords,
    activeKpIds,
    activeScopeReady,
    topErrorBanner,
    loadMastery,
    loadWrongs,
    loadPractices,
    refreshAll,
    selectFolderFilter,
    switchTab,
    openPractice,
    handleBreakthroughPoint,
    handleReinforceWeak,
    handleBatchRegenerate,
    handleSingleKpPractice,
    toggleWrongSelect,
    toggleSelectAllUnmastered,
    handleMarkWrongMastered,
    handleRestartSelectedWrongs,
  }
}
