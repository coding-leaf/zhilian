<template>
  <view class="course-container">
    <MaterialCourseHeader
      :material="course.material.value"
      :can-start-parse="course.canStartParse.value"
      :is-parsing="course.isParsing.value"
      :parse-progress-text="course.parseProgressText.value"
      :generated-question-count="course.generatedQuestionCount.value"
      @start-parse="course.startParse"
      @review-generated="goToGeneratedQuestions"
    />

    <KnowledgePointList
      v-if="course.material.value?.status === 'ready'"
      :nodes="course.knowledgeNodes.value"
      @select="course.openPointDetail"
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
      :snippets="course.pointSnippets.value"
      :loading-snippets="course.isLoadingSnippets.value"
      :snippet-load-failed="course.snippetLoadFailed.value"
      @ask-coach="askAboutPoint"
    />

    <AiCoachDrawer
      v-model:visible="showCoach"
      :title="coachTitle"
      :context-text="coachContext"
      :material-id="course.materialId.value"
      :knowledge-point-id="coachPointId"
    />
  </view>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { onLoad, onPullDownRefresh } from '@dcloudio/uni-app'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import MaterialCourseHeader from '../../components/MaterialCourseHeader.vue'
import KnowledgePointList from '../../components/KnowledgePointList.vue'
import KnowledgeSnippetModal from '../../components/KnowledgeSnippetModal.vue'
import { useCourseDetail } from '../../composables/useCourseDetail'

const course = useCourseDetail()

const showCoach = ref(false)
const coachTitle = ref('讲义专属助教')
const coachContext = ref('')
const coachPointId = ref<string | undefined>()

onLoad(async (options) => {
  if (options?.id) {
    await course.initCourse(options.id)
  }
})

onPullDownRefresh(async () => {
  await course.loadDetail()
  uni.stopPullDownRefresh()
})

onUnmounted(() => {
  course.dispose()
})

const askAboutPoint = () => {
  const point = course.selectedPoint.value
  if (!point) return
  coachTitle.value = `考点答疑: ${point.name}`
  coachContext.value = `当前知识点：${point.name}。概要：${point.description || '无'}`
  coachPointId.value = point.id
  course.showPointModal.value = false
  showCoach.value = true
}

const openMaterialCoach = () => {
  coachTitle.value = `讲义助教: ${course.material.value?.title || '讲义答疑'}`
  coachContext.value = `当前讲义包含 ${course.knowledgeNodes.value.length} 个核心考点，涵盖知识树已建立。`
  coachPointId.value = undefined
  showCoach.value = true
}

const goToQuestionConfig = () => {
  if (!course.materialId.value) return
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?material_id=${course.materialId.value}`,
    fail: () => uni.showToast({ title: '打开出题页失败，请重试', icon: 'none' }),
  })
}

const goToGeneratedQuestions = () => {
  if (!course.materialId.value) return
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?material_id=${course.materialId.value}&view=generated`,
    fail: () => uni.showToast({ title: '打开已生成题目失败，请重试', icon: 'none' }),
  })
}
</script>

<style lang="scss" scoped>
@import '../../../../styles/common.scss';

.course-container {
  padding: 32rpx;
  padding-bottom: calc(180rpx + env(safe-area-inset-bottom));
  min-height: 100vh;
}

.action-coach-btn {
  width: 220rpx;
  height: 88rpx;
  background: var(--color-blue-bg);
  color: var(--color-academic-blue);
  font-size: 28rpx;
  font-weight: 600;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-generate-btn {
  flex: 1;
  height: 88rpx;
  font-size: 30rpx;
}
</style>
