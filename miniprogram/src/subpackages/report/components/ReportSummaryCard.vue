<template>
  <view class="paper-card score-card">
    <view class="score-header">
      <text class="score-title">{{ isFullyGraded ? '学情诊断完成' : '本次作答结果' }}</text>
      <text v-if="createdAt" class="score-date">{{ createdAt.slice(0, 10) }}</text>
    </view>

    <view class="score-stats-row">
      <view class="stat-item">
        <text class="stat-num">{{ totalScore === null ? '—' : totalScore }}</text>
        <text class="stat-label">得分 (满分 {{ maxScore === null ? '—' : maxScore }})</text>
      </view>
      <view class="stat-divider" />
      <view class="stat-item">
        <text class="stat-num">{{ scoreRateText }}</text>
        <text class="stat-label">得分率</text>
      </view>
      <view class="stat-divider" />
      <view class="stat-item">
        <text class="stat-num wrong-stat">{{ wrongCount }}</text>
        <text class="stat-label">错题数</text>
      </view>
      <view v-if="pendingCount > 0 || unansweredCount > 0" class="stat-divider" />
      <view v-if="pendingCount > 0 || unansweredCount > 0" class="stat-item">
        <text class="stat-num pending-stat">{{ pendingCount + unansweredCount }}</text>
        <text class="stat-label">待判 / 未答</text>
      </view>
    </view>

    <view v-if="!isFullyGraded" class="pending-notice">
      <text class="pending-notice-text">
        全卷仍在判题中，正式学情诊断将在全部题目判完后自动生成。待判题目不计入错题与得分统计。
      </text>
    </view>

    <view v-if="suggestion" class="next-suggestion-box">
      <text class="suggestion-tag">学习建议</text>
      <text class="suggestion-text">{{ suggestion }}</text>
    </view>
  </view>

  <template v-if="weakPoints.length">
    <text class="section-title">需重点巩固的薄弱点</text>
    <view
      v-for="point in weakPoints"
      :key="point.id || point.name"
      class="paper-card weakness-card"
    >
      <view class="weakness-header">
        <text class="weakness-name">{{ point.name }}</text>
        <text class="weakness-rate">掌握度 {{ formatPercent(point.masteryRate) }}</text>
      </view>
      <text class="weakness-reason">{{ point.reason }}</text>
      <text class="weakness-sugg">建议：{{ point.suggestion }}</text>
    </view>
  </template>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DiagnosisReport } from '@/types'
import { formatPercent, type WeakPointView } from '../utils/reportView'

const props = defineProps<{
  report: DiagnosisReport | null
  totalScore: number | null
  maxScore: number | null
  wrongCount: number
  unansweredCount: number
  pendingCount: number
  isFullyGraded: boolean
  weakPoints: WeakPointView[]
}>()

const createdAt = computed(() => props.report?.created_at || null)

const scoreRateText = computed(() => {
  if (!props.report || !props.isFullyGraded) return '—'
  return formatPercent(props.report.score_rate)
})

const suggestion = computed(() => {
  const report = props.report
  if (!report) return ''
  return report.summary || report.suggestions[0] || report.root_causes[0] || ''
})
</script>

<style lang="scss" scoped>
@import '../report.scss';
</style>
