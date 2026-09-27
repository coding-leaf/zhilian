<template>
  <view class="wrong-record-filter-bar">
    <!-- 攻克状态三段式 Tab -->
    <view class="status-tab-group">
      <view
        v-for="tab in statusTabs"
        :key="tab.value"
        class="status-tab-item"
        :class="{ active: currentStatus === tab.value }"
        @tap="selectStatus(tab.value)"
      >
        <text>{{ tab.label }}</text>
      </view>
    </view>

    <!-- 知识点筛选胶囊（若传入） -->
    <view v-if="knowledgePoints && knowledgePoints.length > 0" class="filter-section">
      <text class="section-label">知识点</text>
      <scroll-view class="capsule-scroll" scroll-x :show-scrollbar="false">
        <view class="capsule-row">
          <view
            class="filter-capsule"
            :class="{ active: currentKnowledgePointId === '' }"
            @tap="selectKnowledgePoint('')"
          >
            <text>全部知识点</text>
          </view>
          <view
            v-for="kp in knowledgePoints"
            :key="kp.id"
            class="filter-capsule"
            :class="{ active: currentKnowledgePointId === kp.id }"
            @tap="selectKnowledgePoint(kp.id)"
          >
            <text>{{ kp.name }}</text>
          </view>
        </view>
      </scroll-view>
    </view>

    <!-- 题型筛选胶囊 -->
    <view class="filter-section">
      <text class="section-label">题型</text>
      <scroll-view class="capsule-scroll" scroll-x :show-scrollbar="false">
        <view class="capsule-row">
          <view
            v-for="item in questionTypeOptions"
            :key="item.value"
            class="filter-capsule"
            :class="{ active: currentQuestionType === item.value }"
            @tap="selectQuestionType(item.value)"
          >
            <text>{{ item.label }}</text>
          </view>
        </view>
      </scroll-view>
    </view>

    <!-- 错误类型胶囊 -->
    <view class="filter-section">
      <text class="section-label">错误类型</text>
      <scroll-view class="capsule-scroll" scroll-x :show-scrollbar="false">
        <view class="capsule-row">
          <view
            v-for="item in errorTypeOptions"
            :key="item.value"
            class="filter-capsule"
            :class="{ active: currentErrorType === item.value }"
            @tap="selectErrorType(item.value)"
          >
            <text>{{ item.label }}</text>
          </view>
        </view>
      </scroll-view>
    </view>

    <!-- 重置按钮 -->
    <view v-if="hasActiveFilter" class="filter-actions">
      <view class="reset-btn" @tap="handleReset">
        <text>重置筛选</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * WrongRecordFilterBar.vue
 * Multi-dimensional filter bar for wrong records (mastered status, question type, error type).
 * Complies with docs/DESIGN.md & spec ZL-136.
 * Zero-Emoji Policy enforced.
 */

import { ref, computed, watch } from 'vue';
import type { WrongRecordQueryParams } from '@/types/report';

interface Props {
  modelValue?: WrongRecordQueryParams;
  knowledgePoints?: Array<{ id: string; name: string }>;
  materialId?: string;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: () => ({}),
  knowledgePoints: () => [],
  materialId: '',
});

const emit = defineEmits<{
  (e: 'update:modelValue', value: WrongRecordQueryParams): void;
  (e: 'filter-change', value: WrongRecordQueryParams): void;
}>();

const statusTabs = [
  { label: '全部', value: 'all' },
  { label: '待攻克', value: 'unresolved' },
  { label: '已攻克', value: 'mastered' },
];

const questionTypeOptions = [
  { label: '全部题型', value: '' },
  { label: '单选', value: 'single_choice' },
  { label: '多选', value: 'multiple_choice' },
  { label: '判断', value: 'true_false' },
  { label: '填空', value: 'fill_in_blank' },
  { label: '简答', value: 'short_answer' },
];

const errorTypeOptions = [
  { label: '全部错误', value: '' },
  { label: '概念性错误', value: 'conceptual' },
  { label: '表述不全', value: 'incomplete_expression' },
  { label: '审题偏差', value: 'question_misreading' },
  { label: '未作答', value: 'unanswered' },
];

const currentStatus = ref<string>('all');
const currentKnowledgePointId = ref<string>('');
const currentQuestionType = ref<string>('');
const currentErrorType = ref<string>('');

watch(
  () => props.modelValue,
  (val) => {
    if (!val) return;
    if (val.is_mastered === true) {
      currentStatus.value = 'mastered';
    } else if (val.is_mastered === false) {
      currentStatus.value = 'unresolved';
    } else {
      currentStatus.value = 'all';
    }
    currentKnowledgePointId.value = val.knowledge_point_id || '';
    currentQuestionType.value = val.question_type || '';
    currentErrorType.value = val.error_type || '';
  },
  { immediate: true, deep: true },
);

const hasActiveFilter = computed(() => {
  return (
    currentStatus.value !== 'all' ||
    currentKnowledgePointId.value !== '' ||
    currentQuestionType.value !== '' ||
    currentErrorType.value !== ''
  );
});

function emitChange(): void {
  const result: WrongRecordQueryParams = {
    material_id: props.materialId || undefined,
  };
  if (currentStatus.value === 'mastered') {
    result.is_mastered = true;
  } else if (currentStatus.value === 'unresolved') {
    result.is_mastered = false;
  }
  if (currentKnowledgePointId.value) {
    result.knowledge_point_id = currentKnowledgePointId.value;
  }
  if (currentQuestionType.value) {
    result.question_type = currentQuestionType.value;
  }
  if (currentErrorType.value) {
    result.error_type = currentErrorType.value;
  }

  emit('update:modelValue', result);
  emit('filter-change', result);
}

function selectStatus(status: string): void {
  currentStatus.value = status;
  emitChange();
}

function selectKnowledgePoint(id: string): void {
  currentKnowledgePointId.value = id;
  emitChange();
}

function selectQuestionType(type: string): void {
  currentQuestionType.value = type;
  emitChange();
}

function selectErrorType(type: string): void {
  currentErrorType.value = type;
  emitChange();
}

function handleReset(): void {
  currentStatus.value = 'all';
  currentKnowledgePointId.value = '';
  currentQuestionType.value = '';
  currentErrorType.value = '';
  // BUG-DIAG-015: 仅通过 filter-change 单通道通知父组件，避免 reset 与
  // filter-change 双通道导致父组件重复发起列表请求。
  emitChange();
}
</script>

<style lang="scss" scoped>
@import './WrongRecordFilterBar.scss';
</style>
