<template>
  <view class="course-container">
    <BackgroundTaskBar disable-auto-navigate @open-task="handleOpenTask" />

    <MaterialCourseHeader
      :material="course.material.value"
      :can-start-parse="course.canStartParse.value"
      :is-parsing="course.isParsing.value"
      :is-parse-timed-out="course.isParseTimedOut.value"
      :is-refreshing="course.isRefreshing.value"
      :parse-progress-text="course.parseProgressText.value"
      :generated-question-count="course.generatedQuestionCount.value"
      @start-parse="course.startParse(false)"
      @reparse="course.confirmAndReparse"
      @reparse-direct="course.startParse(true)"
      @refresh="course.refreshParseProgress"
      @review-generated="goToGeneratedQuestions"
    />

    <KnowledgePointList
      v-if="course.material.value?.status === 'ready'"
      :nodes="course.knowledgeNodes.value"
      :mastery-map="course.masteryMap.value"
      @select="course.openPointDetail"
      @practice="goToPracticePoint"
    />

    <view v-if="course.material.value?.status === 'ready'" class="bottom-fixed-bar bottom-action-bar">
      <button class="action-coach-btn" @tap="openMaterialCoach">
        讲义助教
      </button>
      <button class="paper-btn-primary action-generate-btn" @tap="goToQuestionConfig">
        按知识点组卷出题
      </button>
    </view>

    <KnowledgeSnippetModal
      v-model:visible="course.showPointModal.value"
      :point="course.selectedPoint.value"
      :point-detail="course.selectedPointDetail.value"
      :point-hierarchy="course.pointHierarchy.value"
      :mastery-entry="selectedPointMastery"
      :snippets="course.pointSnippets.value"
      :loading-snippets="course.isLoadingSnippets.value"
      :snippet-load-failed="course.snippetLoadFailed.value"
      @ask-coach="askAboutPoint"
      @practice="practiceSelectedPoint"
    />

    <AiCoachDrawer
      v-model:visible="showCoach"
      :title="coachTitle"
      :context-text="coachContext"
      :material-id="coachPointId ? undefined : course.materialId.value"
      :knowledge-point-id="coachPointId"
    />
  </view>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref } from 'vue'
import { onLoad, onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import BackgroundTaskBar from '@/components/BackgroundTaskBar.vue'
import { useBackgroundTaskStore, type BackgroundTaskItem } from '@/stores/backgroundTask'
import { safeShowToast } from '@/utils/loadingGuard'
import type { KnowledgeTreeNode } from '@/types'
import MaterialCourseHeader from '../../components/MaterialCourseHeader.vue'
import KnowledgePointList from '../../components/KnowledgePointList.vue'
import KnowledgeSnippetModal from '../../components/KnowledgeSnippetModal.vue'
import { useCourseDetail } from '../../composables/useCourseDetail'
import { formatKpSummaryPreview } from '../../utils/courseStudy'

const course = useCourseDetail()
const taskStore = useBackgroundTaskStore()

const showCoach = ref(false)
const coachTitle = ref('讲义专属助教')
const coachContext = ref('')
const coachPointId = ref<string | undefined>()

const selectedPointMastery = computed(() => {
  const id = course.selectedPoint.value?.id
  return id ? course.masteryMap.value[id] ?? null : null
})

onLoad(async (options) => {
  if (options?.id) {
    await course.initCourse(options.id)
  }
})

onShow(() => {
  if (course.material.value?.status === 'ready') {
    void course.refreshMastery()
  } else if (!course.isLoading.value && course.materialId.value) {
    void course.loadDetail()
    void taskStore.refreshActiveTasks()
  }
})

onPullDownRefresh(async () => {
  await course.loadDetail()
  uni.stopPullDownRefresh()
})

onUnmounted(() => {
  course.dispose()
})

const handleOpenTask = (task: BackgroundTaskItem) => {
  if (task.kind === 'material_parse' && task.materialId) {
    if (task.materialId === course.materialId.value) {
      void course.loadDetail()
      return
    }
    uni.navigateTo({
      url: `/subpackages/material/pages/course/index?id=${task.materialId}`,
      fail: () => safeShowToast('打开讲义详情失败'),
    })
    return
  }
  if (task.kind !== 'question_job') return
  const query: string[] = ['view=generated']
  if (task.materialId) query.unshift(`material_id=${encodeURIComponent(task.materialId)}`)
  else if (task.folderId) query.unshift(`folder_id=${encodeURIComponent(task.folderId)}`)
  else {
    uni.switchTab({
      url: '/pages/review/index',
      fail: () => safeShowToast('跳转学情页失败'),
    })
    return
  }
  if (task.batchId) query.push(`batch_id=${encodeURIComponent(task.batchId)}`)
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?${query.join('&')}`,
    fail: () => safeShowToast('打开出题结果失败'),
  })
}

const askAboutPoint = async () => {
  const point = course.selectedPoint.value
  if (!point) return
  const summary = formatKpSummaryPreview(course.selectedPointDetail.value || point)
  coachTitle.value = `考点答疑: ${point.name}`
  coachContext.value = `当前考点：${point.name}。概要：${summary || '无'}`
  coachPointId.value = point.id
  course.showPointModal.value = false
  await nextTick()
  showCoach.value = true
}

const openMaterialCoach = () => {
  coachTitle.value = `讲义助教: ${course.material.value?.title || '讲义答疑'}`
  coachContext.value = `当前讲义包含 ${course.knowledgeNodes.value.length} 个核心考点，涵盖知识树已建立。`
  coachPointId.value = undefined
  showCoach.value = true
}

const goToPracticePoint = (point: KnowledgeTreeNode) => {
  if (!course.materialId.value || !point?.id) return
  course.showPointModal.value = false
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?material_id=${encodeURIComponent(course.materialId.value)}&kp_id=${encodeURIComponent(point.id)}`,
    fail: () => safeShowToast('打开出题页失败，请重试'),
  })
}

const practiceSelectedPoint = () => {
  if (!course.selectedPoint.value) return
  goToPracticePoint(course.selectedPoint.value)
}

const goToQuestionConfig = () => {
  if (!course.materialId.value) return
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?material_id=${course.materialId.value}`,
    fail: () => safeShowToast('打开出题页失败，请重试'),
  })
}

const goToGeneratedQuestions = () => {
  if (!course.materialId.value) return
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?material_id=${course.materialId.value}&view=generated`,
    fail: () => safeShowToast('打开已生成题目失败，请重试'),
  })
}
</script>

<style lang="scss" scoped>
@import '../../../../styles/common.scss';
@import '../../course.scss';
</style>
