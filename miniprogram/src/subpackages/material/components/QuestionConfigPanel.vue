<template>
  <view class="config-section">
    <view class="paper-card form-card">
      <view class="card-header-row">
        <text class="card-label">1. 考点范围 ({{ selectedKpIds.length }} 已选)</text>
        <text class="select-all-btn" @tap="emit('toggle-select-all')">
          {{ isAllKpSelected ? '取消全选' : '全部全选' }}
        </text>
      </view>

      <view v-if="availableKpList.length > 0" class="kp-chips-group">
        <view
          v-for="kp in availableKpList"
          :key="kp.id"
          :class="['kp-chip', isKpSelected(kp.id) ? 'active' : '']"
          @tap="emit('toggle-kp', kp.id)"
        >
          <text class="kp-chip-text">{{ kp.name }}</text>
          <view v-if="isKpSelected(kp.id)" class="chip-check-mark" />
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
          :class="['type-chip', isTypeSelected(type.value) ? 'active' : '']"
          @tap="emit('toggle-type', type.value)"
        >
          <text class="type-chip-text">{{ type.label }}</text>
          <view v-if="isTypeSelected(type.value)" class="chip-check-mark" />
        </view>
      </view>
    </view>

    <view class="paper-card form-card">
      <text class="card-label">3. 题量与难度设置</text>

      <view class="setting-row">
        <text class="setting-title">题目数量：{{ questionCount }} 题</text>
        <slider
          :value="questionCount"
          :min="1"
          :max="15"
          :step="1"
          :active-color="sliderActiveColor"
          :block-size="20"
          @change="onCountChange"
        />
      </view>

      <view class="setting-row">
        <text class="setting-title">
          难度等级：{{ difficultyLabel }} ({{ difficulty }}/5)
        </text>
        <slider
          :value="difficulty"
          :min="1"
          :max="5"
          :step="1"
          :active-color="sliderActiveColor"
          :block-size="20"
          @change="onDifficultyChange"
        />
      </view>

      <view v-if="plannedCount > questionCount" class="notice-box">
        <text class="notice-text">
          已选 {{ selectedKpIds.length }} 个考点，预计题量将调整为 {{ plannedCount }} 题以覆盖全部考点。
        </text>
      </view>
    </view>

    <view class="config-action-bar">
      <button
        class="paper-btn-primary full-btn"
        :loading="isGenerating"
        :disabled="selectedKpIds.length === 0 || isGenerating"
        @tap="emit('generate')"
      >
        {{ isGenerating ? 'AI 正在组卷中...' : `一键智能出题 (${selectedKpIds.length} 考点)` }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QuestionType } from '@/types'
import type { KnowledgePointOption } from '../composables/useComposeConfig'

const props = defineProps<{
  availableKpList: KnowledgePointOption[]
  selectedKpIds: string[]
  selectedTypes: QuestionType[]
  questionCount: number
  difficulty: number
  plannedCount: number
  isAllKpSelected: boolean
  isLoadingKp: boolean
  isGenerating: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle-select-all'): void
  (e: 'toggle-kp', id: string): void
  (e: 'toggle-type', type: QuestionType): void
  (e: 'update:questionCount', value: number): void
  (e: 'update:difficulty', value: number): void
  (e: 'generate'): void
}>()

const sliderActiveColor = '#1E3A8A'

const typeOptions: Array<{ label: string; value: QuestionType }> = [
  { label: '单项选择', value: 'single_choice' },
  { label: '多项选择', value: 'multiple_choice' },
  { label: '判断正误', value: 'true_false' },
  { label: '填空题', value: 'fill_in_blank' },
  { label: '名词解释', value: 'term_explanation' },
  { label: '简答/分析题', value: 'short_answer' },
  { label: '案例分析题', value: 'case_analysis' },
]

const isKpSelected = (id: string) => props.selectedKpIds.includes(id)
const isTypeSelected = (type: QuestionType) => props.selectedTypes.includes(type)

const difficultyLabel = computed(() => {
  switch (props.difficulty) {
    case 1: return '极简入门'
    case 2: return '基础巩固'
    case 3: return '进阶综合'
    case 4: return '高阶拓展'
    case 5: return '硬核挑战'
    default: return '适中'
  }
})

const onCountChange = (event: { detail: { value: number } }) => {
  emit('update:questionCount', event.detail.value)
}

const onDifficultyChange = (event: { detail: { value: number } }) => {
  emit('update:difficulty', event.detail.value)
}
</script>

<style lang="scss" scoped>
@import '../questions.scss';
</style>
