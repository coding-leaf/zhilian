<template>
  <view class="questions-container">
    <BackgroundTaskBar disable-auto-navigate @open-task="handleOpenBackgroundTask" />

    <view class="page-header">
      <text class="page-title">{{ isConfigMode ? '智能组卷与出题配置' : '核对生成题目' }}</text>
      <text class="page-subtitle">
        {{ isConfigMode
          ? '勾选考点、指定题型与难度，提交后台非阻塞出题'
          : `已生成 ${compose.remainingQuestions.value.length} 道题目，核对答案与解析后开始作答` }}
      </text>
    </view>

    <view v-if="compose.isJobInFlight.value" class="paper-card job-progress-banner">
      <text class="job-banner-text">{{ compose.jobProgressText.value }}</text>
      <view class="job-progress-track">
        <view class="job-progress-fill" :style="{ width: `${compose.jobProgressPercent.value}%` }" />
      </view>
      <view class="job-banner-actions">
        <button
          v-if="compose.scope.value.materialId"
          class="job-nav-btn"
          @tap="goBrowseMaterial"
        >
          先去浏览讲义
        </button>
        <button class="job-nav-btn job-nav-secondary" @tap="goToWorkbench">
          返回工作台
        </button>
      </view>
    </view>

    <QuestionConfigPanel
      v-if="isConfigMode"
      :available-kp-list="compose.availableKpList.value"
      :selected-kp-ids="compose.selectedKpIds.value"
      :selected-types="compose.selectedTypes.value"
      :question-count="compose.questionCount.value"
      :difficulty="compose.difficulty.value"
      :planned-count="compose.plannedCount.value"
      :is-all-kp-selected="compose.isAllKpSelected.value"
      :is-loading-kp="isLoadingKp"
      :is-generating="compose.isGenerating.value"
      :is-job-in-flight="compose.isJobInFlight.value"
      @toggle-select-all="compose.toggleSelectAllKp"
      @toggle-group="compose.toggleKpGroup"
      @toggle-kp="compose.toggleKp"
      @toggle-type="compose.toggleType"
      @update:question-count="compose.questionCount.value = $event"
      @update:difficulty="compose.difficulty.value = $event"
      @generate="handleGenerate"
    />

    <QuestionPreviewPanel
      v-else
      :questions="compose.remainingQuestions.value"
      :generated-batch-notice="compose.generatedBatchNotice.value"
      :generation-notice="compose.generationNotice.value"
      :missing-count="compose.coverage.value.missing.length"
      :is-generating="compose.isGenerating.value"
      :is-job-in-flight="compose.isJobInFlight.value"
      :is-starting="compose.isStarting.value"
      :can-start="compose.canStart.value"
      @fill-gap="compose.fillCoverageGap"
      @remove="compose.removeQuestion"
      @regenerate="compose.regenerateQuestion"
      @reconfig="isConfigMode = true"
      @start="handleStartPractice"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { MAX_PRACTICE_QUESTIONS } from '@/api'
