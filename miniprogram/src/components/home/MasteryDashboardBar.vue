<template>
  <view
    class="mastery-dashboard-bar"
    :class="{ 'is-loading': loading }"
    role="button"
    aria-label="学情诊断综合掌握度看板"
    @tap="handleTapDetail"
  >
    <!-- 左侧得分与档次徽章 -->
    <view class="score-column">
      <view class="score-display">
        <text class="score-value">{{ displayScoreText }}</text>
        <view
          class="tier-badge"
          :style="{
            backgroundColor: tierInfo.bgColor,
            color: tierInfo.color,
          }"
        >
          {{ tierInfo.label }}
        </view>
      </view>
      <text class="score-sub-label">综合掌握度</text>
    </view>

    <!-- 右侧四档横条与数量分布 -->
    <view class="distribution-column">
      <view class="distribution-header">
        <text class="distribution-title">核心考点分布</text>
        <text class="distribution-total">共 {{ totalPointsCount }} 个</text>
      </view>

      <!-- 四档平滑比例横条 -->
      <view class="tier-bar-track">
        <view
          v-if="tierPercentages.masteredPct > 0"
          class="tier-seg seg-mastered"
          :style="{ width: tierPercentages.masteredPct + '%' }"
        />
        <view
          v-if="tierPercentages.proficientPct > 0"
          class="tier-seg seg-proficient"
          :style="{ width: tierPercentages.proficientPct + '%' }"
        />
        <view
          v-if="tierPercentages.weakPct > 0"
          class="tier-seg seg-weak"
          :style="{ width: tierPercentages.weakPct + '%' }"
        />
        <view
          v-if="tierPercentages.unlearnedPct > 0"
          class="tier-seg seg-unlearned"
          :style="{ width: tierPercentages.unlearnedPct + '%' }"
        />
      </view>

      <!-- 四档数值紧凑标注 -->
      <view class="legend-row">
        <view class="legend-item">
          <view class="dot dot-mastered" />
          <text class="legend-text">精通 {{ tierCounts.mastered }}</text>
        </view>
        <view class="legend-item">
          <view class="dot dot-proficient" />
          <text class="legend-text">良好 {{ tierCounts.proficient }}</text>
        </view>
        <view class="legend-item">
          <view class="dot dot-weak" />
          <text class="legend-text">需巩固 {{ tierCounts.weak }}</text>
        </view>
        <view class="legend-item">
          <view class="dot dot-unlearned" />
          <text class="legend-text">未学 {{ tierCounts.unlearned }}</text>
        </view>
      </view>
    </view>

    <!-- 右侧穿透指示器 -->
    <view class="arrow-indicator">
      <text class="arrow-char">&gt;</text>
    </view>
  </view>
</template>

<script lang="ts">
export interface TierCountsInput {
  mastered_count?: number;
  proficient_count?: number;
  weak_count?: number;
  unlearned_count?: number;
}

export interface TierPercentagesResult {
  masteredPct: number;
  proficientPct: number;
  weakPct: number;
  unlearnedPct: number;
}

export interface OverallTierResult {
  tier: 'mastered' | 'proficient' | 'weak' | 'unlearned';
  label: string;
  color: string;
  bgColor: string;
  fillColor: string;
}

/**
 * 纯函数计算核：计算四档考点分布百分比与严格归一化。
 *
 * @param counts 四档考点计数对象
 * @returns 归一化四档整数百分比（总和严格为 100%）
 */
