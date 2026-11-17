<template>
  <view class="paper-card detail-card">
    <view class="d-header">
      <text class="d-num">第 {{ result.orderIndex }} 题 ({{ typeLabel(result.type) }})</text>
      <view :class="['result-tag', `tag-${badge.tone}`]">{{ badge.text }}</view>
    </view>

    <text class="d-stem">{{ result.stem }}</text>

    <view v-if="result.options.length" class="answer-compare-box">
      <text v-for="(option, idx) in result.options" :key="option.key || idx" class="ans-line">
        {{ optionDisplayText(option, idx) }}
      </text>
    </view>

    <template v-if="result.gradingStatus === 'graded'">
      <view class="answer-compare-box">
        <text class="ans-line">你的作答：<text class="ans-val">{{ formatAnswer(result.userAnswer) }}</text></text>
        <text class="ans-line">标准答案：<text class="ans-val ans-correct">{{ formatAnswer(result.correctAnswer) }}</text></text>
      </view>

      <view v-if="result.analysis" class="feedback-box">
        <text class="fb-title">判题分析：</text>
        <text class="fb-text">{{ result.analysis }}</text>
      </view>

      <view v-if="result.hitKeywords.length" class="kp-hit-box">
        <text class="hit-title">命中的采分点：</text>
        <text v-for="(hit, idx) in result.hitKeywords" :key="idx" class="hit-item">· {{ hit }}</text>
      </view>

      <view v-if="result.missingKeywords.length" class="kp-miss-box">
        <text class="miss-title">遗漏的要点：</text>
        <text v-for="(miss, idx) in result.missingKeywords" :key="idx" class="miss-item">· {{ miss }}</text>
      </view>

      <view v-if="result.sourceQuote" class="source-quote-box">
        <text class="sq-title">讲义原文对应：</text>
        <text class="sq-text">{{ result.sourceQuote }}</text>
      </view>
    </template>

    <view v-else-if="result.gradingStatus === 'pending_regrade'" class="feedback-box">
      <text class="fb-title">判题状态：待重判</text>
      <text class="fb-text">本题暂未得出有效判分，可申请 AI 复查或填写复核理由。</text>
    </view>

    <view v-else-if="result.gradingStatus === 'grading'" class="feedback-box">
      <text class="fb-title">判题状态：判题中</text>
      <text class="fb-text">本题结果仍在生成，稍后刷新即可查看，暂不计入得分与错题。</text>
    </view>

    <view class="card-actions-row">
      <button
        v-if="canGradeManually(result)"
        class="regrade-action-btn"
        @tap="emit('regrade', result)"
      >
        申请 AI 复查
      </button>
      <button
        v-if="canGradeManually(result)"
        class="regrade-action-btn"
        @tap="emit('self-evaluate', result)"
      >
        自行评分
      </button>
      <button class="coach-action-btn" @tap="emit('coach', result)">
        问 AI 助教
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AttemptResult } from '@/types'
import { optionDisplayText } from '@/api'
import { canGradeManually } from '@/api/adapters/practice'
import { formatAnswer, resolveResultBadge, typeLabel } from '../utils/reportView'

const props = defineProps<{ result: AttemptResult }>()

const emit = defineEmits<{
  (e: 'regrade', result: AttemptResult): void
  (e: 'self-evaluate', result: AttemptResult): void
  (e: 'coach', result: AttemptResult): void
}>()

const badge = computed(() => resolveResultBadge(props.result))
</script>

<style lang="scss" scoped>
.detail-card { padding: 30rpx; margin-bottom: 24rpx; }
.d-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16rpx; }
.d-num { font-size: 26rpx; font-weight: 600; color: var(--color-academic-blue); }
.result-tag { font-size: 22rpx; padding: 4rpx 14rpx; border-radius: 6rpx; }
.tag-correct { background: var(--color-success-bg); color: var(--color-success); }
.tag-wrong { background: var(--color-danger-bg); color: var(--color-danger); }
.tag-pending { background: var(--color-warning-bg); color: var(--color-warm-amber); }
.tag-unanswered { background: var(--color-surface-muted); color: var(--color-ink-subtle); }
.d-stem { display: block; font-size: 28rpx; color: var(--color-ink-primary); line-height: 1.6; margin-bottom: 20rpx; }
.answer-compare-box { background: var(--color-surface-subtle); padding: 16rpx 20rpx; border-radius: 8rpx; margin-bottom: 16rpx; }
.ans-line { display: block; font-size: 24rpx; color: var(--color-ink-subtle); margin-bottom: 6rpx; }
.ans-val { color: var(--color-ink-primary); font-weight: 500; }
.ans-correct { color: var(--color-success); }
.feedback-box, .source-quote-box, .kp-hit-box, .kp-miss-box { margin-top: 12rpx; font-size: 24rpx; line-height: 1.5; }
.fb-title, .sq-title, .hit-title, .miss-title { font-weight: 600; color: var(--color-ink-body); display: block; margin-bottom: 4rpx; }
.hit-title { color: var(--color-correct); }
.miss-title { color: var(--color-wrong); }
.hit-item { color: var(--color-success-strong); display: block; }
.miss-item { color: var(--color-danger-strong); display: block; }
.fb-text { color: var(--color-ink-secondary); }
.sq-text { color: var(--color-ink-subtle); }
.card-actions-row { display: flex; gap: 16rpx; margin-top: 20rpx; padding-top: 16rpx; border-top: 1px dashed var(--color-paper-border); }
.regrade-action-btn, .coach-action-btn { flex: 1; height: 64rpx; font-size: 24rpx; border-radius: 8rpx; display: flex; align-items: center; justify-content: center; }
.regrade-action-btn { background: var(--color-warning-bg-strong); color: var(--color-warning-deep); }
.coach-action-btn { background: var(--color-blue-bg); color: var(--color-academic-blue); }
</style>
