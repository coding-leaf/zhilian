<template>
  <view class="questions-container">
    <BackgroundTaskBar
      :exclude-job-id="compose.activeJobId.value"
      disable-auto-navigate
      @open-task="handleOpenBackgroundTask"
    />

    <view class="page-header">
      <text class="page-title">{{ pageTitle }}</text>
      <text class="page-subtitle">{{ pageSubtitle }}</text>
    </view>

    <view v-if="compose.viewMode.value === 'generating'" class="paper-card job-progress-banner">
      <text class="job-banner-text">{{ compose.jobProgressText.value || '正在后台出题...' }}</text>
      <text class="job-hint-text">可随时离开，完成后顶部提醒</text>
      <view class="job-progress-track">
        <view class="job-progress-fill" :style="{ width: `${compose.jobProgressPercent.value}%` }" />
      </view>
      <view class="job-banner-actions">
        <button v-if="compose.scope.value.materialId" class="job-nav-btn" @tap="goBrowseMaterial">
          先去浏览讲义
        </button>
        <button class="job-nav-btn job-nav-secondary" @tap="goToWorkbench">
          返回工作台
        </button>
      </view>
    </view>

    <QuestionReadyCard
      v-else-if="compose.viewMode.value === 'ready'"
      :available-count="compose.readyAvailableCount.value"
      :covered-kp-count="compose.readyCoveredKpCount.value"
      :pending-review-count="compose.readyPendingCount.value"
      :missing-kp-count="compose.coverage.value.missing.length"
      :practice-title="compose.readyPracticeTitle.value"
      :is-loading="compose.isLoadingReady.value"
      :is-starting="compose.isStarting.value"
      :can-start="compose.canStart.value"
      @start="handleStartPractice"
      @go-bank="goToReviewBank"
      @reconfig="compose.reconfig"
    />

    <QuestionConfigPanel
      v-else
      :available-kp-list="compose.availableKpList.value"
      :kp-groups="compose.kpGroups.value"
      :selected-kp-ids="compose.selectedKpIds.value"
      :effective-kp-count="compose.effectiveKpIds.value.length"
      :compose-mode="compose.composeMode.value"
      :selected-types="compose.selectedTypes.value"
      :question-count="compose.questionCount.value"
      :difficulty="compose.difficulty.value"
      :planned-count="compose.plannedCount.value"
      :exceeds-practice-limit="compose.exceedsPracticeLimit.value"
      :is-all-kp-selected="compose.isAllKpSelected.value"
      :is-loading-kp="compose.isLoadingKp.value"
      :is-generating="compose.isGenerating.value"
      :is-job-in-flight="compose.isJobInFlight.value"
      @open-picker="showKpDrawer = true"
      @toggle-select-all="compose.toggleSelectAllKp"
      @toggle-type="compose.toggleType"
      @update:compose-mode="compose.setComposeMode"
      @update:question-count="compose.questionCount.value = $event"
      @update:difficulty="compose.difficulty.value = $event"
      @generate="handleGenerate"
    />

    <KnowledgePointPickerDrawer
      v-model:visible="showKpDrawer"
      :groups="compose.kpGroups.value"
      :selected-ids="compose.selectedKpIds.value"
      :is-all-selected="compose.isAllKpSelected.value"
      @toggle-kp="compose.toggleKp"
      @toggle-group="compose.toggleKpGroup"
      @toggle-select-all="compose.toggleSelectAllKp"
    />
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import BackgroundTaskBar from '@/components/BackgroundTaskBar.vue'
import { useBackgroundTaskStore, type BackgroundTaskItem } from '@/stores/backgroundTask'
import { safeShowToast } from '@/utils/loadingGuard'
import { describeFailure, RequestError } from '@/utils/requestError'
import KnowledgePointPickerDrawer from '../../components/KnowledgePointPickerDrawer.vue'
import QuestionConfigPanel from '../../components/QuestionConfigPanel.vue'
import QuestionReadyCard from '../../components/QuestionReadyCard.vue'
import { useQuestionCompose } from '../../composables/useQuestionCompose'

const taskStore = useBackgroundTaskStore()
const compose = useQuestionCompose()
const showKpDrawer = ref(false)

const pageTitle = computed(() => {
  if (compose.viewMode.value === 'generating') return '正在后台智能出题'
  if (compose.viewMode.value === 'ready') return '试卷已就绪'
  return '智能组卷与出题配置'
})

const pageSubtitle = computed(() => {
  if (compose.viewMode.value === 'generating') return '可随时离开继续浏览，完成后顶部提醒'
  if (compose.viewMode.value === 'ready') return '确认即可直接进入答题，也可前往我的题库查看'
  return '勾选考点、指定题型与难度，提交后台非阻塞出题'
})

