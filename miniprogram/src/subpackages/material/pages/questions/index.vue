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

    <view v-if="isConfigMode" class="config-section">
      <view class="paper-card form-card">
        <view class="card-header-row">
          <text class="card-label">1. 考点范围 ({{ compose.selectedKpIds.value.length }} 已选)</text>
          <text class="select-all-btn" @tap="compose.toggleSelectAllKp">
            {{ compose.isAllKpSelected.value ? '取消全选' : '全部全选' }}
          </text>
        </view>

        <view v-if="compose.availableKpList.value.length > 0" class="kp-chips-group">
          <view
            v-for="kp in compose.availableKpList.value"
            :key="kp.id"
            :class="['kp-chip', compose.isKpSelected(kp.id) ? 'active' : '']"
            @tap="compose.toggleKp(kp.id)"
          >
            <text class="kp-chip-text">{{ kp.name }}</text>
            <text v-if="compose.isKpSelected(kp.id)" class="kp-check">✓</text>
          </view>
        </view>
        <view v-else class="notice-box">
          <text class="notice-text">
            {{ isLoadingKp ? '正在拉取考点列表...' : '当前范围暂无已解析考点，请先完成资料解析。' }}
          </text>
        </view>
      </view>

      <view class="paper-card form-card">
        <text class="card-label">2. 测验题型多选</text>
        <view class="type-chips-group">
          <view
            v-for="type in typeOptions"
            :key="type.value"
            :class="['type-chip', compose.isTypeSelected(type.value) ? 'active' : '']"
            @tap="compose.toggleType(type.value)"
          >
            <text class="type-chip-text">{{ type.label }}</text>
            <text v-if="compose.isTypeSelected(type.value)" class="type-check">✓</text>
          </view>
        </view>
      </view>

      <view class="paper-card form-card">
        <text class="card-label">3. 题量与难度设置</text>

        <view class="setting-row">
          <text class="setting-title">题目数量：{{ compose.questionCount.value }} 题</text>
          <slider
            :value="compose.questionCount.value"
            :min="1"
            :max="15"
            :step="1"
            active-color="#1E3A8A"
            :block-size="20"
            @change="onCountChange"
          />
        </view>

        <view class="setting-row">
          <text class="setting-title">
            难度等级：{{ difficultyText(compose.difficulty.value) }} ({{ compose.difficulty.value }}/5)
          </text>
          <slider
            :value="compose.difficulty.value"
            :min="1"
            :max="5"
            :step="1"
            active-color="#1E3A8A"
            :block-size="20"
            @change="onDifficultyChange"
          />
        </view>

        <view v-if="plannedCount > compose.questionCount.value" class="notice-box">
          <text class="notice-text">
            已选 {{ compose.selectedKpIds.value.length }} 个考点，预计题量将调整为 {{ plannedCount }} 题以覆盖全部考点。
          </text>
        </view>
      </view>

      <view class="config-action-bar">
        <button
          class="paper-btn-primary full-btn"
          :loading="compose.isGenerating.value"
          :disabled="compose.selectedKpIds.value.length === 0 || compose.isGenerating.value"
          @tap="compose.generate"
        >
          {{ compose.isGenerating.value ? 'AI 正在组卷中...' : `一键智能出题 (${compose.selectedKpIds.value.length} 考点)` }}
        </button>
      </view>
    </view>

    <view v-else class="preview-section">
      <view v-if="compose.generationNotice.value" class="notice-box">
        <text class="notice-text">{{ compose.generationNotice.value }}</text>
      </view>

      <view v-if="compose.coverage.value.missing.length > 0" class="gap-box">
        <text class="gap-text">
          仍有 {{ compose.coverage.value.missing.length }} 个已选考点没有合格题目覆盖，请补齐或调整考点后再开始作答。
        </text>
        <button class="gap-btn" :loading="compose.isGenerating.value" @tap="compose.fillCoverageGap">
          补齐缺失考点
        </button>
      </view>

      <view class="questions-list">
        <QuestionPreviewCard
          v-for="(question, idx) in compose.remainingQuestions.value"
          :key="question.id || idx"
          :question="question"
          :index="idx"
          :disabled="compose.isGenerating.value"
          @remove="compose.removeQuestion"
          @regenerate="compose.regenerateQuestion"
        />
        <view v-if="compose.remainingQuestions.value.length === 0" class="notice-box">
          <text class="notice-text">题目已全部剔除，请重新生成或返回调整配置。</text>
        </view>
      </view>

      <view class="bottom-action-bar">
        <button class="reconfig-btn" @tap="isConfigMode = true">重新调整</button>
        <button
          class="paper-btn-primary start-btn"
          :loading="compose.isStarting.value"
          :disabled="!compose.canStart.value"
          @tap="handleStartPractice"
        >
          开始作答 ({{ compose.remainingQuestions.value.length }} 题)
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useMaterialStore } from '@/stores/material'
import { usePracticeStore } from '@/stores/practice'
import { useFolderStore } from '@/stores/folder'
import type { QuestionType } from '@/types'
import QuestionPreviewCard from '../../components/QuestionPreviewCard.vue'
import { useQuestionCompose } from '../../composables/useQuestionCompose'

