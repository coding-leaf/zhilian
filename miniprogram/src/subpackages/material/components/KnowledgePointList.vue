<template>
  <view class="knowledge-tree-section">
    <view class="section-title-block">
      <text class="section-title">知识点拓扑图谱</text>
      <text class="section-subtitle">点击知识点查看深入讲解与教材原文切片</text>
    </view>

    <view v-if="nodes.length > 0" class="tree-container">
      <view
        v-for="node in nodes"
        :key="node.id"
        class="paper-card tree-node-card"
        @tap="emit('select', node)"
      >
        <view class="node-header">
          <view class="node-title-group">
            <text :class="['level-tag', `level-${node.level}`]">L{{ node.level }}</text>
            <text class="node-name">{{ node.name }}</text>
          </view>
          <text class="node-arrow">→</text>
        </view>
        <text v-if="node.description" class="node-desc">{{ node.description }}</text>
      </view>
    </view>

    <view v-else class="empty-tree">
      <text class="empty-tree-text">知识点正在建树中，请稍后下拉刷新...</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import type { KnowledgeTreeNode } from '@/types'

defineProps<{
  nodes: KnowledgeTreeNode[]
}>()

const emit = defineEmits<{
  (e: 'select', node: KnowledgeTreeNode): void
}>()
</script>

<style lang="scss" scoped>
.knowledge-tree-section {
  margin-top: 16rpx;
}

.section-title-block {
  margin-bottom: 20rpx;
  padding: 0 4rpx;
}

.section-title {
  display: block;
  font-size: 32rpx;
  font-weight: 700;
  color: var(--color-ink-primary);
}

.section-subtitle {
  display: block;
  font-size: 22rpx;
  color: var(--color-ink-subtle);
  margin-top: 4rpx;
}

.tree-node-card {
  padding: 24rpx 28rpx;
  margin-bottom: 16rpx;
  transition: all 0.2s;
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8rpx;
}

.node-title-group {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex: 1;
}

.level-tag {
  font-size: 20rpx;
  font-weight: 700;
  padding: 2rpx 8rpx;
  border-radius: 4rpx;
  background: var(--color-sky-bg);
  color: var(--color-sky);
}

.level-1 {
  background: var(--color-warning-bg-strong);
  color: var(--color-warning-strong);
}

.level-2 {
  background: var(--color-sky-bg);
  color: var(--color-sky);
}

.level-3 {
  background: var(--color-purple-bg);
  color: var(--color-purple);
}

.node-name {
  font-size: 28rpx;
  font-weight: 600;
  color: var(--color-ink-primary);
}

.node-arrow {
  font-size: 26rpx;
  color: var(--color-ink-muted);
}

.node-desc {
  display: block;
  font-size: 24rpx;
  color: var(--color-ink-secondary);
  line-height: 1.5;
  margin-top: 8rpx;
}

.empty-tree {
  padding: 60rpx 0;
  text-align: center;
}

.empty-tree-text {
  font-size: 26rpx;
  color: var(--color-ink-muted);
}
</style>
