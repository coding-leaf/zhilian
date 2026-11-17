<template>
  <view class="paper-card summary-card mastery-dashboard">
    <view class="dashboard-header">
      <view>
        <text class="title">学情总览</text>
        <text class="subtitle">基于真实作答记录动态评估掌握度</text>
      </view>
      <text class="avg-badge">{{ avgPercentText }}</text>
    </view>

    <view v-if="error" class="inline-error-box">
      <text class="inline-error-text">{{ error }}</text>
      <button class="inline-retry-btn" @tap="emit('retry')">重试</button>
    </view>

    <view v-else-if="loading && !overview" class="dashboard-loading">
      <text class="empty-text">正在同步掌握度数据...</text>
    </view>

    <template v-else>
      <view class="stats-row">
        <view class="stat-col">
          <text class="stat-num material-num">{{ totalCount }}</text>
          <text class="stat-lbl">考点总数</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-col">
          <text class="stat-num material-num">{{ practicedCount }}</text>
          <text class="stat-lbl">已练考点</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-col">
          <text class="stat-num mastered-num">{{ masteredCount }}</text>
          <text class="stat-lbl">已熟练</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-col">
          <text class="stat-num">{{ weakCount }}</text>
          <text class="stat-lbl">薄弱点</text>
        </view>
      </view>

      <view class="mastery-progress-wrap">
        <view class="mastery-progress-track">
          <view class="mastery-progress-fill" :style="{ width: avgPercentText }" />
        </view>
        <view class="tier-pills-row">
          <text class="tier-pill tier-proficient">熟练 {{ masteredCount }}</text>
          <text class="tier-pill tier-basic">基本掌握 {{ basicCount }}</text>
          <text class="tier-pill tier-weak">薄弱 {{ weakCount }}</text>
          <text class="tier-pill tier-unlearned">未练 {{ unlearnedCount }}</text>
        </view>
      </view>

      <button
        v-if="hasWeakPoints"
        class="paper-btn-primary reinforce-weak-btn"
        @tap="emit('reinforce-weak')"
      >
        针对薄弱考点强化练习
      </button>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { UserMasteryOverview } from '@/types'
import { computePracticedPointCount, formatMasteryPercent } from '../reviewView'

const props = defineProps<{
  overview: UserMasteryOverview | null
  loading: boolean
  error: string
}>()

const emit = defineEmits<{
  (e: 'retry'): void
  (e: 'reinforce-weak'): void
}>()

const totalCount = computed(() => props.overview?.total_knowledge_points ?? 0)
const practicedCount = computed(() => computePracticedPointCount(props.overview))
const masteredCount = computed(() => props.overview?.proficient_count ?? 0)
const basicCount = computed(() => props.overview?.basic_count ?? 0)
const weakCount = computed(() => props.overview?.weak_count ?? 0)
const unlearnedCount = computed(() => props.overview?.unlearned_count ?? 0)
const avgPercentText = computed(() =>
  formatMasteryPercent(props.overview?.overall_mastery_score ?? 0),
)
const hasWeakPoints = computed(
  () => weakCount.value > 0 || (props.overview?.weak_knowledge_points?.length ?? 0) > 0,
)
</script>

<style lang="scss" scoped>
@import '../review.scss';
</style>
