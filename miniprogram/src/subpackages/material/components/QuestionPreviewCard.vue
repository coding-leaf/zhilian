<template>
  <view class="paper-card question-card">
    <view class="q-header">
      <text class="q-num">第 {{ index + 1 }} 题</text>
      <view class="q-meta-badges">
        <text class="q-type">{{ typeLabel }}</text>
        <text v-if="question.difficulty" class="q-diff">难度 {{ question.difficulty }}</text>
      </view>
    </view>

    <text class="q-stem">{{ question.stem }}</text>

    <view v-if="question.options && question.options.length" class="q-options">
      <view
        v-for="(option, optIdx) in question.options"
        :key="option.key || optIdx"
        class="option-item"
      >
        <text class="option-text">{{ optionDisplayText(option, optIdx) }}</text>
      </view>
    </view>

    <view v-if="question.source_quote" class="source-box">
      <text class="source-tag">讲义依据切片</text>
      <text class="source-text">{{ question.source_quote }}</text>
    </view>

    <view class="card-actions">
      <button class="remove-btn" @tap="emit('remove', question)">剔除本题</button>
      <button class="regen-btn" :disabled="disabled" @tap="emit('regenerate', question)">
        重新生成
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QuestionItem } from '@/types'
import { optionDisplayText, questionTypeLabel } from '@/api'

const props = defineProps<{
  question: QuestionItem
  index: number
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'remove', question: QuestionItem): void
  (e: 'regenerate', question: QuestionItem): void
}>()

const typeLabel = computed(() => questionTypeLabel(props.question.type))
</script>

<style lang="scss" scoped>
.question-card { padding: 32rpx; margin-bottom: 24rpx; }
.q-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16rpx; }
.q-num { font-size: 26rpx; font-weight: 600; color: var(--color-academic-blue); }
.q-meta-badges { display: flex; gap: 12rpx; }
.q-type, .q-diff { font-size: 22rpx; background: var(--color-surface-muted); color: var(--color-ink-subtle); padding: 4rpx 12rpx; border-radius: 4rpx; }
.q-stem { display: block; font-size: 30rpx; color: var(--color-ink-primary); line-height: 1.6; font-weight: 500; margin-bottom: 20rpx; }
.option-item { display: flex; padding: 12rpx 0; font-size: 28rpx; color: var(--color-ink-body); }
.option-text { flex: 1; }
.source-box { margin-top: 20rpx; padding: 16rpx 20rpx; background: var(--color-surface-subtle); border-left: 4rpx solid var(--color-academic-blue); border-radius: 4rpx; }
.source-tag { font-size: 22rpx; font-weight: 600; color: var(--color-academic-blue); display: block; margin-bottom: 4rpx; }
.source-text { font-size: 24rpx; color: var(--color-ink-subtle); line-height: 1.5; }
.card-actions { display: flex; gap: 16rpx; margin-top: 20rpx; padding-top: 16rpx; border-top: 1px dashed var(--color-paper-border); }
.remove-btn, .regen-btn { flex: 1; height: 64rpx; font-size: 24rpx; border-radius: 8rpx; display: flex; align-items: center; justify-content: center; }
.remove-btn { background: var(--color-surface-muted); color: var(--color-ink-secondary); }
.regen-btn { background: var(--color-blue-bg); color: var(--color-academic-blue); }
</style>
