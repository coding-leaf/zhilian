<template>
  <view v-if="wrongPointCount > 0 && canRegenerate" class="paper-card adaptive-card">
    <text class="adaptive-title">错题知识点自适应强化</text>
    <text class="adaptive-desc">
      本次练习涉及 {{ wrongPointCount }} 个薄弱知识点，可针对当前课程范围再生题目继续巩固。
    </text>
    <button
      class="paper-btn-primary adaptive-btn"
      :loading="regenerating"
      @tap="emit('start')"
    >
      错题针对性生题
    </button>
  </view>

  <view v-else-if="wrongPointCount > 0" class="paper-card adaptive-card">
    <text class="adaptive-title">暂无可用再生范围</text>
    <text class="adaptive-desc">
      本次练习未归属课程或资料，暂时无法再生题，请先将资料归入课程后重试。
    </text>
  </view>

  <view v-if="needsRetry" class="paper-card refresh-card">
    <text class="adaptive-title">判题未完成（待重判）</text>
    <text class="adaptive-desc">
      已判 {{ gradedCount }}/{{ totalCount }} 题，仍有 {{ pendingRegradeCount }} 题未判定，
      未判定题目不计零分也不计答错。可重试判题继续完成本轮判分。
    </text>
    <button
      class="paper-btn-primary retry-grading-btn"
      :loading="retryingGrading"
      @tap="emit('retry-grading')"
    >
      重试判题
    </button>
  </view>

  <view v-else-if="!fullyGraded" class="paper-card refresh-card">
    <text class="adaptive-desc">判题进度：已判 {{ gradedCount }}/{{ totalCount }} 题。</text>
    <button class="refresh-btn" :loading="polling" @tap="emit('poll-grading')">
      刷新判题进度
    </button>
  </view>
</template>

<script setup lang="ts">
defineProps<{
  wrongPointCount: number
  canRegenerate: boolean
  regenerating: boolean
  needsRetry: boolean
  fullyGraded: boolean
  gradedCount: number
  totalCount: number
  pendingRegradeCount: number
  retryingGrading: boolean
  polling: boolean
}>()

const emit = defineEmits<{
  (e: 'start'): void
  (e: 'retry-grading'): void
  (e: 'poll-grading'): void
}>()
</script>

<style lang="scss" scoped>
@import '../report.scss';

.refresh-card {
  padding: 24rpx 32rpx;
}

.refresh-btn {
  height: 72rpx;
  font-size: 26rpx;
  background: var(--color-blue-bg);
  color: var(--color-academic-blue);
  border-radius: 8rpx;
  margin-top: 16rpx;
}

.retry-grading-btn {
  height: 76rpx;
  font-size: 27rpx;
  margin-top: 16rpx;
}
</style>
