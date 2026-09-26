<template>
  <view v-if="isOpen" class="drawer-mask" @tap="handleClose">
    <view class="drawer-body" @tap.stop>
      <view class="drawer-header">
        <text class="drawer-title">定制出题配置</text>
        <text class="close-btn" @tap="handleClose">关闭</text>
      </view>

      <view class="drawer-content">
        <!-- 生成进行中面板：阶段文案轮播 + 已耗时计时（流程示意，非真实进度） -->
        <view v-if="submitting" class="progress-panel">
          <view class="progress-stages">
            <view
              v-for="(stage, idx) in stages"
              :key="stage"
              class="progress-stage"
              :class="{ active: idx === stageIndex, done: idx < stageIndex }"
            >
              {{ stage }}
            </view>
          </view>
          <text class="progress-timer">已等待 {{ elapsedSeconds }} 秒，流程示意仅供参考</text>
        </view>

        <!-- 考点范围提示 -->
        <view class="config-section">
          <text class="section-label">考点范围</text>
          <text class="section-tip">已选考点: {{ selectedKpCount }} 项</text>
          <text v-if="distributionHint" class="section-tip">{{ distributionHint }}</text>
        </view>

        <!-- 出题量步进器 (1~50题边界约束，默认10题) -->
        <view class="config-section">
          <text class="section-label">出题数量</text>
          <text class="section-tip">单次支持生成 1 到 50 道题目</text>
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
              :class="{ disabled: questionCount >= 50 || submitting }"
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
import {
  DIFFICULTY_OPTIONS,
  QUESTION_TYPE_OPTIONS,
  navigateToQuestionPage,
  resolveGenerateErrorMessage,
} from '../utils/questionGeneration';
import { useGenerationProgress } from '../composables/useGenerationProgress';

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

const {
  stages,
  stageIndex,
  elapsedSeconds,
  start: startProgress,
  stop: stopProgress,
} = useGenerationProgress();

const questionTypeOptions = QUESTION_TYPE_OPTIONS;
const difficultyOptions = DIFFICULTY_OPTIONS;

const selectedTypes = ref<string[]>([
  'single_choice',
  'multiple_choice',
  'fill_in_blank',
  'short_answer',
]);

const selectedKpCount = computed<number>(() => {
  if (props.selectedKnowledgeIds.length > 0) {
    return props.selectedKnowledgeIds.length;
  }
  return props.knowledgePointId ? 1 : 0;
});

// 题量分配提示：与后端「均分 + 每考点至少 1 题」规则保持一致。
const distributionHint = computed<string>(() => {
  const kpCount = selectedKpCount.value;
  if (kpCount === 0) {
    return '';
  }
  if (questionCount.value < kpCount) {
    return `每个考点至少 1 题，实际将生成 ${kpCount} 题`;
  }
  return `已选 ${kpCount} 个考点，共 ${questionCount.value} 题`;
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

  const selectedIds =
    props.selectedKnowledgeIds.length > 0
      ? props.selectedKnowledgeIds
      : props.knowledgePointId
        ? [props.knowledgePointId]
        : [];
  if (selectedIds.length === 0) {
    uni.showToast({ title: '请至少选择一个考点', icon: 'none' });
    return;
  }

  submitting.value = true;
  startProgress();
  try {
    const res = await generateQuestions({
      material_id: props.materialId,
      version_id: props.versionId || undefined,
      // 保留首位考点以兼容旧后端；同时提交全部已选考点。
      knowledge_point_id: selectedIds[0],
      knowledge_point_ids: selectedIds,
      count: questionCount.value,
      difficulty: selectedDifficulty.value,
      question_types: selectedTypes.value as QuestionType[],
    });

    const questions: QuestionItem[] = res.data?.qualified_questions || [];
    if (questions.length === 0) {
      uni.showToast({ title: '本次未产出合格题目，可调整考点或题量后重试', icon: 'none' });
      return;
    }

    emit('success', questions);
    emitClose();
    navigateToQuestionPage(props.materialId);
    uni.showToast({ title: '出题成功', icon: 'success' });
  } catch (err: unknown) {
    uni.showToast({ title: resolveGenerateErrorMessage(err), icon: 'none' });
  } finally {
    stopProgress();
    submitting.value = false;
  }
}
</script>

<style lang="scss" scoped>
@import './QuestionConfigDrawer.scss';
</style>