export function calculateTierPercentages(counts?: TierCountsInput | null): TierPercentagesResult {
  const m = Math.max(0, counts?.mastered_count || 0);
  const p = Math.max(0, counts?.proficient_count || 0);
  const w = Math.max(0, counts?.weak_count || 0);
  const u = Math.max(0, counts?.unlearned_count || 0);
  const total = m + p + w + u;

  if (total <= 0) {
    return { masteredPct: 0, proficientPct: 0, weakPct: 0, unlearnedPct: 100 };
  }

  const items = [
    { key: 'masteredPct', val: (m / total) * 100 },
    { key: 'proficientPct', val: (p / total) * 100 },
    { key: 'weakPct', val: (w / total) * 100 },
    { key: 'unlearnedPct', val: (u / total) * 100 },
  ];

  const floorItems = items.map((item) => ({
    key: item.key,
    floor: Math.floor(item.val),
    rem: item.val - Math.floor(item.val),
  }));

  const currentSum = floorItems.reduce((acc, curr) => acc + curr.floor, 0);
  const diff = 100 - currentSum;
  const sorted = floorItems
    .map((item, idx) => ({ idx, rem: item.rem }))
    .sort((a, b) => b.rem - a.rem);

  for (let i = 0; i < diff; i++) {
    floorItems[sorted[i % sorted.length].idx].floor += 1;
  }

  const result: Record<string, number> = {};
  for (const item of floorItems) {
    result[item.key] = item.floor;
  }

  return {
    masteredPct: result.masteredPct,
    proficientPct: result.proficientPct,
    weakPct: result.weakPct,
    unlearnedPct: result.unlearnedPct,
  };
}

/**
 * 纯函数计算核：根据综合得分判定掌握度档次与设计系统颜色。
 */
export function resolveOverallTier(overallScore?: number | null): OverallTierResult {
  if (
    overallScore === undefined ||
    overallScore === null ||
    typeof overallScore !== 'number' ||
    Number.isNaN(overallScore)
  ) {
    return {
      tier: 'unlearned',
      label: '未学',
      color: '#64748B',
      bgColor: '#F1F5F9',
      fillColor: '#94A3B8',
    };
  }

  const normalized = overallScore > 1 ? overallScore / 100 : overallScore;
  if (normalized <= 0) {
    return {
      tier: 'unlearned',
      label: '未学',
      color: '#64748B',
      bgColor: '#F1F5F9',
      fillColor: '#94A3B8',
    };
  }
  if (normalized >= 0.7) {
    return {
      tier: 'mastered',
      label: '精通',
      color: '#7C3AED',
      bgColor: '#F5F3FF',
      fillColor: '#8B5CF6',
    };
  }
  if (normalized >= 0.4) {
    return {
      tier: 'proficient',
      label: '良好',
      color: '#059669',
      bgColor: '#ECFDF5',
      fillColor: '#10B981',
    };
  }
  return {
    tier: 'weak',
    label: '需巩固',
    color: '#B45309',
    bgColor: '#FFFBEB',
    fillColor: '#F59E0B',
  };
}
</script>

<script setup lang="ts">
import { computed } from 'vue';
import type { UserMasteryOverview } from '@/types/report';

interface Props {
  overview?: UserMasteryOverview | null;
  loading?: boolean;
}

interface Emits {
  (e: 'tap-detail'): void;
  (e: 'click'): void;
}

const props = withDefaults(defineProps<Props>(), {
  overview: null,
  loading: false,
});

const emit = defineEmits<Emits>();

const displayScoreText = computed(() => {
  if (
    props.overview?.overall_score === undefined ||
    props.overview?.overall_score === null ||
    Number.isNaN(props.overview.overall_score)
  ) {
    return '--';
  }
  const score = props.overview.overall_score;
  const num = score > 1 ? Math.round(score) : Math.round(score * 100);
  return `${num}分`;
});

const tierInfo = computed(() => {
  return resolveOverallTier(props.overview?.overall_score);
});

const tierCounts = computed(() => {
  return {
    mastered: props.overview?.mastered_count || 0,
    proficient: props.overview?.proficient_count || 0,
    weak: props.overview?.weak_count || 0,
    unlearned: props.overview?.unlearned_count || 0,
  };
});

const totalPointsCount = computed(() => {
  const c = tierCounts.value;
  return c.mastered + c.proficient + c.weak + c.unlearned;
});

const tierPercentages = computed(() => {
  return calculateTierPercentages(props.overview);
});

function handleTapDetail(): void {
  emit('tap-detail');
  emit('click');
}
</script>

<style lang="scss" scoped>
@import './MasteryDashboardBar.scss';
</style>
