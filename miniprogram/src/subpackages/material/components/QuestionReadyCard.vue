<template>
  <view class="paper-card ready-card">
    <view v-if="isLoading" class="ready-loading">
      <text class="ready-desc">正在同步试卷状态...</text>
    </view>

    <template v-else-if="availableCount > 0">
      <view class="ready-badge">试卷已就绪</view>
      <text class="ready-title">{{ practiceTitle || '专项练习卷' }}</text>
      <text class="ready-summary">
        已为你准备好 {{ availableCount }} 道题目 · 覆盖 {{ coveredKpCount }} 个考点
      </text>

      <text v-if="pendingNote" class="ready-hint">{{ pendingNote }}</text>

      <button
        class="paper-btn-primary ready-start-btn"
        :loading="isStarting"
        :disabled="!canStart || isStarting"
        @tap="emit('start')"
      >
        立即开始作答
      </button>

      <view class="ready-secondary-row">
        <button class="ready-secondary-btn" @tap="emit('go-bank')">前往我的题库</button>
        <button class="ready-secondary-btn" @tap="emit('reconfig')">重新组卷</button>
      </view>
    </template>

    <template v-else>
      <view class="ready-badge ready-badge-empty">暂未生成可用题目</view>
      <text class="ready-title">需要调整出题配置</text>
      <text class="ready-desc">
        {{
          pendingReviewCount > 0
            ? `本批 ${pendingReviewCount} 道题目暂待审核，建议调整考点或难度后重新出题。`
            : '当前范围暂未生成可用题目，请调整考点或题型后重试。'
        }}
      </text>
      <button class="paper-btn-primary ready-start-btn" @tap="emit('reconfig')">
        重新组卷
      </button>
      <view class="ready-secondary-row">
        <button class="ready-secondary-btn" @tap="emit('go-bank')">前往我的题库</button>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  availableCount: number
  coveredKpCount: number
  pendingReviewCount: number
  missingKpCount: number
  practiceTitle?: string
  isLoading?: boolean
  isStarting?: boolean
  canStart: boolean
}>()

const emit = defineEmits<{
  (e: 'start'): void
  (e: 'go-bank'): void
  (e: 'reconfig'): void
}>()

const pendingNote = computed(() => {
  if (props.pendingReviewCount > 0) {
    return `另有 ${props.pendingReviewCount} 道题目待审核，可随时在「我的题库」查看，不影响当前作答。`
  }
  if (props.missingKpCount > 0) {
    return `有 ${props.missingKpCount} 个所选考点暂未出题，不影响当前已就绪题目的作答。`
  }
  return ''
})
</script>

<style lang="scss" scoped>
@import '../questions.scss';
</style>
