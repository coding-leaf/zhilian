<template>
  <view v-if="isOpen" class="drawer-mask" @tap="handleClose">
    <view class="drawer-body" @tap.stop>
      <view class="drawer-header">
        <text class="drawer-title">定制出题配置</text>
        <text class="close-btn" @tap="handleClose">关闭</text>
      </view>

      <view class="drawer-content">
        <!-- 考点范围提示 -->
        <view class="config-section">
          <text class="section-label">考点范围</text>
          <text class="section-tip">已选考点: {{ selectedKpCount }} 项</text>
        </view>

        <!-- 出题量步进器 (1~50题边界约束，默认10题) -->
        <view class="config-section">
          <text class="section-label">出题数量</text>
          <text class="section-tip">单次支持生成 1 到 50 道题目</text>
          <view class="stepper-row">
            <button
              class="step-btn"
              :class="{ disabled: questionCount <= 1 || submitting }"
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
              :class="{ disabled: questionCount >= 50 || submitting }"
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
              :class="{ active: selectedTypes.includes(item.value) }"
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
              :class="{ active: selectedDifficulty === item.value }"
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
          {{ submitting ? '正在定制出题...' : '开始定制出题' }}
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import type { QuestionItem, QuestionType } from '@/types/question';
import { generateQuestions } from '@/api/question';
import { validateQuestionConfig } from '../utils/tree';

interface Props {
  visible?: boolean;
  modelValue?: boolean;
  materialId?: string;
  versionId?: string;
  knowledgePointId?: string;
  selectedKnowledgeIds?: string[];
}

interface Emits {
  (e: 'update:visible', val: boolean): void;
  (e: 'update:modelValue', val: boolean): void;
  (e: 'close'): void;
  (e: 'success', questions: QuestionItem[]): void;
  (e: 'generate-success', questions: QuestionItem[]): void;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  modelValue: false,
  materialId: '',
  versionId: '',
  knowledgePointId: '',
  selectedKnowledgeIds: () => [],
});

const emit = defineEmits<Emits>();

const isOpen = computed(() => props.visible || props.modelValue);
const questionCount = ref<number>(10);
const selectedDifficulty = ref<number>(3);
const submitting = ref<boolean>(false);

const questionTypeOptions = [
  { label: '单选题', value: 'single_choice' },
  { label: '多选题', value: 'multiple_choice' },
  { label: '填空题', value: 'fill_in_blank' },
  { label: '主观简答题', value: 'short_answer' },
];

const selectedTypes = ref<string[]>([
  'single_choice',
  'multiple_choice',
  'fill_in_blank',
  'short_answer',
]);

const difficultyOptions = [
  { label: '基础巩固', value: 2 },
  { label: '默认/自适应', value: 3 },
  { label: '进阶挑战', value: 4 },
];

const selectedKpCount = computed<number>(() => {
  if (props.selectedKnowledgeIds.length > 0) {
    return props.selectedKnowledgeIds.length;
  }
  return props.knowledgePointId ? 1 : 0;
});

function clampCount(val: number): number {
  if (isNaN(val) || val < 1) return 1;
  if (val > 50) return 50;
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

function handleToggleType(type: string): void {
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

function handleClose(): void {
  emit('update:visible', false);
  emit('update:modelValue', false);
  emit('close');
}

async function handleSubmit(): Promise<void> {
  if (submitting.value) return;

  const validResult = validateQuestionConfig({
    count: questionCount.value,
    question_types: selectedTypes.value,
  });
  if (!validResult.valid) {
    uni.showToast({ title: validResult.message || '配置参数不合法', icon: 'none' });
    return;
  }

  const targetKpId = props.knowledgePointId || props.selectedKnowledgeIds[0];
  if (!targetKpId) {
    uni.showToast({ title: '请至少选择一个考点', icon: 'none' });
    return;
  }

  submitting.value = true;
  try {
    const res = await generateQuestions({
      material_id: props.materialId,
      version_id: props.versionId || undefined,
      knowledge_point_id: targetKpId,
      count: questionCount.value,
      difficulty: selectedDifficulty.value,
      question_types: selectedTypes.value as QuestionType[],
    });

    const questions: QuestionItem[] = res.data?.qualified_questions || [];
    emit('success', questions);
    emit('generate-success', questions);
    uni.showToast({ title: '出题成功', icon: 'success' });
    handleClose();
  } catch (err: unknown) {
    const errorPayload = err as { message?: string; errMsg?: string };
    const errorMsg = errorPayload?.message || errorPayload?.errMsg || '生成题目失败，请稍后重试';
    uni.showToast({ title: errorMsg, icon: 'none' });
  } finally {
    submitting.value = false;
  }
}
</script>

<style lang="scss" scoped>
@import './QuestionConfigDrawer.scss';
</style>
