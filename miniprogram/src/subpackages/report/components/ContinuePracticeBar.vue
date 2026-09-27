<template>
  <view class="continue-practice-bar bottom-action-bar">
    <view class="bar-content">
      <view v-if="showInfo" class="info-section">
        <text class="info-count">
          已选<text class="highlight-num">{{ count }}</text
          >{{ countUnit }}
        </text>
        <text v-if="tipText" class="info-tip">{{ tipText }}</text>
      </view>

      <view
        class="continue-btn"
        :class="{
          'is-submitting': isSubmitting,
          'is-disabled': disabled,
        }"
        @tap="handleTap"
      >
        <text class="btn-text">{{ displayButtonText }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * ContinuePracticeBar.vue
 * Bottom fixed continue practice action bar with 500ms debounce, UUID v4 idempotency, and anti-duplicate lock.
 * Complies with docs/DESIGN.md & spec ZL-136.
 * Zero-Emoji Policy enforced.
 */

import { ref, computed } from 'vue';
import { usePracticeStore } from '@/stores/practiceStore';
import { continuePractice } from '@/api/diagnosis';
import type { PracticeSession } from '@/types/practice';
import { generateIdempotencyKey, buildContinuePracticePayload } from '../utils/wrongBookFormat';

interface Props {
  materialId?: string;
  knowledgePointIds?: string[];
  sourceReportId?: string;
  sourceType?: 'weakness' | 'wrong_record';
  mode?: 'weak_points' | 'random';
  title?: string;
  buttonText?: string;
  questionCount?: number;
  count?: number;
  tipText?: string;
  showInfo?: boolean;
  disabled?: boolean;
  autoNavigate?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  materialId: '',
  knowledgePointIds: () => [],
  sourceReportId: '',
  sourceType: 'weakness',
  mode: 'weak_points',
  title: '薄弱点强化练习',
  buttonText: '',
  questionCount: 10,
  count: 0,
  tipText: '',
  showInfo: false,
  disabled: false,
  autoNavigate: true,
});

const emit = defineEmits<{
  (e: 'click'): void;
  (e: 'success', session: PracticeSession): void;
  (e: 'error', error: unknown): void;
}>();

const practiceStore = usePracticeStore();
const isSubmitting = ref(false);
let lastClickTime = 0;

const countUnit = computed(() => {
  return props.sourceType === 'wrong_record' ? '道错题' : '个考点';
});

const displayButtonText = computed(() => {
  if (isSubmitting.value) {
    return '正在生成练习...';
  }
  if (props.buttonText) {
    return props.buttonText;
  }
  if (props.sourceType === 'wrong_record') {
    if (props.count > 0) {
      return `巩固已选 ${props.count} 道错题`;
    }
    return '一键巩固错题';
  }
  if (props.count > 0) {
    return `一键强化 ${props.count} 个薄弱点`;
  }
  return '一键强化薄弱点练习';
});

async function handleTap(): Promise<void> {
  if (props.disabled || isSubmitting.value) {
    return;
  }

  const now = Date.now();
  if (now - lastClickTime < 500) {
    return;
  }
  lastClickTime = now;

  emit('click');

  isSubmitting.value = true;
  const idempotencyKey = generateIdempotencyKey();

  try {
    const payload = buildContinuePracticePayload({
      materialId: props.materialId || undefined,
      knowledgePointIds: props.knowledgePointIds || [],
      sourceReportId: props.sourceReportId || undefined,
      title: props.title || '薄弱点强化练习',
      questionCount: props.questionCount,
      sourceType: props.sourceType,
      mode: props.mode,
      idempotencyKey,
    });

    const res = await continuePractice(payload);

    if (res.data?.id) {
      practiceStore.initSession(res.data.id, res.data.questions || [], {
        title: res.data.title,
        material_id: res.data.material_id,
      });
      if (props.autoNavigate) {
        uni.navigateTo({
          url: `/subpackages/practice/pages/session/index?id=${res.data.id}`,
        });
      }
      emit('success', res.data);
    } else {
      const msg = res.message || '无法创建强化练习';
      uni.showToast({ title: msg, icon: 'none' });
      emit('error', new Error(msg));
    }
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : '创建强化练习异常';
    uni.showToast({ title: errMsg, icon: 'none' });
    emit('error', err);
  } finally {
    isSubmitting.value = false;
  }
}
</script>

<style lang="scss" scoped>
@import './ContinuePracticeBar.scss';
</style>
