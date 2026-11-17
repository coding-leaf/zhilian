<template>
  <view v-if="visible" class="sheet-overlay">
    <!-- 关闭热区独立成元素：@tap.self 在小程序端被编译器丢弃，绑在容器上会导致点内容即关闭 -->
    <view class="modal-backdrop" @tap="close" />
    <view class="sheet-panel point-sheet paper-card">
      <view class="sheet-header">
        <view class="sheet-title-box">
          <text class="sheet-tag">L{{ point?.level || 1 }} 核心考点</text>
          <text class="sheet-title">{{ point?.name }}</text>
        </view>
        <text class="modal-close" @tap="close">关闭</text>
      </view>

      <scroll-view scroll-y class="sheet-body">
        <view class="point-section">
          <text class="sec-label">知识点定义与深入解析</text>
          <text class="sec-content">
            {{ pointDetail?.description || '该知识点暂无定义说明。' }}
          </text>
          <text v-if="point" class="hierarchy-text">层级：{{ pointHierarchy }}</text>
        </view>

        <view class="point-section">
          <text class="sec-label">教材原文依据切片 ({{ snippets.length }}处溯源)</text>
          <view v-if="loadingSnippets" class="loading-snippets">
            <text class="loading-text">正在检索教材溯源切片...</text>
          </view>
          <view v-else-if="snippets.length > 0" class="snippets-list">
            <view
              v-for="(snip, sIdx) in snippets"
              :key="snip.id || sIdx"
              class="snippet-item"
            >
              <view class="snip-meta">
                <text class="snip-page">第 {{ snip.page_index || 1 }} 页</text>
                <text v-if="snip.chapter_title" class="snip-chapter">{{ snip.chapter_title }}</text>
              </view>
              <text class="snip-content">{{ snip.content }}</text>
            </view>
          </view>
          <view v-else class="empty-snippets">
            <text class="empty-snippets-text">
              {{ snippetLoadFailed ? '原文切片加载失败，请稍后重试。' : '此知识点暂无可展示的原文切片。' }}
            </text>
          </view>
        </view>
      </scroll-view>

      <view class="sheet-footer">
        <button class="paper-btn-primary ask-coach-btn" @tap="emit('ask-coach')">
          问助教：针对本知识点提问
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import type { KnowledgePointDetail, KnowledgeSnippet, KnowledgeTreeNode } from '@/types'

defineProps<{
  visible: boolean
  point: KnowledgeTreeNode | null
  pointDetail: KnowledgePointDetail | null
  pointHierarchy: string
  snippets: KnowledgeSnippet[]
  loadingSnippets: boolean
  snippetLoadFailed: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'ask-coach'): void
}>()

const close = () => {
  emit('update:visible', false)
}
</script>

<style lang="scss" scoped>
@import '../../../styles/modal.scss';

.point-sheet {
  height: 80vh;
}

.sheet-header {
  padding: 28rpx 32rpx;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 1px solid var(--color-surface-muted);
}

.sheet-tag {
  font-size: 20rpx;
  color: var(--color-academic-blue);
  background: var(--color-blue-bg);
  padding: 2rpx 10rpx;
  border-radius: 4rpx;
  font-weight: 600;
  display: inline-block;
  margin-bottom: 6rpx;
}

.sheet-title {
  font-size: 32rpx;
  font-weight: 700;
  color: var(--color-ink-primary);
  display: block;
}

.sheet-body {
  flex: 1;
  padding: 28rpx 32rpx;
  overflow-y: auto;
}

.point-section {
  margin-bottom: 32rpx;
}

.sec-label {
  display: block;
  font-size: 26rpx;
  font-weight: 700;
  color: var(--color-ink-primary);
  margin-bottom: 12rpx;
}

.sec-content {
  display: block;
  font-size: 26rpx;
  color: var(--color-ink-body);
  line-height: 1.6;
  background: var(--color-surface-subtle);
  padding: 20rpx;
  border-radius: 8rpx;
  border: 1px solid var(--color-surface-muted);
}

.hierarchy-text {
  display: block;
  margin-top: 14rpx;
  color: var(--color-ink-subtle);
  font-size: 23rpx;
}

.loading-snippets,
.empty-snippets {
  padding: 20rpx 0;
}

.loading-text,
.empty-snippets-text {
  font-size: 24rpx;
  color: var(--color-ink-muted);
}

.snippets-list {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.snippet-item {
  background: var(--color-surface-slate);
  border-left: 4rpx solid var(--color-academic-blue);
  padding: 16rpx 20rpx;
  border-radius: 4rpx;
}

.snip-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6rpx;
}

.snip-page {
  font-size: 20rpx;
  color: var(--color-academic-blue);
  font-weight: 600;
}

.snip-chapter {
  font-size: 20rpx;
  color: var(--color-ink-slate-subtle);
}

.snip-content {
  font-size: 24rpx;
  color: var(--color-ink-slate);
  line-height: 1.5;
}

.sheet-footer {
  padding: 24rpx 32rpx calc(24rpx + env(safe-area-inset-bottom));
  border-top: 1px solid var(--color-surface-muted);
}

.ask-coach-btn {
  height: 80rpx;
  font-size: 28rpx;
}
</style>
