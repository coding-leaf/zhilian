<template>
  <view class="paper-card stats-card">
    <text class="card-title">学习足迹</text>
    <view v-if="state.status === 'ready'" class="stats-grid">
      <view class="grid-item">
        <text class="grid-num">{{ state.course_count }}</text>
        <text class="grid-label">已建课程</text>
      </view>
      <view class="grid-item">
        <text class="grid-num">{{ state.ready_material_count }}</text>
        <text class="grid-label">就绪讲义</text>
      </view>
      <view class="grid-item">
        <text class="grid-num">{{ state.knowledge_point_count }}</text>
        <text class="grid-label">涵盖考点</text>
      </view>
    </view>
    <view v-else-if="state.status === 'error'" class="stats-status">
      <text>加载失败，可下拉重试</text>
      <button class="paper-btn-primary retry-btn" @tap="emit('retry')">重试</button>
    </view>
    <text v-else-if="state.status === 'logged-out'" class="stats-status">登录后查看学习足迹</text>
    <text v-else class="stats-status">正在加载学习足迹…</text>
    <text v-if="state.status === 'ready'" class="stats-note">
      课程不含已归档；讲义与考点含未分类及归档课程的就绪资料。
    </text>
  </view>
</template>

<script setup lang="ts">
import type { LearningStatisticsState } from '@/types'

defineProps<{ state: LearningStatisticsState }>()
const emit = defineEmits<{ (e: 'retry'): void }>()
</script>

<style scoped>
.stats-card {
  padding: 32rpx;
  margin-bottom: 32rpx;
}

.card-title {
  font-size: 28rpx;
  font-weight: 700;
  color: var(--color-ink-primary);
  display: block;
  margin-bottom: 24rpx;
}

.stats-grid {
  display: flex;
  justify-content: space-around;
  align-items: center;
}

.grid-item {
  text-align: center;
}

.grid-num {
  font-size: 38rpx;
  font-weight: 700;
  color: var(--color-academic-blue);
  display: block;
}

.grid-label,
.stats-status {
  font-size: 24rpx;
  color: var(--color-ink-secondary);
  margin-top: 4rpx;
}

.stats-status {
  display: block;
  text-align: center;
  padding: 16rpx 0;
}

.retry-btn {
  margin-top: 20rpx;
  font-size: 24rpx;
}

.stats-note {
  display: block;
  margin-top: 24rpx;
  font-size: 22rpx;
  line-height: 1.5;
  color: var(--color-ink-secondary);
}
</style>
