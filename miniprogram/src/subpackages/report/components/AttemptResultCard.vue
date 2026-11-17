<template>
  <view class="paper-card detail-card">
    <view class="d-header">
      <view class="d-header-left">
        <text class="d-num">第 {{ result.orderIndex }} 题 ({{ typeLabel(result.type) }})</text>
        <text v-if="result.knowledgePointName" class="d-kp-pill">{{ result.knowledgePointName }}</text>
      </view>
      <view :class="['result-tag', `tag-${badge.tone}`]">{{ badge.text }}</view>
    </view>

    <view class="d-stem">
      <RichContent :content="result.stem" />
    </view>

    <view v-if="result.options.length" class="report-options-list">
      <view
        v-for="(option, idx) in result.options"
        :key="option.key || idx"
        :class="['report-option-row', `opt-tone-${optionTone(option, idx)}`]"
      >
        <view :class="['report-opt-badge', `badge-tone-${optionTone(option, idx)}`]">
          <text class="report-opt-key">{{ optionBadgeLabel(option, idx) }}</text>
        </view>
        <view class="report-opt-body">
          <RichContent :content="formatOptionText(option, idx)" compact />
        </view>
      </view>
    </view>

    <template v-if="result.gradingStatus === 'graded'">
      <view class="answer-compare-box">
        <view class="ans-row">
          <text class="ans-label">你的作答：</text>
          <view class="ans-rich">
            <RichContent :content="formattedUserAnswer" compact />
          </view>
        </view>
        <view class="ans-row">
          <text class="ans-label">标准答案：</text>
          <view class="ans-rich ans-correct">
            <RichContent :content="formattedCorrectAnswer" compact />
          </view>
        </view>
      </view>

      <view v-if="result.analysis" class="feedback-box">
        <text class="fb-title">判题分析：</text>
        <RichContent :content="result.analysis" compact muted />
      </view>

      <view v-if="result.gradingPoints.length" class="grading-points-box">
        <text class="fb-title">采分点与评分细则：</text>
        <view v-for="(point, idx) in result.gradingPoints" :key="idx" class="grading-point-item">
          <text class="grading-point-num">{{ idx + 1 }}.</text>
          <view class="grading-point-rich">
            <RichContent :content="point" compact muted />
          </view>
        </view>
      </view>

      <view v-if="result.hitKeywords.length" class="kp-hit-box">
        <text class="hit-title">命中的采分点：</text>
        <view v-for="(hit, idx) in result.hitKeywords" :key="idx" class="hit-item">
          <RichContent :content="`· ${hit}`" compact />
        </view>
      </view>

      <view v-if="result.missingKeywords.length" class="kp-miss-box">
        <text class="miss-title">遗漏的要点：</text>
        <view v-for="(miss, idx) in result.missingKeywords" :key="idx" class="miss-item">
          <RichContent :content="`· ${miss}`" compact />
        </view>
      </view>

      <view v-if="sourceQuoteView.visible" class="source-quote-box">
        <text class="sq-title">讲义原文对应：</text>
        <text v-if="sourceQuoteView.isGarbled" class="sq-garbled-tip">
          该切片含历史 PDF 公式符号识别噪声，已自动屏蔽；可在讲义详情页点击「重新解析」还原公式。
        </text>
        <RichContent v-else :content="sourceQuoteView.content" compact muted />
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
import RichContent from '@/components/RichContent.vue'
import type { AttemptResult, QuestionOption } from '@/types'
import { optionKey } from '@/api'
import { canGradeManually } from '@/api/adapters/practice'
import {
  formatAttemptAnswer,
  formatOptionText,
  normalizeReportTrueFalse,
  resolveOptionTone,
  resolveResultBadge,
  resolveSourceQuoteView,
  typeLabel,
} from '../utils/reportView'

const props = defineProps<{ result: AttemptResult }>()

const emit = defineEmits<{
  (e: 'regrade', result: AttemptResult): void
  (e: 'self-evaluate', result: AttemptResult): void
  (e: 'coach', result: AttemptResult): void
}>()

const badge = computed(() => resolveResultBadge(props.result))
const formattedUserAnswer = computed(() =>
  formatAttemptAnswer(props.result.userAnswer, props.result.type),
)
const formattedCorrectAnswer = computed(() =>
  formatAttemptAnswer(props.result.correctAnswer, props.result.type),
)
const sourceQuoteView = computed(() => resolveSourceQuoteView(props.result.sourceQuote))

const optionTone = (option: QuestionOption, idx: number) =>
  resolveOptionTone(option, idx, props.result)

const optionBadgeLabel = (option: QuestionOption, idx: number): string => {
  if (props.result.type === 'true_false') {
    const tf = normalizeReportTrueFalse(option.content) || normalizeReportTrueFalse(option.key)
    if (tf === '正确') return '对'
    if (tf === '错误') return '错'
  }
  return optionKey(option, idx)
}
</script>

<style lang="scss" scoped>
@import '../report.scss';
</style>
