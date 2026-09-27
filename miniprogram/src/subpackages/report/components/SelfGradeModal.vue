<template>
  <view v-if="visible" class="self-grade-modal-mask" @tap.self="handleClose">
    <view class="modal-card">
      <!-- 头部：标题与关闭按钮 -->
      <view class="modal-header">
        <text class="modal-title">主观题自主评分</text>
        <view class="close-btn" @tap="handleClose">
          <text>关闭</text>
        </view>
      </view>

      <!-- 可滚动内容主体 -->
      <scroll-view scroll-y class="modal-scroll-content">
        <!-- 试题题干 -->
        <view v-if="stem" class="modal-section">
          <text class="section-label">试题题干</text>
          <text class="stem-text">{{ stem }}</text>
        </view>

        <!-- 您的作答 -->
        <view class="modal-section">
          <text class="section-label">您的作答</text>
          <view class="answer-box user-answer">
            <text>{{ userAnswer || '（未作答）' }}</text>
          </view>
        </view>

        <!-- 参考答案 -->
        <view class="modal-section">
          <text class="section-label">参考标准答案</text>
          <view class="answer-box standard-answer">
            <text>{{ standardAnswer || '暂无标准答案' }}</text>
          </view>
        </view>

        <!-- 评分细则说明 -->
        <view v-if="rubricEntries.length > 0" class="modal-section">
          <text class="section-label">评分细则说明</text>
          <view class="rubric-card">
            <view v-for="(item, idx) in rubricEntries" :key="idx" class="rubric-item">
              <text class="rubric-key">{{ item.label }}</text>
              <text class="rubric-val">{{ item.text }}</text>
            </view>
          </view>
        </view>

        <!-- 分值调节区 -->
        <view class="modal-section score-adjust-container">
          <view class="score-display-row">
            <text class="section-label">自主判定得分</text>
            <view class="score-number-group">
              <text class="current-score-text">{{ localScore.toFixed(1) }}</text>
              <text class="max-score-text">/ {{ maxScore.toFixed(1) }} 分</text>
            </view>
          </view>

          <!-- 滑块选择器 -->
          <view class="slider-wrapper">
            <slider
              class="score-slider"
              :min="0"
              :max="maxScore"
              :step="0.5"
              :value="localScore"
              active-color="#2563EB"
              background-color="#E2E8F0"
              :block-size="20"
              @change="onSliderChange"
            />
          </view>

          <!-- 快速步进按钮组 -->
          <view class="quick-adjust-group">
            <view class="adjust-pill" @tap="adjustScore(-0.5)">
              <text>-0.5 分</text>
            </view>
            <view class="adjust-pill" @tap="setScore(0)">
              <text>0 分</text>
            </view>
            <view class="adjust-pill" @tap="setScore(Number((maxScore / 2).toFixed(1)))">
              <text>半分</text>
            </view>
            <view class="adjust-pill" @tap="setScore(maxScore)">
              <text>满分</text>
            </view>
            <view class="adjust-pill" @tap="adjustScore(0.5)">
              <text>+0.5 分</text>
            </view>
          </view>
        </view>

        <!-- 自评心得 / 理由录入 -->
        <view class="modal-section">
          <text class="section-label">自评理由 / 心得 (选填)</text>
          <view class="feedback-box">
            <textarea
              v-model="localFeedback"
              class="feedback-textarea"
              placeholder="请记录您的自评理由或心得体会（选填）"
              :maxlength="500"
            />
            <view class="char-count">{{ localFeedback.length }} / 500</view>
          </view>
        </view>
      </scroll-view>

      <!-- 底部操作按钮 -->
      <view class="modal-actions">
        <view class="action-btn btn-secondary" @tap="handleClose">
          <text>取消</text>
        </view>
        <view class="action-btn btn-primary" :class="{ disabled: isBusy }" @tap="handleSubmit">
          <text>{{ isBusy ? '提交中...' : '确认提交自评' }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * SelfGradeModal.vue
 * Subjective Question Self-Grading Modal with rubric comparison, score slider, and feedback input.
 * Complies with docs/DESIGN.md & spec ZL-135.
 * Zero-Emoji Policy: No emoji allowed.
 */

import { computed, ref, watch } from 'vue';
import { selfGradeQuestion } from '@/api/diagnosis';

interface Props {
  visible?: boolean;
  attemptItemId: string;
  stem?: string;
  standardAnswer?: string;
  userAnswer?: string;
  maxScore?: number;
  currentScore?: number;
  rubric?: Record<string, unknown> | string;
  submitting?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  stem: '',
  standardAnswer: '',
  userAnswer: '',
  maxScore: 5.0,
  currentScore: 0,
  rubric: () => ({}),
  submitting: false,
});