const materialStore = useMaterialStore()
const practiceStore = usePracticeStore()
const folderStore = useFolderStore()
const compose = useQuestionCompose()

const isConfigMode = ref<boolean>(true)
const isLoadingKp = ref<boolean>(false)

const typeOptions: Array<{ label: string; value: QuestionType }> = [
  { label: '单项选择', value: 'single_choice' },
  { label: '多项选择', value: 'multiple_choice' },
  { label: '判断正误', value: 'true_false' },
  { label: '填空题', value: 'fill_in_blank' },
  { label: '名词解释', value: 'term_explanation' },
  { label: '简答/分析题', value: 'short_answer' },
  { label: '案例分析题', value: 'case_analysis' },
]

const plannedCount = computed(() => compose.plannedCount.value)

onLoad(async (options) => {
  if (options?.folder_id) {
    compose.setScope({ folderId: options.folder_id })
    await loadKpFromFolder(options.folder_id)
  } else if (options?.material_id) {
    compose.setScope({ materialId: options.material_id })
    await loadKpFromMaterial(options.material_id)
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
    const list: Array<{ id: string; name: string }> = []
    const walk = (nodes: Array<{ id: string; name: string; children?: any[] }>) => {
      for (const node of nodes) {
        list.push({ id: node.id, name: node.name })
        if (node.children?.length) walk(node.children)
      }
    }
    if (tree?.nodes) walk(tree.nodes as any)
    compose.setKnowledgePoints(list)
  } finally {
    uni.hideLoading()
    isLoadingKp.value = false
  }
}

const onCountChange = (event: { detail: { value: number } }) => {
  compose.questionCount.value = event.detail.value
}

const onDifficultyChange = (event: { detail: { value: number } }) => {
  compose.difficulty.value = event.detail.value
}

const difficultyText = (level: number) => {
  switch (level) {
    case 1: return '极简入门'
    case 2: return '基础巩固'
    case 3: return '进阶综合'
    case 4: return '高阶拓展'
    case 5: return '硬核挑战'
    default: return '适中'
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
    const questionIds = compose.remainingQuestions.value.map((question) => question.id)
    const session = await practiceStore.initPractice(undefined, {
      title: compose.scope.value.folderId ? '课程针对性测验' : '讲义专题测验',
      folder_id: compose.scope.value.folderId,
      material_id: compose.scope.value.folderId ? undefined : compose.scope.value.materialId,
      knowledge_point_ids: compose.selectedKpIds.value,
      question_types: compose.selectedTypes.value,
      question_ids: questionIds.length > 0 ? questionIds : undefined,
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
