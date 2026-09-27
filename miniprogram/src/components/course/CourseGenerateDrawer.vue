<template>
  <view v-if="isOpen" class="course-generate-mask" @tap="handleClose">
    <view class="course-generate-body" @tap.stop>
      <view class="drawer-header">
        <text class="drawer-title">智能出题</text>
        <text class="close-btn" @tap="handleClose">关闭</text>
      </view>

      <view class="drawer-content">
        <!-- 出题量步进器 (1~20 题，默认 10 题) -->
        <view class="config-section">
          <text class="section-label">出题数量</text>
          <text class="section-tip">单次支持生成 1 到 20 道题目</text>
          <view class="stepper-row">
            <button
              class="step-btn"
              :class="{ disabled: questionCount <= 1 || submitting }"
              :disabled="submitting"
              @tap="handleStepMinus"
            >
              -
            </button>
            <input
              class="count-input"
              type="number"
              :value="String(questionCount)"
              :disabled="submitting"
              @blur="handleCountBlur"
              @input="handleCountInput"
            />
            <button
              class="step-btn"
              :class="{ disabled: questionCount >= 20 || submitting }"
              :disabled="submitting"
              @tap="handleStepPlus"
            >
              +
            </button>
            <text class="count-unit">题</text>
          </view>
        </view>

        <!-- 题型多选胶囊 (至少选中 1 种) -->
        <view class="config-section">
          <text class="section-label">题型设置</text>
          <text class="section-tip">至少选择 1 种题型</text>
          <view class="capsule-group">
            <view
              v-for="item in questionTypeOptions"
              :key="item.value"
              class="capsule-item"
              :class="{ active: selectedTypes.includes(item.value), disabled: submitting }"
              @tap="handleToggleType(item.value)"
            >
              {{ item.label }}
            </view>
          </view>
        </view>

        <!-- 难度倾向胶囊 -->
        <view class="config-section">
          <text class="section-label">难度倾向</text>
          <text class="section-tip">根据掌握情况调整出题难度</text>
          <view class="capsule-group">
            <view
              v-for="item in difficultyOptions"
              :key="item.value"
              class="capsule-item"
              :class="{ active: selectedDifficulty === item.value, disabled: submitting }"
              @tap="handleSelectDifficulty(item.value)"
            >
              {{ item.label }}
            </view>
          </view>
        </view>
      </view>

      <view class="drawer-footer">
        <button
          class="submit-btn"
          :class="{ disabled: submitting }"
          :disabled="submitting"
          @tap="handleSubmit"
        >
          {{ submitting ? '正在生成题目...' : '开始智能出题' }}
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * CourseGenerateDrawer.vue
 * Course-scoped question generation config drawer (count / types / difficulty).
 * Submits `generateQuestions({ folder_id, count, difficulty, question_types })`
 * and emits `success` with the folder id so the course page can navigate.
 * Zero-Emoji policy enforced; lines <= 300.
 */

import { ref, computed } from 'vue';
import { generateQuestions } from '@/api/question';
import { AppError } from '@/utils/error';
import type { QuestionType } from '@/types/question';

interface Props {
  visible?: boolean;
  modelValue?: boolean;
  folderId?: string;
}

interface Emits {
  (e: 'update:visible', val: boolean): void;
  (e: 'update:modelValue', val: boolean): void;
  (e: 'close'): void;
  (e: 'success', folderId: string): void;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  modelValue: false,
  folderId: '',
});

const emit = defineEmits<Emits>();

const isOpen = computed<boolean>(() => props.visible || props.modelValue);

const questionTypeOptions: Array<{ label: string; value: QuestionType }> = [
  { label: '单选题', value: 'single_choice' },
  { label: '多选题', value: 'multiple_choice' },
  { label: '判断题', value: 'true_false' },
  { label: '主观简答题', value: 'short_answer' },
];

const difficultyOptions: Array<{ label: string; value: number }> = [
  { label: '基础巩固', value: 2 },
  { label: '默认/自适应', value: 3 },
  { label: '进阶挑战', value: 4 },
];

