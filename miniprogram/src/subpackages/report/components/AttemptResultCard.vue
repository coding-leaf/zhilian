<template>
  <view class="paper-card detail-card">
    <view class="d-header">
      <text class="d-num">第 {{ result.orderIndex }} 题 ({{ typeLabel(result.type) }})</text>
      <view :class="['result-tag', `tag-${badge.tone}`]">{{ badge.text }}</view>
    </view>

    <text class="d-stem">{{ result.stem }}</text>

    <view v-if="result.options.length" class="answer-compare-box">
      <text v-for="(option, idx) in result.options" :key="option.key || idx" class="ans-line">
        {{ option.key || String.fromCharCode(65 + idx) }}. {{ option.content }}
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
@import '../report.scss';
</style>