import BackgroundTaskBar from '@/components/BackgroundTaskBar.vue'
import { useBackgroundTaskStore, type BackgroundTaskItem } from '@/stores/backgroundTask'
import { useMaterialStore } from '@/stores/material'
import { usePracticeStore } from '@/stores/practice'
import { useFolderStore } from '@/stores/folder'
import { safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import { describeFailure, RequestError } from '@/utils/requestError'
import QuestionConfigPanel from '../../components/QuestionConfigPanel.vue'
import QuestionPreviewPanel from '../../components/QuestionPreviewPanel.vue'
import { useQuestionCompose } from '../../composables/useQuestionCompose'
import { flattenTreeWithParents } from '../../utils/courseStudy'

const materialStore = useMaterialStore()
const practiceStore = usePracticeStore()
const folderStore = useFolderStore()
const taskStore = useBackgroundTaskStore()
const compose = useQuestionCompose()

const isConfigMode = ref(true)
const isLoadingKp = ref(false)

watch(
  () => compose.activeJob.value?.status,
  async (status) => {
    const job = compose.activeJob.value
    if (!job) return
    if (status === 'completed') {
      const count = await compose.applyCompletedJob(job)
      if (count > 0) {
        isConfigMode.value = false
        safeShowToast(`已生成 ${count} 道题目`, 'success')
      }
    } else if (status === 'failed') {
      safeShowToast(job.error_message || '后台出题失败，请重试')
      compose.clearActiveJob()
    }
  },
)

onLoad(async (options) => {
  const preselectedKpId = options?.kp_id
  if (options?.folder_id) {
    compose.setScope({ folderId: options.folder_id })
    await loadKpFromFolder(options.folder_id, preselectedKpId)
  } else if (options?.material_id) {
    compose.setScope({ materialId: options.material_id })
    await loadKpFromMaterial(options.material_id, preselectedKpId)
  }
  if (options?.view === 'generated') {
    if (options?.batch_id) {
      await loadGeneratedBatch(options.batch_id)
    } else if (options?.material_id) {
      await loadGeneratedQuestions(options.material_id)
    }
  } else {
    await taskStore.refreshActiveTasks()
    compose.attachActiveJobForScope()
  }
})

onShow(() => {
  compose.attachActiveJobForScope()
})

const loadKpFromFolder = async (folderId: string, preselectedKpId?: string) => {
  isLoadingKp.value = true
  try {
    const res = await folderStore.loadFolderKnowledgePoints(folderId)
    const list = (res.groups || []).flatMap((group) =>
      compose.flattenKnowledgePoints(group.knowledge_points || [], {
        materialId: group.material_id,
        materialTitle: group.material_title,
      }),
    )
    compose.setKnowledgePoints(list, preselectedKpId)
  } finally {
    isLoadingKp.value = false
  }
}

const loadKpFromMaterial = async (materialId: string, preselectedKpId?: string) => {
  isLoadingKp.value = true
  try {
    const tree = await materialStore.loadKnowledgeTree(materialId)
    const nodes = flattenTreeWithParents(tree?.nodes)
    compose.setKnowledgePoints(
      nodes.map((node) => ({
        id: node.id,
        name: node.name,
        level: node.level,
        parent_id: node.parent_id ?? null,
        sort_order: node.sort_order ?? 0,
      })),
      preselectedKpId,
    )
  } finally {
    isLoadingKp.value = false
  }
}

const loadGeneratedBatch = async (batchId: string) => {
  try {
    const count = await withBlockingLoading('加载生成题目...', () =>
      compose.loadBatchQuestions(batchId),
    )
    if (count > 0) {
      isConfigMode.value = false
      return
    }
    safeShowToast('该批次暂无可用题目')
  } catch (error: any) {
    if (!(error instanceof RequestError)) {
      safeShowToast(describeFailure(error, '加载生成题目失败'))
    }
  }
}

/** 「继续核对已生成题目」入口：直接进入核对视图，无数据时留在配置区并提示。 */
const loadGeneratedQuestions = async (materialId: string) => {
  try {
    const count = await withBlockingLoading('加载已生成题目...', () =>
      compose.loadExistingQuestions(materialId),
    )
    if (count > 0) {
      isConfigMode.value = false
      return
    }
    safeShowToast('该讲义暂无已生成题目')
  } catch (error: any) {
    if (!(error instanceof RequestError)) {
      safeShowToast(describeFailure(error, '已生成题目加载失败'))
    }
  }
}

const handleOpenBackgroundTask = async (task: BackgroundTaskItem) => {
  if (task.kind === 'material_parse' && task.materialId) {
    uni.navigateTo({
      url: `/subpackages/material/pages/course/index?id=${task.materialId}`,
      fail: () => safeShowToast('打开讲义详情失败'),
    })
    return
  }
  if (task.kind === 'question_job' && task.batchId) {
    await loadGeneratedBatch(task.batchId)
  }
}

const handleGenerate = async () => {
  const generatedCount = await compose.generate()
  if (generatedCount > 0) {
    isConfigMode.value = false
    safeShowToast(`已生成 ${generatedCount} 道题目`, 'success')
  }
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
  uni.switchTab({
    url: '/pages/index/index',
    fail: () => safeShowToast('返回工作台失败'),
  })
}

const handleStartPractice = async () => {
  if (!compose.canStart.value) {
    safeShowToast('请先补齐考点覆盖')
    return
  }
  compose.isStarting.value = true
  try {
    const questionIds = compose.remainingQuestions.value
      .map((question) => question.id)
      .slice(0, MAX_PRACTICE_QUESTIONS)
    const session = await withBlockingLoading('准备考场中...', () =>
      practiceStore.initPractice(undefined, {
        title: compose.scope.value.folderId ? '课程针对性测验' : '讲义专题测验',
        folder_id: compose.scope.value.folderId,
        material_id: compose.scope.value.folderId ? undefined : compose.scope.value.materialId,
        knowledge_point_ids: compose.selectedKpIds.value,
        question_types: compose.selectedTypes.value,
        question_ids: questionIds.length > 0 ? questionIds : undefined,
        question_count: questionIds.length > 0 ? questionIds.length : undefined,
      }),
    )
    if (!session?.id) {
      safeShowToast('练习初始化失败，请重试')
      return
    }
    uni.navigateTo({
      url: `/subpackages/practice/pages/session/index?practice_id=${session.id}`,
      fail: () => safeShowToast('打开练习失败，请重试'),
    })
  } catch (error: any) {
    if (!(error instanceof RequestError)) {
      safeShowToast(describeFailure(error, '初始化练习失败'))
    }
  } finally {
    compose.isStarting.value = false
  }
}
</script>

<style lang="scss" scoped>
@import '../../questions.scss';
</style>
