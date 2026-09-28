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
        <text class="option-index">{{ option.key || String.fromCharCode(65 + optIdx) }}.</text>
        <text class="option-text">{{ option.content }}</text>
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
import { questionTypeLabel } from '@/api'

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
@import '../questions.scss';
</style>
