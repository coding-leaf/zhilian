<template>
  <view class="question-renderer">
    <!-- 顶部状态栏：题型徽章与题号 -->
    <view class="question-header">
      <text class="type-badge">{{ questionTypeLabel }}</text>
      <text v-if="orderIndex" class="order-label">第 {{ orderIndex }} 题</text>
    </view>

    <!-- 题干卡片 -->
    <view class="stem-card">
      <text class="stem-text">{{ question.stem }}</text>
    </view>

    <!-- 1. 单选题渲染 -->
    <view v-if="question.question_type === 'single_choice'" class="options-container">
      <OptionCard
        v-for="opt in formattedOptions"
        :key="opt.key"
        :option-key="opt.key"
        :content="opt.text"
        :selected="modelValue === opt.key"
        type="radio"
        @select="handleSingleSelect"
      />
    </view>

    <!-- 2. 多选题渲染 -->
    <view v-else-if="question.question_type === 'multiple_choice'" class="options-container">
      <OptionCard
        v-for="opt in formattedOptions"
        :key="opt.key"
        :option-key="opt.key"
        :content="opt.text"
        :selected="isMultiSelected(opt.key)"
        type="checkbox"
        @select="handleMultiSelect"
      />
    </view>

    <!-- 3. 判断题渲染 -->
    <view v-else-if="question.question_type === 'true_false'" class="options-container">
      <OptionCard
        v-for="opt in trueFalseOptions"
        :key="opt.key"
        :option-key="opt.key"
        :content="opt.text"
        :selected="modelValue === opt.key"
        type="radio"
        @select="handleSingleSelect"
      />
    </view>

    <!-- 4. 填空题渲染 -->
    <view v-else-if="question.question_type === 'fill_in_blank'" class="blank-input-wrapper">
      <input
        class="blank-input"
        type="text"
        :value="typeof modelValue === 'string' ? modelValue : ''"
        placeholder="请输入你的作答"
        @input="handleInput"
      />
    </view>

    <!-- 5. 主观题渲染：简答题 / 名词解释 / 案例分析 / 未知题型兜底 -->
    <view v-else class="short-answer-wrapper">
      <textarea
        class="short-answer-textarea"
        :value="typeof modelValue === 'string' ? modelValue : ''"
        :placeholder="subjectivePlaceholder"
        :maxlength="500"
        @input="handleTextareaInput"
      />
      <text class="word-count">{{ answerLength }}/500</text>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * QuestionRenderer.vue
 * Core dispatcher component for practice question types.
 * Covers objective types plus subjective fallbacks (short_answer, term_explanation,
 * case_analysis, and unknown types). Reference: docs/sdlc/ZL-134/spec.md
 * Zero-Emoji Policy enforced.
 */

import { computed } from 'vue';
import OptionCard from './OptionCard.vue';
import type { QuestionType } from '../../../types/question';

export interface RendererQuestion {
  id: string;
  stem: string;
  question_type: QuestionType | string;
  options?: Array<{ key: string; text: string }>;
  difficulty?: number;
}

interface Props {
  question: RendererQuestion;
  modelValue?: string | string[];
  orderIndex?: number;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  orderIndex: 0,
});

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | string[]): void;
}>();

const questionTypeLabel = computed<string>(() => {
  const map: Record<string, string> = {
    single_choice: '单选题',
    multiple_choice: '多选题',
    true_false: '判断题',
    fill_in_blank: '填空题',
    short_answer: '简答题',
    term_explanation: '名词解释',
    case_analysis: '案例分析',
  };
  return map[props.question.question_type] || '练习题';
});

const subjectivePlaceholder = computed<string>(() => {
  const map: Record<string, string> = {
    short_answer: '请输入你的简要分析或回答（最多500字）',
    term_explanation: '请输入名词解释（最多500字）',
    case_analysis: '请输入案例分析（最多500字）',
  };
  return map[props.question.question_type] || '请输入你的作答（最多500字）';
});

const formattedOptions = computed(() => {
  return props.question.options || [];
});

const trueFalseOptions = computed(() => {
  if (props.question.options && props.question.options.length > 0) {
    return props.question.options;
  }
  return [
    { key: 'T', text: '正确' },
    { key: 'F', text: '错误' },
  ];
});

const answerLength = computed<number>(() => {
  if (typeof props.modelValue === 'string') {
    return props.modelValue.length;
  }
  return 0;
});

function handleSingleSelect(key: string): void {
  emit('update:modelValue', key);
}

function isMultiSelected(key: string): boolean {
  if (Array.isArray(props.modelValue)) {
    return props.modelValue.includes(key);
  }
  return false;
}

function handleMultiSelect(key: string): void {
  const currentList = Array.isArray(props.modelValue) ? [...props.modelValue] : [];
  const idx = currentList.indexOf(key);
  if (idx >= 0) {
    currentList.splice(idx, 1);
  } else {
    currentList.push(key);
    currentList.sort(); // 保持 A, B, C 顺序
  }
  emit('update:modelValue', currentList);
}

function handleInput(event: unknown): void {
  const target = event as { detail?: { value?: string } };
  const val = target.detail?.value ?? '';
  emit('update:modelValue', val);
}

function handleTextareaInput(event: unknown): void {
  const target = event as { detail?: { value?: string } };
  const val = target.detail?.value ?? '';
  emit('update:modelValue', val);
}
</script>

<style lang="scss" scoped>
@import './QuestionRenderer.scss';
</style>
