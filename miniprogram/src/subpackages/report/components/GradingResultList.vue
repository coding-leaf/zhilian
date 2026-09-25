<template>
  <view class="grading-result-list">
    <!-- 空状态 -->
    <view v-if="items.length === 0" class="empty-state">
      <text class="empty-text">暂无题目作答记录</text>
    </view>

    <!-- 逐题卡片列表 -->
    <view
      v-for="item in items"
      :key="item.attempt_item_id || item.id || String(item.order_index)"
      class="result-card"
    >
      <!-- 顶栏：题号、题型、状态徽章与分值 -->
      <view class="card-top-row">
        <view class="order-type-group">
          <text class="order-title">第 {{ item.order_index }} 题</text>
          <text class="type-tag">{{
            getQuestionTypeLabel(item.question_snapshot?.question_type)
          }}</text>
        </view>
        <view class="status-score-group">
          <text
            class="status-badge"
            :style="{
              backgroundColor: getStatus(item).bgColor,
              color: getStatus(item).textColor || getStatus(item).color,
              borderColor: getStatus(item).borderColor || getStatus(item).color,
            }"
          >
            {{ getStatus(item).label }}
          </text>
          <text class="score-info">{{ getScoreText(item) }}</text>
        </view>
      </view>

      <!-- 题干 -->
      <view class="question-stem">
        <text>{{ item.question_snapshot?.stem }}</text>
      </view>

      <!-- 用户作答与参考答案对比 -->
      <view class="comparison-section">
        <view class="answer-line">
          <text class="label">您的作答：</text>
          <text class="user-text">{{ formatAnswer(item.user_answer) }}</text>
        </view>
        <view v-if="item.question_snapshot?.answer" class="answer-line">
          <text class="label">参考答案：</text>
          <text class="standard-text">{{ item.question_snapshot.answer }}</text>
        </view>
      </view>

      <!-- 题目解析 -->
      <view v-if="item.question_snapshot?.analysis" class="analysis-section">
        <text class="analysis-text">解析：{{ item.question_snapshot.analysis }}</text>
      </view>

      <!-- 关键词微胶囊 (命中与遗漏) -->
      <view v-if="hasKeywords(item)" class="keywords-wrapper">
        <text
          v-for="(kw, idx) in item.question_snapshot.hit_keywords || []"
          :key="`hit-${idx}`"
          class="keyword-capsule hit"
        >
          已命中：{{ kw }}
        </text>
        <text
          v-for="(kw, idx) in item.question_snapshot.missing_keywords || []"
          :key="`miss-${idx}`"
          class="keyword-capsule missing"
        >
          遗漏：{{ kw }}
        </text>
      </view>

      <!-- 操作栏：原文依据、自评与重判入口 -->
      <view class="card-actions-row">
        <view
          v-if="hasSnippet(item)"
          class="action-btn snippet-btn"
          @tap="emit('view-snippet', item)"
        >
          <text>查看原文依据</text>
        </view>
        <view
          v-if="canSelfGrade(item)"
          class="action-btn self-grade-btn"
          @tap="emit('self-grade', item)"
        >
          <text>手动自评</text>
        </view>
        <view v-if="canSelfGrade(item)" class="action-btn regrade-btn" @tap="emit('regrade', item)">
          <text>申请重判</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * GradingResultList.vue
 * Question-by-question grading review list with comparison, keyword chips, and actions.
 * Complies with docs/DESIGN.md & spec ZL-135.
 * Zero-Emoji Policy: No emoji allowed.
 */

import type { AttemptGradingItem, GradingStatusInfo } from '@/types/report';
import { getGradingStatusInfo } from '../utils/reportFormat';

interface Props {
  items: AttemptGradingItem[];
}

defineProps<Props>();

const emit = defineEmits<{
  (e: 'view-snippet', item: AttemptGradingItem): void;
  (e: 'self-grade', item: AttemptGradingItem): void;
  (e: 'regrade', item: AttemptGradingItem): void;
}>();

const questionTypeMap: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_in_blank: '填空题',
  short_answer: '简答题',
};

function getQuestionTypeLabel(type?: string): string {
  if (!type) return '试题';
  return questionTypeMap[type] || '试题';
}

function getStatus(item: AttemptGradingItem): GradingStatusInfo {
  return getGradingStatusInfo({
    status: item.status,
    score: item.score,
    max_score: item.max_score,
  });
}

function getScoreText(item: AttemptGradingItem): string {
  const status = getStatus(item).status;
  if (status === 'pending_regrade') {
    return '待判定';
  }
  const score = item.score ?? 0;
  const maxScore = item.max_score ?? 1;
  return `${score} / ${maxScore} 分`;
}

function formatAnswer(userAnswer?: unknown): string {
  if (userAnswer === null || userAnswer === undefined || userAnswer === '') {
    return '（未作答）';
  }
  if (Array.isArray(userAnswer)) {
    return userAnswer.join(', ');
  }
  return String(userAnswer);
}

function hasKeywords(item: AttemptGradingItem): boolean {
  const hit = item.question_snapshot?.hit_keywords;
  const miss = item.question_snapshot?.missing_keywords;
  return Boolean((hit && hit.length > 0) || (miss && miss.length > 0));
}

function hasSnippet(item: AttemptGradingItem): boolean {
  return Boolean(
    item.question_snapshot?.source_snippet || item.question_snapshot?.source_snippet_id,
  );
}

function canSelfGrade(item: AttemptGradingItem): boolean {
  const isSubjective = item.question_snapshot?.question_type === 'short_answer';
  const isPending = item.status === 'pending_regrade' || item.score === null;
  return isSubjective || isPending;
}
</script>

<style lang="scss" scoped>
@import './GradingResultList.scss';
</style>
