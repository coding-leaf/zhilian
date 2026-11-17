<template>
  <view class="mastery-point-list">
    <view v-if="error" class="paper-card inline-error-box">
      <text class="inline-error-text">{{ error }}</text>
      <button class="inline-retry-btn" @tap="emit('retry')">重试</button>
    </view>

    <view v-else-if="loading && points.length === 0" class="empty-state">
      <text class="empty-text">正在加载考点掌握详情...</text>
    </view>

    <view v-else-if="points.length === 0" class="paper-card empty-summary-card">
      <text class="empty-summary-title">
        {{ overview && overview.total_knowledge_points > 0 ? '暂无薄弱或待突破考点' : '暂无考点掌握记录' }}
      </text>
      <text class="empty-summary-desc">
        {{
          overview && overview.total_knowledge_points > 0
            ? `当前范围内共 ${overview.total_knowledge_points} 个考点（熟练 ${overview.proficient_count} · 基本掌握 ${overview.basic_count} · 未练 ${overview.unlearned_count}）。`
            : '请先在工作台导入讲义并完成一次练习，掌握度评估会自动生成。'
        }}
      </text>
    </view>

    <view
      v-for="point in points"
      :key="point.knowledge_point_id"
      class="paper-card mastery-point-card"
    >
      <view class="mp-header">
        <text class="mp-name">{{ point.knowledge_name }}</text>
        <view :class="['mp-level-badge', `level-${point.level}`]">
          {{ levelLabel(point.level) }}
        </view>
      </view>

      <view class="mp-progress-row">
        <view class="mp-progress-track">
          <view
            :class="['mp-progress-fill', `fill-${point.level}`]"
            :style="{ width: masteryPercent(point.mastery_score) }"
          />
        </view>
        <text class="mp-score-text">{{ masteryPercent(point.mastery_score) }}</text>
      </view>

      <view class="mp-footer">
        <view class="mp-meta-group">
          <text class="mp-meta-text">{{ accuracyText(point) }}</text>
          <text v-if="point.last_practiced_at" class="mp-meta-text">
            最近练习：{{ formatDate(point.last_practiced_at) }}
          </text>
        </view>
        <button class="mp-breakthrough-btn" @tap="emit('breakthrough', point)">
          去突破
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import type { KnowledgeMasterySummary, UserMasteryOverview } from '@/types'
import {
  formatMasteryPercent,
  formatPointAccuracy,
  formatShortDateTime,
  masteryLevelLabel,
} from '../reviewView'

defineProps<{
  points: KnowledgeMasterySummary[]
  overview: UserMasteryOverview | null
  loading: boolean
  error: string
}>()

const emit = defineEmits<{
  (e: 'retry'): void
  (e: 'breakthrough', point: KnowledgeMasterySummary): void
}>()

const levelLabel = (level: string) => masteryLevelLabel(level)
const masteryPercent = (score: number) => formatMasteryPercent(score)
const accuracyText = (point: KnowledgeMasterySummary) => formatPointAccuracy(point)
const formatDate = (iso: string) => formatShortDateTime(iso)
</script>

<style lang="scss" scoped>
@import '../review.scss';
</style>
