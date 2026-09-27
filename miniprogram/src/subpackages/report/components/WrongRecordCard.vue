<template>
  <view class="wrong-record-card" :class="{ 'is-selected': selected }">
    <!-- 卡片头部：勾选框、题型标签、错误类型、攻克操作按钮 -->
    <view class="card-top-bar">
      <view class="header-left">
        <!-- 多选模式下的勾选热区 -->
        <view v-if="selectable" class="select-touch-area" @tap.stop="handleToggleSelect">
          <view class="select-checkbox" :class="{ checked: selected }">
            <view v-if="selected" class="check-inner" />
          </view>
        </view>

        <!-- 题型标签 -->
        <view class="type-tag">
          <text>{{ formatQuestionType(questionType) }}</text>
        </view>

        <!-- 错误类型胶囊 -->
        <view
          class="error-type-tag"
          :style="{
            color: errorMeta.color,
            backgroundColor: errorMeta.bgColor,
            borderColor: errorMeta.borderColor,
          }"
        >
          <text>{{ errorMeta.label }}</text>
        </view>
      </view>

      <!-- 攻克状态切换按键 -->
      <view
        class="master-action-btn"
        :class="record.is_mastered ? 'is-mastered' : 'is-unresolved'"
        @tap.stop="handleToggleMastered"
      >
        <text>{{ mastering ? '处理中...' : record.is_mastered ? '已攻克' : '标为已攻克' }}</text>
      </view>
    </view>

    <!-- 答错频次与时间统计行 -->
    <view class="meta-stats-row">
      <text class="wrong-count-badge">{{
        formatWrongCount(record.error_count ?? record.wrong_count)
      }}</text>
      <text class="meta-time">{{
        formatRelativeErrorTime(record.first_wrong_at || record.created_at)
      }}</text>
      <text v-if="knowledgeName" class="knowledge-name">{{ knowledgeName }}</text>
    </view>

    <!-- 题干正文 -->
    <view class="stem-content">
      <text>{{ stemText }}</text>
    </view>

    <!-- 选项预览（选择题模式） -->
    <view v-if="optionsList && optionsList.length > 0" class="options-preview">
      <view v-for="opt in optionsList" :key="opt.key" class="option-item">
        <text class="option-key">{{ opt.key }}.</text>
        <text class="option-val">{{ opt.text }}</text>
      </view>
    </view>

    <!-- 展开/收起对比解析栏 -->
    <view class="expand-toggle-row">
      <view class="toggle-expand-btn" @tap="toggleExpand">
        <text>{{ isExpanded ? '收起解析' : '展开答案与解析' }}</text>
      </view>
    </view>

    <!-- 折叠展开的答案比对与题目解析 -->
    <view v-if="isExpanded" class="answer-analysis-foldable">
      <!-- 您的作答 -->
      <view class="comparison-row user-ans">
        <text class="label">您的作答：</text>
        <text class="value">{{ formatAnswer(userAnswer) || '未作答' }}</text>
      </view>

      <!-- 正确答案 -->
      <view class="comparison-row correct-ans">
        <text class="label">正确答案：</text>
        <text class="value">{{ formatAnswer(correctAnswer) || '暂无标准答案' }}</text>
      </view>

      <!-- 题目解析 -->
      <view v-if="analysisText" class="analysis-section">
        <text class="analysis-title">题目解析：</text>
        <text class="analysis-text">{{ analysisText }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * WrongRecordCard.vue
 * Wrong record snapshot card with four-color error tags, foldable answer comparison, and mastery toggle.
 * Complies with docs/DESIGN.md & spec ZL-136.
 * Zero-Emoji Policy enforced.
 */

import { ref, computed } from 'vue';
import type { WrongRecordItem } from '@/types/report';
import {
  getErrorTypeMeta,
  formatWrongCount,
  formatRelativeErrorTime,
} from '../utils/wrongBookFormat';

interface Props {
  record: WrongRecordItem;
  selectable?: boolean;
  selected?: boolean;
  mastering?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  selectable: false,
  selected: false,
  mastering: false,
});

const emit = defineEmits<{
  (e: 'toggle-select', record: WrongRecordItem): void;
  (e: 'toggle-mastered', record: WrongRecordItem): void;
}>();

const isExpanded = ref(false);

const errorMeta = computed(() => getErrorTypeMeta(props.record.error_type));

const questionType = computed(() => {
  return props.record.question_type || props.record.question_snapshot?.question_type || '';
});

const stemText = computed(() => {
  return props.record.question_snapshot?.stem || props.record.question_stem || '无题干信息';
});

const optionsList = computed(() => {
  return props.record.question_snapshot?.options || props.record.options || [];
});

const knowledgeName = computed(() => {
  return props.record.question_snapshot?.knowledge_name || '';
});

const userAnswer = computed(() => {
  return props.record.user_answer;
});

const correctAnswer = computed(() => {
  return props.record.correct_answer || props.record.question_snapshot?.answer || '';
});

const analysisText = computed(() => {
  return props.record.analysis || props.record.question_snapshot?.analysis || '';
});

function formatQuestionType(type: string): string {
  switch (type) {
    case 'single_choice':
      return '单选题';
    case 'multiple_choice':
      return '多选题';
    case 'true_false':
      return '判断题';
    case 'fill_in_blank':
    case 'fill_in_the_blank':
    case 'fill_blank':
      return '填空题';
    case 'short_answer':
      return '简答题';
    default:
      return '试题';
  }
}

function formatAnswer(ans: unknown): string {
  if (ans === null || ans === undefined || ans === '') {
    return '';
  }
  if (Array.isArray(ans)) {
    return ans.join(', ');
  }
  return String(ans);
}

function toggleExpand(): void {
  isExpanded.value = !isExpanded.value;
}

function handleToggleSelect(): void {
  emit('toggle-select', props.record);
}

function handleToggleMastered(): void {
  if (props.mastering) return;
  emit('toggle-mastered', props.record);
}
</script>

<style lang="scss" scoped>
@import './WrongRecordCard.scss';
</style>
