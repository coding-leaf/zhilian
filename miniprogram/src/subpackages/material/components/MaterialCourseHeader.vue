<template>
  <view v-if="material" class="paper-card detail-card">
    <view class="detail-header">
      <text class="title">{{ material.title }}</text>
      <view :class="['badge', `badge-${material.status}`]">
        {{ statusText }}
      </view>
    </view>

    <view class="meta-section">
      <text class="meta-item">上传时间：{{ material.created_at?.slice(0, 19).replace('T', ' ') }}</text>
      <text v-if="material.page_count" class="meta-item">解析页数：{{ material.page_count }} 页</text>
      <text v-if="material.key_points_count" class="meta-item">抽取考点：{{ material.key_points_count }} 个</text>
    </view>

    <view v-if="canStartParse" class="status-box waiting-box">
      <text class="status-tips">讲义已上传，尚未开始解析。点击下方按钮手动启动解析流水线。</text>
      <button class="paper-btn-primary parse-btn" @tap="emit('start-parse')">开始解析</button>
    </view>

    <view v-else-if="isParsing" class="status-box loading-box">
      <view class="loading-spinner" />
      <text class="loading-tips">{{ parseProgressText }}</text>
    </view>

    <view v-else-if="material.status === 'failed'" class="status-box error-box">
      <text class="error-tips">解析失败：{{ material.error_message || '文档内容异常或排队超时' }}</text>
      <button class="retry-btn" @tap="emit('start-parse')">重试解析</button>
    </view>

    <view v-else-if="material.status === 'retake_required'" class="status-box error-box">
      <text class="error-tips">{{ material.error_message || '图片文字不够清晰，请重新拍摄后上传。' }}</text>
    </view>

    <view v-else-if="material.status === 'ready'" class="status-box ready-box">
      <text class="ready-tips">讲义解析已就绪，已构建完整考点树与证据溯源切片。</text>
      <!-- 已有持久化题目时才渲染：入口表达的「之前生成过」，空态不该由它承担 -->
      <button
        v-if="generatedQuestionCount > 0"
        class="review-existing-btn"
        @tap="emit('review-generated')"
      >
        继续核对已生成题目（{{ generatedQuestionCount }} 道）
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { materialStatusText } from '@/utils/materialState'
import type { MaterialItem } from '@/types'

const props = defineProps<{
  material: MaterialItem | null
  canStartParse: boolean
  isParsing: boolean
  parseProgressText: string
  generatedQuestionCount: number
}>()

const emit = defineEmits<{
  (e: 'start-parse'): void
  (e: 'review-generated'): void
}>()

const statusText = computed(() => materialStatusText(props.material))
</script>

<style lang="scss" scoped>
@import '../../../styles/common.scss';

.detail-card {
  padding: 36rpx 32rpx;
  margin-bottom: 32rpx;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24rpx;
}

.title {
  font-size: 36rpx;
  font-weight: 700;
  color: var(--color-ink-primary);
  flex: 1;
  margin-right: 16rpx;
  line-height: 1.4;
}

.meta-section {
  border-top: 1px solid var(--color-surface-muted);
  padding-top: 20rpx;
  margin-bottom: 24rpx;
}

.meta-item {
  display: block;
  font-size: 24rpx;
  color: var(--color-ink-subtle);
  margin-bottom: 8rpx;
}

.status-box {
  padding: 24rpx;
  border-radius: 12rpx;
  font-size: 26rpx;
}

.waiting-box {
  background: var(--color-surface-subtle);
  border: 1px dashed var(--color-border-strong);
}

.status-tips {
  display: block;
  font-size: 24rpx;
  color: var(--color-ink-subtle);
  margin-bottom: 16rpx;
}

.parse-btn {
  height: 68rpx;
  font-size: 26rpx;
}

.loading-box {
  background: var(--color-surface-warm);
  color: var(--color-warm-amber);
  display: flex;
  align-items: center;
}

.loading-spinner {
  width: 16rpx;
  height: 16rpx;
  border-radius: 8rpx;
  background: var(--color-warm-amber);
  margin-right: 14rpx;
  flex-shrink: 0;
}

.ready-box {
  background: var(--color-success-bg-soft);
  color: var(--color-success-strong);
}

.review-existing-btn {
  margin-top: 20rpx;
  height: 72rpx;
  background: var(--color-paper-card);
  color: var(--color-success-strong);
  font-size: 26rpx;
  font-weight: 600;
  border: 1px solid var(--color-success-border);
  border-radius: 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.error-box {
  background: var(--color-danger-bg);
  color: var(--color-danger-strong);
}

.retry-btn {
  margin-top: 16rpx;
  height: 64rpx;
  background: var(--color-danger);
  color: var(--color-ink-on-primary);
  font-size: 24rpx;
  border-radius: 8rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
