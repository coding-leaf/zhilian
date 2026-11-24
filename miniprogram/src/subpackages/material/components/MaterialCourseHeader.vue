<template>
  <view v-if="material" class="paper-card detail-card">
    <view class="detail-header">
      <text class="title">{{ material.title }}</text>
      <view class="header-right">
        <view :class="['badge', `badge-${material.status}`]">
          {{ statusText }}
        </view>
        <text
          v-if="material.status === 'ready'"
          class="reparse-top-btn"
          @tap="emit('reparse')"
        >
          重新解析
        </text>
      </view>
    </view>

    <view class="meta-section">
      <text class="meta-item">上传时间：{{ material.created_at?.slice(0, 19).replace('T', ' ') }}</text>
      <text v-if="material.page_count" class="meta-item">解析页数：{{ material.page_count }} 页</text>
      <text v-if="material.key_points_count" class="meta-item">抽取考点：{{ material.key_points_count }} 个</text>
    </view>

    <view v-if="canStartParse" class="status-box waiting-box">
      <text class="status-tips">讲义已上传，点击下方按钮立即启动解析流水线。</text>
      <button class="paper-btn-primary parse-btn" @tap="emit('start-parse')">开始解析</button>
    </view>

    <view v-else-if="isParsing" class="status-box loading-box">
      <view class="loading-row">
        <view class="loading-spinner" />
        <text class="loading-tips">{{ parseProgressText }}</text>
        <button
          class="refresh-progress-btn"
          :disabled="isRefreshing"
          @tap="emit('refresh')"
        >
          {{ isRefreshing ? '刷新中' : '刷新进度' }}
        </button>
      </view>
      <text class="loading-subtips">
        {{
          isParseTimedOut
            ? '后台仍在处理中，自动同步已暂停，请点击「刷新进度」获取最新状态。'
            : '大讲义需提取公式与结构化考点，通常耗时数分钟，可离开页面稍后查看。'
        }}
      </text>
    </view>

    <view v-else-if="material.status === 'failed'" class="status-box error-box">
      <text class="error-tips">解析失败：{{ material.error_message || '文档内容异常或排队超时' }}</text>
      <button class="retry-btn" @tap="emit('reparse-direct')">重新解析</button>
    </view>

    <view v-else-if="material.status === 'retake_required'" class="status-box retake-box">
      <text class="retake-tips">{{ material.error_message || '图片文字不够清晰，请重新拍摄后上传或尝试重新解析。' }}</text>
      <button class="retake-reparse-btn" @tap="emit('reparse-direct')">重新解析</button>
    </view>

    <view v-else-if="material.status === 'ready'" class="status-box ready-box">
      <view class="ready-head-row">
        <text class="ready-tips">讲义解析已就绪，点击考点卡可速览结构化要点与教材溯源。</text>
      </view>
      <button
        v-if="generatedQuestionCount > 0"
        class="review-existing-btn"
        @tap="emit('review-generated')"
      >
        前往我的题库查看（已生成 {{ generatedQuestionCount }} 题）
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
  isParseTimedOut?: boolean
  isRefreshing?: boolean
  parseProgressText: string
  generatedQuestionCount: number
}>()

const emit = defineEmits<{
  (e: 'start-parse'): void
  (e: 'reparse'): void
  (e: 'reparse-direct'): void
  (e: 'refresh'): void
  (e: 'review-generated'): void
}>()

const statusText = computed(() => materialStatusText(props.material))
</script>

<style lang="scss" scoped>
@import '../../../styles/common.scss';

.detail-card { padding: 32rpx; margin-bottom: 28rpx; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16rpx; margin-bottom: 20rpx; }
.title { font-size: 34rpx; font-weight: 700; color: var(--color-ink-primary); flex: 1; min-width: 0; line-height: 1.4; }
.header-right { display: flex; flex-direction: column; align-items: flex-end; gap: 10rpx; flex-shrink: 0; }
.reparse-top-btn {
  font-size: 22rpx; font-weight: 600; color: var(--color-academic-blue);
  background: var(--color-blue-bg); border: 1px solid var(--color-blue-border);
  padding: 6rpx 16rpx; border-radius: 999rpx;
}
.meta-section { border-top: 1px solid var(--color-surface-muted); padding-top: 16rpx; margin-bottom: 20rpx; }
.meta-item { display: block; font-size: 23rpx; color: var(--color-ink-subtle); margin-bottom: 6rpx; }
.status-box { padding: 22rpx; border-radius: 12rpx; font-size: 25rpx; }
.waiting-box { background: var(--color-surface-subtle); border: 1px dashed var(--color-border-strong); }
.status-tips { display: block; font-size: 24rpx; color: var(--color-ink-subtle); margin-bottom: 16rpx; }
.parse-btn { height: 72rpx; font-size: 26rpx; margin: 0; line-height: 1.4; &::after { border: none; } }
.loading-box { background: var(--color-surface-warm); color: var(--color-warm-amber); display: flex; flex-direction: column; gap: 10rpx; }
.loading-row { display: flex; align-items: center; gap: 12rpx; }
.loading-spinner { width: 16rpx; height: 16rpx; border-radius: 8rpx; background: var(--color-warm-amber); flex-shrink: 0; }
.loading-tips { flex: 1; min-width: 0; font-size: 24rpx; line-height: 1.5; }
.loading-subtips { font-size: 22rpx; color: var(--color-ink-subtle); line-height: 1.45; }
.refresh-progress-btn {
  flex-shrink: 0; height: 54rpx; padding: 0 18rpx; margin: 0; line-height: 1.4;
  font-size: 22rpx; font-weight: 600; color: var(--color-academic-blue);
  background: var(--color-bg-card); border: 1px solid var(--color-blue-border);
  border-radius: 999rpx; display: flex; align-items: center; justify-content: center;
  &::after { border: none; }
}
.ready-box { background: var(--color-success-bg-soft); color: var(--color-success-strong); }
.ready-tips { display: block; font-size: 24rpx; line-height: 1.5; }
.review-existing-btn {
  margin: 18rpx 0 0; height: 72rpx; line-height: 1.4; background: var(--color-paper-card);
  color: var(--color-success-strong); font-size: 26rpx; font-weight: 600;
  border: 1px solid var(--color-success-border); border-radius: 10rpx;
  display: flex; align-items: center; justify-content: center;
  &::after { border: none; }
}
.error-box { background: var(--color-danger-bg); color: var(--color-danger-strong); }
.error-tips { display: block; font-size: 24rpx; line-height: 1.5; }
.retry-btn {
  margin: 16rpx 0 0; height: 68rpx; line-height: 1.4; background: var(--color-danger); color: var(--color-ink-on-primary);
  font-size: 25rpx; border-radius: 8rpx; display: flex; align-items: center; justify-content: center;
  &::after { border: none; }
}
.retake-box { background: var(--color-orange-bg); border: 1px solid var(--color-orange-border); color: var(--color-orange-deep); }
.retake-tips { display: block; font-size: 24rpx; line-height: 1.5; }
.retake-reparse-btn {
  margin: 16rpx 0 0; height: 68rpx; line-height: 1.4; background: var(--color-orange-strong); color: var(--color-ink-on-primary);
  font-size: 25rpx; border-radius: 8rpx; display: flex; align-items: center; justify-content: center;
  &::after { border: none; }
}
</style>
