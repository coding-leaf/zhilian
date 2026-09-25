<template>
  <view class="weak-knowledge-card">
    <view class="card-header">
      <text class="title">薄弱知识点诊断</text>
      <text v-if="weakPoints.length > 0" class="subtitle-count">
        共 {{ weakPoints.length }} 个薄弱点
      </text>
    </view>

    <!-- 空状态 -->
    <view v-if="weakPoints.length === 0" class="empty-state">
      <text class="empty-text">本次练习暂无显著薄弱考点</text>
    </view>

    <!-- 薄弱知识点列表 -->
    <view v-else class="point-list">
      <view
        v-for="point in weakPoints"
        :key="getPointKey(point)"
        class="point-item"
        @tap="handlePointTap(point)"
      >
        <!-- 考点头部：名称、退步徽章、当前分值 -->
        <view class="point-top-bar">
          <view class="point-name-wrapper">
            <text class="point-name">{{ getPointName(point) }}</text>
            <text v-if="isRegressedPoint(point)" class="regression-badge">退步</text>
          </view>
          <text class="score-display">
            {{ formatPercent(point.current_score) }}
          </text>
        </view>

        <!-- 掌握度进度条 -->
        <view class="progress-bar-container">
          <view
            class="progress-bar-fill"
            :style="{
              width: `${Math.min(100, Math.max(0, Math.round(point.current_score * 100)))}%`,
              backgroundColor: getFillColor(point.current_score),
            }"
          />
        </view>

        <!-- 归因与建议 -->
        <view class="point-meta-content">
          <text v-if="point.cause_explanation" class="cause-text">
            成因诊断：{{ point.cause_explanation }}
          </text>
          <text v-if="point.actionable_advice" class="advice-text">
            改进建议：{{ point.actionable_advice }}
          </text>
          <text v-if="hasHistoricalDecayEvidence(point)" class="evidence-origin">
            【证据来源：历史掌握度低/时间衰减】
          </text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * WeakKnowledgeCard.vue
 * Diagnosed weak knowledge points card with regression indicator and actionable advice.
 * Zero-Emoji Policy: No emoji in styles or UI.
 * Complies with docs/DESIGN.md & spec ZL-135.
 */

import type { WeakPoint } from '@/types/report';
import { formatScoreDelta, getMasteryTierInfo } from '../utils/reportFormat';

interface Props {
  weakPoints: WeakPoint[];
}

defineProps<Props>();

const emit = defineEmits<{
  (e: 'click-point', point: WeakPoint): void;
}>();

function getPointKey(point: WeakPoint): string {
  return point.knowledge_point_id || point.knowledge_id || String(Math.random());
}

function getPointName(point: WeakPoint): string {
  return point.knowledge_name || point.knowledge_title || '未命名考点';
}

function formatPercent(score?: number): string {
  if (typeof score !== 'number' || Number.isNaN(score)) {
    return '0%';
  }
  return `${Math.round(score * 100)}%`;
}

function getFillColor(score?: number): string {
  return getMasteryTierInfo(score).fillColor;
}

function isRegressedPoint(point: WeakPoint): boolean {
  if (typeof point.score_delta === 'number') {
    return formatScoreDelta(point.score_delta).isRegressed;
  }
  return false;
}

function hasHistoricalDecayEvidence(point: WeakPoint): boolean {
  return !point.associated_mistakes || point.associated_mistakes.length === 0;
}

function handlePointTap(point: WeakPoint): void {
  emit('click-point', point);
}
</script>

<style lang="scss" scoped>
@import './WeakKnowledgeCard.scss';
</style>
