<template>
  <view class="diagnosis-summary-card">
    <!-- 顶部标题与评级状态徽章 -->
    <view class="card-top-header">
      <text class="header-title">学情综合诊断</text>
      <view class="badges-wrapper">
        <text v-if="isDegraded" class="degraded-tag">降级模式</text>
        <text
          class="tier-badge"
          :style="{
            backgroundColor: tierInfo.bgColor,
            color: tierInfo.color,
          }"
        >
          {{ tierInfo.label }}
        </text>
      </view>
    </view>

    <!-- 综合总分展示 -->
    <view class="score-section">
      <text class="score-value">{{ displayOverallScore }}</text>
      <text class="score-label">综合得分</text>
    </view>

    <!-- 核心指标网格 -->
    <view class="metrics-grid">
      <view class="metric-item">
        <text class="metric-value">{{ scoreRateDisplay }}</text>
        <text class="metric-label">得分率</text>
      </view>
      <view class="metric-item">
        <text class="metric-value">{{ formattedDuration }}</text>
        <text class="metric-label">答题耗时</text>
      </view>
      <view class="metric-item">
        <text class="metric-value">{{ wrongCountDisplay }}</text>
        <text class="metric-label">答错题数</text>
      </view>
    </view>

    <!-- 待重新判题告警横幅 -->
    <view v-if="hasPendingRegrade" class="pending-regrade-banner">
      <text class="banner-text">
        当前有
        {{ report.pending_regrade_count }} 道主观题待重新判题，您可以进行手动自评或等待系统重判
      </text>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * DiagnosisSummaryCard.vue
 * Overview summary card for diagnosis report.
 * Zero-Emoji Policy: No emoji allowed in styles or UI.
 * Complies with docs/DESIGN.md & spec ZL-135.
 */

import { computed } from 'vue';
import type { DiagnosisReport } from '@/types/report';
import { formatReportDuration, getMasteryTierInfo } from '../utils/reportFormat';

interface Props {
  report: DiagnosisReport;
  durationSeconds?: number;
}

const props = withDefaults(defineProps<Props>(), {
  durationSeconds: 0,
});

const displayOverallScore = computed(() => {
  const score = props.report.overall_score ?? 0;
  return Number.isInteger(score) ? score.toString() : score.toFixed(1);
});

const tierInfo = computed(() => {
  const rate =
    props.report.mastery_rate ??
    (props.report.score_rate !== undefined
      ? props.report.score_rate * 100
      : props.report.overall_score);
  return getMasteryTierInfo(rate);
});

const scoreRateDisplay = computed(() => {
  if (typeof props.report.score_rate === 'number') {
    return `${Math.round(props.report.score_rate * 100)}%`;
  }
  const rate = props.report.mastery_rate ?? props.report.overall_score;
  return `${Math.round(rate > 1 ? rate : rate * 100)}%`;
});

const formattedDuration = computed(() => {
  return formatReportDuration(props.durationSeconds);
});

const wrongCountDisplay = computed(() => {
  return (props.report.wrong_count ?? 0).toString();
});

const hasPendingRegrade = computed(() => {
  return (props.report.pending_regrade_count ?? 0) > 0;
});

const isDegraded = computed(() => {
  return Boolean(props.report.is_structure_degraded);
});
</script>

<style lang="scss" scoped>
@import './DiagnosisSummaryCard.scss';
</style>
