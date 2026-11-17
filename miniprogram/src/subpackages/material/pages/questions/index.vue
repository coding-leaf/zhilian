<template>
  <view class="questions-container">
    <view class="page-header">
      <text class="page-title">{{ isConfigMode ? '智能组卷与出题配置' : '核对生成题目' }}</text>
      <text class="page-subtitle">
        {{ isConfigMode
          ? '勾选考点、指定题型与难度，生成针对性批次练习'
          : `已生成 ${compose.remainingQuestions.value.length} 道题目，核对无误后开始作答` }}
      </text>
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
      @toggle-select-all="compose.toggleSelectAllKp"
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
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { MAX_PRACTICE_QUESTIONS } from '@/api'
import { useMaterialStore } from '@/stores/material'
import { usePracticeStore } from '@/stores/practice'
import { useFolderStore } from '@/stores/folder'
import { flattenKnowledgeTree } from '@/utils/knowledgeTree'
import QuestionConfigPanel from '../../components/QuestionConfigPanel.vue'
import QuestionPreviewPanel from '../../components/QuestionPreviewPanel.vue'
import { useQuestionCompose } from '../../composables/useQuestionCompose'

const materialStore = useMaterialStore()
const practiceStore = usePracticeStore()
const folderStore = useFolderStore()
const compose = useQuestionCompose()

const isConfigMode = ref(true)
const isLoadingKp = ref(false)

onLoad(async (options) => {
  if (options?.folder_id) {
    compose.setScope({ folderId: options.folder_id })
    await loadKpFromFolder(options.folder_id)
  } else if (options?.material_id) {
    compose.setScope({ materialId: options.material_id })
    await loadKpFromMaterial(options.material_id)
  }
  if (options?.view === 'generated' && options?.material_id) {
    await loadGeneratedQuestions(options.material_id)
  }
})

const loadKpFromFolder = async (folderId: string) => {
  isLoadingKp.value = true
  uni.showLoading({ title: '加载课程考点...' })
  try {
    const res = await folderStore.loadFolderKnowledgePoints(folderId)
    const list = (res.groups || []).flatMap((group) => group.knowledge_points || [])
    compose.setKnowledgePoints(compose.flattenKnowledgePoints(list))
  } finally {
    uni.hideLoading()
    isLoadingKp.value = false
  }
}

const loadKpFromMaterial = async (materialId: string) => {
  isLoadingKp.value = true
  uni.showLoading({ title: '加载讲义考点...' })
  try {
    const tree = await materialStore.loadKnowledgeTree(materialId)
    const nodes = flattenKnowledgeTree(tree?.nodes)
    compose.setKnowledgePoints(nodes.map((node) => ({ id: node.id, name: node.name })))
  } finally {
    uni.hideLoading()
    isLoadingKp.value = false
  }
}

/** 「继续核对已生成题目」入口：直接进入核对视图，无数据时留在配置区并提示。 */
const loadGeneratedQuestions = async (materialId: string) => {
  uni.showLoading({ title: '加载已生成题目...' })
  try {
    const count = await compose.loadExistingQuestions(materialId)
    if (count > 0) {
      isConfigMode.value = false
      return
    }
    uni.showToast({ title: '该讲义暂无已生成题目', icon: 'none' })
  } catch (error: any) {
    uni.showToast({ title: error?.message || '已生成题目加载失败', icon: 'none' })
  } finally {
    uni.hideLoading()
  }
}

/** 生成成功才切到核对视图；失败与零合格题留在配置区。 */
const handleGenerate = async () => {
  const generatedCount = await compose.generate()
  if (generatedCount > 0) {
    isConfigMode.value = false
  }
}

const handleStartPractice = async () => {
  if (!compose.canStart.value) {
    uni.showToast({ title: '请先补齐考点覆盖', icon: 'none' })
    return
  }
  compose.isStarting.value = true
  uni.showLoading({ title: '准备考场中...' })
  try {
    const questionIds = compose.remainingQuestions.value
      .map((question) => question.id)
      .slice(0, MAX_PRACTICE_QUESTIONS)
    const session = await practiceStore.initPractice(undefined, {
      title: compose.scope.value.folderId ? '课程针对性测验' : '讲义专题测验',
      folder_id: compose.scope.value.folderId,
      material_id: compose.scope.value.folderId ? undefined : compose.scope.value.materialId,
      knowledge_point_ids: compose.selectedKpIds.value,
      question_types: compose.selectedTypes.value,
      question_ids: questionIds.length > 0 ? questionIds : undefined,
      question_count: questionIds.length > 0 ? questionIds.length : undefined,
    })
    uni.hideLoading()
    if (!session?.id) {
      uni.showToast({ title: '练习初始化失败，请重试', icon: 'none' })
      return
    }
    uni.navigateTo({
      url: `/subpackages/practice/pages/session/index?practice_id=${session.id}`,
      fail: () => uni.showToast({ title: '打开练习失败，请重试', icon: 'none' }),
    })
  } catch (error: any) {
    uni.hideLoading()
    uni.showToast({ title: error?.message || '初始化练习失败', icon: 'none' })
  } finally {
    compose.isStarting.value = false
  }
}
</script>

<style lang="scss" scoped>
@import '../../questions.scss';
</style>
