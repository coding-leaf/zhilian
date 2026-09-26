<template>
  <view class="question-card">
    <view class="q-header">
      <text class="q-type-badge">{{ formatQuestionType(question.question_type) }}</text>
      <text class="q-difficulty">难度 {{ question.difficulty }}</text>
    </view>

    <text class="q-stem">{{ question.stem }}</text>

    <!-- 客观题展示选项；主观简答题隐藏选项区 -->
    <view v-if="showOptions" class="q-options">
      <view v-for="option in options" :key="option.key" class="q-option">
        <text class="option-key">{{ option.key }}</text>
        <text class="option-text">{{ option.text }}</text>
      </view>
    </view>

    <view class="q-answer-box">
      <text class="ans-label">参考答案：</text>
      <text class="ans-content">{{ question.answer || '暂无参考答案' }}</text>
    </view>

    <!-- 解析折叠区 -->
    <view v-if="question.analysis" class="q-analysis">
      <view class="analysis-header" @tap="toggleAnalysis">
        <text class="analysis-label">解析</text>
        <text class="analysis-toggle">{{ isAnalysisOpen ? '收起' : '展开' }}</text>
      </view>
      <text v-if="isAnalysisOpen" class="analysis-content">{{ question.analysis }}</text>
    </view>

    <view class="q-actions">
      <button class="action-btn primary" @tap="handleEdit">编辑</button>
      <button class="action-btn" @tap="handleAudit">修改痕迹</button>
      <button class="action-btn danger" @tap="handleDelete">删除</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import type { QuestionItem, QuestionOption } from '@/types/question';

interface Props {
  question: QuestionItem;
}

interface Emits {
  (e: 'edit', question: QuestionItem): void;
  (e: 'audit', questionId: string): void;
  (e: 'delete', questionId: string): void;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const isAnalysisOpen = ref<boolean>(false);

const options = computed<QuestionOption[]>(() =>
  Array.isArray(props.question.options) ? props.question.options : [],
);

const showOptions = computed<boolean>(
  () => props.question.question_type !== 'short_answer' && options.value.length > 0,
);

function toggleAnalysis(): void {
  isAnalysisOpen.value = !isAnalysisOpen.value;
}

function handleEdit(): void {
  emit('edit', props.question);
}

function handleAudit(): void {
  emit('audit', props.question.id);
}

function handleDelete(): void {
  emit('delete', props.question.id);
}

function formatQuestionType(type?: string): string {
  const map: Record<string, string> = {
    single_choice: '单选题',
    multiple_choice: '多选题',
    true_false: '判断题',
    fill_in_blank: '填空题',
    short_answer: '主观简答题',
  };
  return (type && map[type]) || type || '题目';
}

defineExpose({
  isAnalysisOpen,
  options,
  showOptions,
  toggleAnalysis,
  formatQuestionType,
});
</script>

<style lang="scss" scoped>
@import './QuestionCard.scss';
</style>