const questionCount = ref<number>(10);
const selectedDifficulty = ref<number>(3);
const selectedTypes = ref<QuestionType[]>([
  'single_choice',
  'multiple_choice',
  'true_false',
  'short_answer',
]);
const submitting = ref<boolean>(false);

const GENERATE_FAIL_MESSAGE = '生成题目失败，请稍后重试';
const NETWORK_FAIL_MESSAGE = '网络异常，请重试';

function clampCount(val: number): number {
  if (isNaN(val) || val < 1) return 1;
  if (val > 20) return 20;
  return val;
}

function handleStepMinus(): void {
  if (submitting.value) return;
  questionCount.value = clampCount(questionCount.value - 1);
}

function handleStepPlus(): void {
  if (submitting.value) return;
  questionCount.value = clampCount(questionCount.value + 1);
}

function handleCountInput(e: { detail?: { value?: string } }): void {
  const val = parseInt(e?.detail?.value || '', 10);
  if (!isNaN(val)) {
    questionCount.value = clampCount(val);
  }
}

function handleCountBlur(e: { detail?: { value?: string } }): void {
  const val = parseInt(e?.detail?.value || '', 10);
  questionCount.value = clampCount(val);
}

function handleToggleType(type: QuestionType): void {
  if (submitting.value) return;
  const idx = selectedTypes.value.indexOf(type);
  if (idx !== -1) {
    if (selectedTypes.value.length === 1) {
      uni.showToast({ title: '至少选择一种题型', icon: 'none' });
      return;
    }
    selectedTypes.value.splice(idx, 1);
  } else {
    selectedTypes.value.push(type);
  }
}

function handleSelectDifficulty(val: number): void {
  if (submitting.value) return;
  selectedDifficulty.value = val;
}

function emitClose(): void {
  emit('update:visible', false);
  emit('update:modelValue', false);
  emit('close');
}

function handleClose(): void {
  if (submitting.value) {
    uni.showToast({ title: '正在生成题目，请稍候', icon: 'none' });
    return;
  }
  emitClose();
}

function resolveErrorMessage(err: unknown): string {
  if (err instanceof AppError) {
    return err.code === -1 ? NETWORK_FAIL_MESSAGE : err.message || GENERATE_FAIL_MESSAGE;
  }
  const payload = err as { message?: string; errMsg?: string } | null;
  return payload?.message || payload?.errMsg || GENERATE_FAIL_MESSAGE;
}

async function handleSubmit(): Promise<void> {
  if (submitting.value) return;

  if (!props.folderId) {
    uni.showToast({ title: '缺少课程信息', icon: 'none' });
    return;
  }
  if (selectedTypes.value.length === 0) {
    uni.showToast({ title: '请至少选择一种题型', icon: 'none' });
    return;
  }

  submitting.value = true;
  try {
    const res = await generateQuestions({
      folder_id: props.folderId,
      count: questionCount.value,
      difficulty: selectedDifficulty.value,
      question_types: selectedTypes.value,
    });

    const questions = res.data?.qualified_questions || [];
    if (questions.length === 0) {
      uni.showToast({ title: '本次未产出合格题目，可调整题量后重试', icon: 'none' });
      return;
    }

    uni.showToast({ title: '出题成功', icon: 'success' });
    emit('success', props.folderId);
    emitClose();
  } catch (err: unknown) {
    uni.showToast({ title: resolveErrorMessage(err), icon: 'none' });
  } finally {
    submitting.value = false;
  }
}

defineExpose({
  isOpen,
  questionCount,
  selectedTypes,
  selectedDifficulty,
  submitting,
  handleStepMinus,
  handleStepPlus,
  handleCountInput,
  handleToggleType,
  handleSelectDifficulty,
  handleSubmit,
  handleClose,
});
</script>

<style lang="scss" scoped>
@import './CourseGenerateDrawer.scss';
</style>
