<template>
  <view class="preview-section">
    <view v-if="generatedBatchNotice" class="notice-box">
      <text class="notice-text">{{ generatedBatchNotice }}</text>
    </view>

    <view v-if="generationNotice" class="notice-box">
      <text class="notice-text">{{ generationNotice }}</text>
    </view>

    <view v-if="missingCount > 0" class="gap-box">
      <text class="gap-text">
        仍有 {{ missingCount }} 个已选考点没有合格题目覆盖，请补齐或调整考点后再开始作答。
      </text>
      <button class="gap-btn" :loading="isGenerating || isJobInFlight" @tap="emit('fill-gap')">
        补齐缺失考点
      </button>
    </view>

    <view class="questions-list">
      <QuestionPreviewCard
        v-for="(question, idx) in questions"
        :key="question.id || idx"
        :question="question"
        :index="idx"
        :disabled="isGenerating || isJobInFlight"
        @remove="emit('remove', $event)"
        @regenerate="emit('regenerate', $event)"
      />
      <view v-if="questions.length === 0" class="notice-box">
        <text class="notice-text">题目已全部剔除，请重新生成或返回调整配置。</text>
      </view>
    </view>

    <view class="bottom-action-bar">
      <button class="reconfig-btn" @tap="emit('reconfig')">重新调整</button>
      <button
        class="paper-btn-primary start-btn"
        :loading="isStarting"
        :disabled="!canStart"
        @tap="emit('start')"
      >
        开始作答 ({{ questions.length }} 题)
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import type { QuestionItem } from '@/types'
import QuestionPreviewCard from './QuestionPreviewCard.vue'

defineProps<{
  questions: QuestionItem[]
  generatedBatchNotice: string
  generationNotice: string
  missingCount: number
  isGenerating: boolean
  isJobInFlight?: boolean
  isStarting: boolean
  canStart: boolean
}>()

const emit = defineEmits<{
  (e: 'fill-gap'): void
  (e: 'remove', question: QuestionItem): void
  (e: 'regenerate', question: QuestionItem): void
  (e: 'reconfig'): void
  (e: 'start'): void
}>()
</script>

<style lang="scss" scoped>
@import '../questions.scss';
</style>