const emit = defineEmits<{
  (e: 'update:visible', visible: boolean): void;
  (e: 'submit', payload: { attempt_item_id: string; score: number; feedback: string }): void;
  (e: 'success', payload: { attempt_item_id: string; score: number; feedback?: string }): void;
}>();

const localScore = ref(props.currentScore ?? 0);
const localFeedback = ref('');
const localSubmitting = ref(false);

const isBusy = computed(() => props.submitting || localSubmitting.value);

watch(
  () => props.visible,
  (val) => {
    if (val) {
      localScore.value = props.currentScore ?? 0;
      localFeedback.value = '';
      localSubmitting.value = false;
    }
  },
  { immediate: true },
);

watch(
  () => props.currentScore,
  (val) => {
    if (val !== undefined && val !== null) {
      localScore.value = val;
    }
  },
);

interface RubricEntry {
  label: string;
  text: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}

function toUnknownArray(value: unknown): unknown[] {
  return Array.isArray(value) ? (value as unknown[]) : [];
}

function pickFirstText(source: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'string' && value.length > 0) {
      return value;
    }
  }
  return '';
}

function formatRubricValue(value: unknown): string {
  const record = asRecord(value);
  if (record === null) {
    return value === null || value === undefined ? '' : String(value);
  }
  const description = pickFirstText(record, ['description', 'desc', 'point', 'content', 'title']);
  if (description) {
    return description;
  }
  return Object.entries(record)
    .map(([key, nested]) => `${key}: ${formatRubricValue(nested)}`)
    .join('；');
}

function formatRubricPoint(item: unknown, index: number): RubricEntry {
  const record = asRecord(item);
  if (record === null) {
    return { label: `要点 ${index + 1}`, text: formatRubricValue(item) };
  }
  const description = pickFirstText(record, ['description', 'desc', 'point', 'content', 'title']);
  const rawWeight = record.weight ?? record.score ?? record.points;
  const weight =
    typeof rawWeight === 'number' || typeof rawWeight === 'string' ? String(rawWeight) : '';
  return {
    label: weight ? `要点 ${index + 1}（${weight}分）` : `要点 ${index + 1}`,
    text: description || formatRubricValue(record),
  };
}

const rubricEntries = computed<RubricEntry[]>(() => {
  const rubric = props.rubric;
  if (!rubric) return [];
  if (typeof rubric === 'string') {
    return [{ label: '细则说明', text: rubric }];
  }
  const points = toUnknownArray(rubric.points);
  const structured = points.length > 0 ? points : toUnknownArray(rubric.dimensions);
  if (structured.length > 0) {
    return structured.map((item, index) => formatRubricPoint(item, index));
  }
  return Object.entries(rubric)
    .filter(([key]) => key !== 'total_score')
    .map(([key, value]) => ({
      label: key,
      text: formatRubricValue(value),
    }));
});

function handleClose(): void {
  emit('update:visible', false);
}

function onSliderChange(e: { detail?: { value?: number } }): void {
  const val = Number(e?.detail?.value ?? 0);
  setScore(val);
}

function setScore(score: number): void {
  const clamped = Math.max(0, Math.min(props.maxScore, score));
  localScore.value = Number(clamped.toFixed(1));
}

function adjustScore(step: number): void {
  setScore(localScore.value + step);
}

async function handleSubmit(): Promise<void> {
  if (isBusy.value) return;

  const payload = {
    attempt_item_id: props.attemptItemId,
    score: localScore.value,
    feedback: localFeedback.value.trim(),
  };

  emit('submit', payload);

  localSubmitting.value = true;
  try {
    const res = await selfGradeQuestion(payload);
    if (res && (res.code === 0 || res.data)) {
      uni.showToast({ title: '自评已提交', icon: 'success' });
      emit('success', payload);
      emit('update:visible', false);
    } else {
      uni.showToast({ title: res?.message || '提交失败', icon: 'none' });
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : '提交异常';
    uni.showToast({ title: msg, icon: 'none' });
  } finally {
    localSubmitting.value = false;
  }
}
</script>

<style lang="scss" scoped>
@import './SelfGradeModal.scss';
</style>
