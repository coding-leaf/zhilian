<template>
  <view class="knowledge-tree-section">
    <view class="section-title-row">
      <view class="section-title-block">
        <text class="section-title">讲义考点学习卡</text>
        <text class="section-subtitle">按章节速览核心定义与实时掌握度，点击查看要点与溯源</text>
      </view>
      <text
        v-if="chapterGroups.length > 1"
        class="expand-all-btn"
        @tap="toggleAllChapters"
      >
        {{ isAllExpanded ? '全部收起' : '全部展开' }}
      </text>
    </view>

    <view v-if="chapterGroups.length > 0" class="chapters-stack">
      <view v-for="group in chapterGroups" :key="group.id" class="chapter-group">
        <view class="paper-card chapter-header" @tap="toggleChapter(group.id)">
          <view class="chapter-header-left">
            <text class="chapter-title">{{ group.title }}</text>
            <text class="chapter-count">{{ group.points.length }} 个考点</text>
          </view>
          <view class="chapter-header-right">
            <text
              v-if="group.chapterNode && formatPreview(group.chapterNode)"
              class="chapter-overview-btn"
              @tap.stop="emit('select', group.chapterNode)"
            >
              章节概览
            </text>
            <text class="chapter-toggle-text">
              {{ isChapterExpanded(group.id) ? '收起' : '展开' }}
            </text>
          </view>
        </view>

        <view v-if="isChapterExpanded(group.id)" class="chapter-cards">
          <view
            v-for="node in group.points"
            :key="node.id"
            class="paper-card tree-node-card kp-study-card"
            @tap="emit('select', node)"
          >
            <view class="node-header">
              <text class="node-name">{{ node.name }}</text>
              <text :class="['mastery-pill', `mastery-${badgeFor(node.id).tone}`]">
                {{ badgeFor(node.id).text }}
              </text>
            </view>

            <text v-if="formatPreview(node)" class="node-summary-clamp">
              {{ formatPreview(node) }}
            </text>

            <view class="card-footer-actions">
              <text class="card-action-detail" @tap.stop="emit('select', node)">查看要点</text>
              <text class="card-action-practice" @tap.stop="emit('practice', node)">练此考点</text>
            </view>
          </view>
        </view>
      </view>
    </view>

    <view v-else class="empty-tree">
      <text class="empty-tree-text">知识点正在整理中，请稍后下拉刷新...</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { KnowledgeTreeNode } from '@/types'
import {
  formatKpSummaryPreview,
  groupKnowledgePointsByChapter,
  resolveMasteryBadge,
  type MasteryEntry,
} from '../utils/courseStudy'

const props = defineProps<{
  nodes: KnowledgeTreeNode[]
  masteryMap?: Record<string, MasteryEntry>
}>()

const emit = defineEmits<{
  (e: 'select', node: KnowledgeTreeNode): void
  (e: 'practice', node: KnowledgeTreeNode): void
}>()

const chapterGroups = computed(() => groupKnowledgePointsByChapter(props.nodes))
const expandedIds = ref<Set<string>>(new Set())

const badgeFor = (kpId: string) => resolveMasteryBadge(props.masteryMap?.[kpId])
const formatPreview = (node: KnowledgeTreeNode) => formatKpSummaryPreview(node)

watch(
  chapterGroups,
  (groups) => {
    const next = new Set<string>()
    groups.forEach((group, idx) => {
      const hasWeak = group.points.some((pt) => badgeFor(pt.id).tone === 'weak')
      if (idx === 0 || group.id === '__general__' || hasWeak) {
        next.add(group.id)
      }
    })
    expandedIds.value = next
  },
  { immediate: true },
)

const isChapterExpanded = (id: string) => expandedIds.value.has(id)

const isAllExpanded = computed(
  () => chapterGroups.value.length > 0 && chapterGroups.value.every((g) => expandedIds.value.has(g.id)),
)

const toggleChapter = (id: string) => {
  const next = new Set(expandedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedIds.value = next
}

const toggleAllChapters = () => {
  if (isAllExpanded.value) {
    expandedIds.value = new Set()
  } else {
    expandedIds.value = new Set(chapterGroups.value.map((g) => g.id))
  }
}
</script>

<style lang="scss" scoped>
@import '../course.scss';

.knowledge-tree-section { margin-top: 8rpx; }
.section-title-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 16rpx; margin-bottom: 20rpx; padding: 0 4rpx; }
.section-title-block { flex: 1; min-width: 0; }
.section-title { display: block; font-size: 32rpx; font-weight: 700; color: var(--color-ink-primary); }
.section-subtitle { display: block; font-size: 22rpx; color: var(--color-ink-subtle); margin-top: 4rpx; }
.expand-all-btn { font-size: 24rpx; font-weight: 600; color: var(--color-academic-blue); flex-shrink: 0; padding: 6rpx 8rpx; }
.chapters-stack { display: flex; flex-direction: column; gap: 20rpx; }
.chapter-header {
  padding: 22rpx 26rpx; display: flex; justify-content: space-between; align-items: center;
  gap: 16rpx; background: var(--color-surface-warm);
}
.chapter-header-left { flex: 1; min-width: 0; }
.chapter-title { display: block; font-size: 28rpx; font-weight: 700; color: var(--color-ink-primary); line-height: 1.4; }
.chapter-count { display: block; font-size: 22rpx; color: var(--color-ink-subtle); margin-top: 4rpx; }
.chapter-header-right { display: flex; align-items: center; gap: 14rpx; flex-shrink: 0; }
.chapter-overview-btn {
  font-size: 22rpx; color: var(--color-academic-teal); background: var(--color-teal-bg);
  padding: 4rpx 14rpx; border-radius: 999rpx; font-weight: 500;
}
.chapter-toggle-text { font-size: 23rpx; font-weight: 600; color: var(--color-academic-blue); }
.chapter-cards { display: flex; flex-direction: column; gap: 14rpx; margin-top: 12rpx; }
.kp-study-card { padding: 24rpx 26rpx; }
.node-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 14rpx; margin-bottom: 10rpx; }
.node-name { flex: 1; min-width: 0; font-size: 29rpx; font-weight: 700; color: var(--color-ink-primary); line-height: 1.4; }
.node-summary-clamp {
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  font-size: 24rpx; color: var(--color-ink-secondary); line-height: 1.55; margin-bottom: 16rpx;
}
.card-footer-actions {
  display: flex; justify-content: flex-end; align-items: center; gap: 16rpx;
  padding-top: 14rpx; border-top: 1px dashed var(--color-paper-border);
}
.card-action-detail {
  font-size: 24rpx; font-weight: 600; color: var(--color-ink-secondary);
  background: var(--color-surface-muted); padding: 8rpx 20rpx; border-radius: 8rpx;
}
.card-action-practice {
  font-size: 24rpx; font-weight: 600; color: var(--color-academic-blue);
  background: var(--color-blue-bg); border: 1px solid var(--color-blue-border);
  padding: 8rpx 20rpx; border-radius: 8rpx;
}
.empty-tree { padding: 60rpx 0; text-align: center; }
.empty-tree-text { font-size: 26rpx; color: var(--color-ink-muted); }
</style>