watch(
  () => compose.activeJob.value?.status,
  async (status) => {
    const job = compose.activeJob.value
    if (!job) return
    if (status === 'completed') {
      const count = await compose.applyCompletedJob(job)
      if (count > 0) safeShowToast(`试卷已就绪（${count} 题）`, 'success')
    } else if (status === 'failed') {
      safeShowToast(job.error_message || '后台出题失败，请重试')
      compose.clearActiveJob()
      compose.viewMode.value = 'config'
    }
  },
)

onLoad(async (options) => {
  const scopeOptions = { folderId: options?.folder_id, materialId: options?.material_id }
  if (scopeOptions.folderId) compose.setScope({ folderId: scopeOptions.folderId })
  else if (scopeOptions.materialId) compose.setScope({ materialId: scopeOptions.materialId })

  if (options?.view === 'generated') {
    compose.viewMode.value = 'ready'
    compose.isLoadingReady.value = true
  } else if (compose.hasScopeActiveJob(scopeOptions)) {
    await compose.attachActiveJobForScope()
  }

  await compose.loadScopeKnowledgePoints({ ...scopeOptions, preselectedKpId: options?.kp_id })

  if (options?.view === 'generated') {
    try {
      if (options?.batch_id) await loadGeneratedBatch(options.batch_id)
      else if (options?.material_id) await loadGeneratedQuestions(options.material_id)
    } finally {
      compose.isLoadingReady.value = false
    }
  } else {
    await taskStore.refreshActiveTasks()
    await compose.attachActiveJobForScope()
  }
})

onShow(async () => {
  await compose.attachActiveJobForScope()
})

const loadGeneratedBatch = async (batchId: string) => {
  try {
    const count = await compose.loadBatchQuestions(batchId)
    if (count === 0) {
      compose.viewMode.value = 'ready'
      safeShowToast('该批次暂无可用题目')
    }
  } catch (error: any) {
    if (!(error instanceof RequestError)) safeShowToast(describeFailure(error, '加载生成题目失败'))
  }
}

const loadGeneratedQuestions = async (materialId: string) => {
  try {
    const count = await compose.loadExistingQuestions(materialId)
    if (count === 0) {
      compose.viewMode.value = 'config'
      safeShowToast('该讲义暂无可用题目')
    }
  } catch (error: any) {
    if (!(error instanceof RequestError)) safeShowToast(describeFailure(error, '已生成题目加载失败'))
  }
}

const navigateToSession = (practiceId: string) => {
  uni.navigateTo({
    url: `/subpackages/practice/pages/session/index?practice_id=${encodeURIComponent(practiceId)}`,
    fail: () => safeShowToast('打开练习失败，请重试'),
  })
}

const handleOpenBackgroundTask = async (task: BackgroundTaskItem) => {
  if (task.kind === 'material_parse' && task.materialId) {
    uni.navigateTo({
      url: `/subpackages/material/pages/course/index?id=${task.materialId}`,
      fail: () => safeShowToast('打开讲义详情失败'),
    })
    return
  }
  if (task.kind !== 'question_job') return
  if (task.resultPracticeId) return navigateToSession(task.resultPracticeId)
  if (task.batchId) {
    compose.viewMode.value = 'ready'
    compose.isLoadingReady.value = true
    try {
      await loadGeneratedBatch(task.batchId)
    } finally {
      compose.isLoadingReady.value = false
    }
    return
  }
  goToReviewBank()
}

const handleGenerate = async () => {
  const generatedCount = await compose.generate()
  if (generatedCount > 0) safeShowToast(`试卷已就绪（${generatedCount} 题）`, 'success')
}

const goBrowseMaterial = () => {
  const materialId = compose.scope.value.materialId
  if (!materialId) return
  uni.navigateTo({
    url: `/subpackages/material/pages/course/index?id=${materialId}`,
    fail: () => safeShowToast('打开讲义详情失败'),
  })
}

const goToWorkbench = () => {
  uni.switchTab({ url: '/pages/index/index', fail: () => safeShowToast('返回工作台失败') })
}

const goToReviewBank = () => {
  uni.switchTab({ url: '/pages/review/index', fail: () => safeShowToast('打开我的题库失败') })
}

const handleStartPractice = async () => {
  const practiceId = await compose.resolvePracticeForReadyCard()
  if (practiceId) navigateToSession(practiceId)
}
</script>

<style lang="scss" scoped>
@import '../../questions.scss';
</style>
