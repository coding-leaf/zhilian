<template>
  <view class="paper-card material-card" @tap="emit('open', item)">
    <view class="card-header">
      <text class="material-name">{{ item.title || '无标题资料' }}</text>
      <view :class="['status-badge', `status-${item.status}`]">
        {{ statusText }}
      </view>
    </view>

    <view class="card-body">
      <text class="meta-date">上传：{{ item.created_at?.slice(0, 10) || '今日' }}</text>
      <text v-if="item.page_count" class="meta-page">{{ item.page_count }} 页</text>
      <text v-if="item.key_points_count" class="meta-points">{{ item.key_points_count }} 考点</text>
    </view>

    <view class="card-footer">
      <button
        v-if="showManualParse"
        class="manual-parse-btn"
        @tap.stop="emit('parse', item)"
      >
        {{ item.status === 'failed' ? '重试解析' : '开始解析' }}
      </button>

      <view v-else-if="parsing" class="processing-hint">
        <view class="spinner-dot" />
        <text class="hint-text">正在抽取考点拓扑...</text>
      </view>

      <!-- 已解析状态：知识树学习与出题入口 -->
      <view v-else-if="item.status === 'ready'" class="ready-actions">
        <text class="action-link-study" @tap.stop="emit('open', item)">知识速览 -></text>
        <text class="action-link-practice" @tap.stop="emit('questions', item)">智能出题 -></text>
      </view>

      <!-- 删除入口无条件显示：资料卡整体有 @tap 跳详情，故必须 @tap.stop -->
      <text class="material-delete" @tap.stop="emit('delete', item)">
        {{ deleting ? '删除中…' : '删除' }}
      </text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  canStartMaterialParse,
  isMaterialParsing,
  materialStatusText,
} from '@/utils/materialState'
import type { MaterialItem } from '@/types'

const props = defineProps<{
  item: MaterialItem
  deleting: boolean
}>()

const emit = defineEmits<{
  (e: 'open', item: MaterialItem): void
  (e: 'parse', item: MaterialItem): void
  (e: 'questions', item: MaterialItem): void
  (e: 'delete', item: MaterialItem): void
}>()

const statusText = computed(() => materialStatusText(props.item))
const showManualParse = computed(
  () => canStartMaterialParse(props.item) || props.item.status === 'failed',
)
const parsing = computed(() => isMaterialParsing(props.item))
</script>

<style lang="scss" scoped>
@import '../../../styles/common.scss';

.material-card {
  padding: 28rpx 30rpx;
  margin-bottom: 24rpx;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14rpx;
}

.material-name {
  font-size: 30rpx;
  font-weight: 600;
  color: var(--color-ink-primary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 16rpx;
}

.card-body {
  display: flex;
  gap: 20rpx;
  margin-bottom: 16rpx;
}

.meta-date,
.meta-page,
.meta-points {
  font-size: 22rpx;
  color: var(--color-ink-muted);
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  border-top: 1px dashed var(--color-surface-muted);
  padding-top: 16rpx;
}

.material-delete {
  margin-left: 28rpx;
  color: var(--color-wrong);
  font-size: 23rpx;
}

.manual-parse-btn {
  font-size: 24rpx;
  color: var(--color-ink-on-primary);
  background: var(--color-academic-blue);
  padding: 6rpx 20rpx;
  border-radius: 8rpx;
  margin: 0;
  line-height: 1.4;

  &::after {
    border: none;
  }
}

.processing-hint {
  display: flex;
  align-items: center;
  gap: 10rpx;
}

.spinner-dot {
  width: 14rpx;
  height: 14rpx;
  border-radius: 7rpx;
  background: var(--color-warm-amber);
}

.hint-text {
  font-size: 24rpx;
  color: var(--color-warm-amber);
}

.ready-actions {
  display: flex;
  gap: 24rpx;
}

.action-link-study {
  font-size: 26rpx;
  color: var(--color-academic-teal);
  font-weight: 500;
}

.action-link-practice {
  font-size: 26rpx;
  color: var(--color-academic-blue);
  font-weight: 600;
}
</style>
