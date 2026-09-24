<template>
  <view v-if="visible" class="modal-mask" @tap="handleClose">
    <view class="modal-card" @tap.stop>
      <!-- 弹窗标题 -->
      <view class="modal-header">
        <text class="modal-title">交卷确认</text>
      </view>

      <!-- 作答统计数据概览 -->
      <view class="stats-summary">
        <view class="stat-item">
          <text class="stat-num">{{ totalCount }}</text>
          <text class="stat-label">总题数</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-item">
          <text class="stat-num num-success">{{ answeredCount }}</text>
          <text class="stat-label">已作答</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-item">
          <text class="stat-num" :class="{ 'num-warning': hasUnanswered }">
            {{ unansweredCount }}
          </text>
          <text class="stat-label">未作答</text>
        </view>
      </view>

      <!-- 1. 存在未答题目阻断警示 -->
      <view v-if="hasUnanswered" class="unanswered-alert">
        <text class="alert-text">
          尚有 {{ unansweredCount }} 道题目未作答，直接交卷将按未作答计分。
        </text>
        <view class="unanswered-chips">
          <view
            v-for="idx in unansweredIndices"
            :key="idx"
            class="chip-item"
            @tap="handleLocate(idx - 1)"
          >
            第 {{ idx }} 题
          </view>
        </view>
      </view>

      <!-- 2. 全部作答完成提示 -->
      <view v-else class="complete-tip">
        <text class="tip-text">已完成全部题目作答，确认交卷吗？</text>
      </view>

      <!-- 操作按钮栏 -->
      <view class="modal-actions">
        <view class="btn btn-secondary" :class="{ disabled: submitting }" @tap="handleCancel">
          {{ hasUnanswered ? '继续作答' : '再检查一下' }}
        </view>
        <view
          class="btn btn-primary"
          :class="{
            disabled: submitting,
            'btn-warning-submit': hasUnanswered,
          }"
          @tap="handleConfirm"
        >
          {{ submitting ? '交卷中...' : hasUnanswered ? '仍要交卷' : '确认交卷' }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * SubmitConfirmModal.vue
 * Submission Confirmation Modal with Unanswered Questions Blocking.
 * Reference: docs/sdlc/ZL-134/spec.md
 * Zero-Emoji Policy enforced.
 */

import { computed } from 'vue';

interface Props {
  visible?: boolean;
  totalCount?: number;
  answeredCount?: number;
  unansweredIndices?: number[];
  submitting?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  totalCount: 0,
  answeredCount: 0,
  unansweredIndices: () => [],
  submitting: false,
});

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void;
  (e: 'confirm', payload: { confirm_unanswered: boolean }): void;
  (e: 'locate-unanswered', targetIndex: number): void;
}>();

const unansweredCount = computed<number>(() => {
  if (props.unansweredIndices && props.unansweredIndices.length > 0) {
    return props.unansweredIndices.length;
  }
  return Math.max(0, props.totalCount - props.answeredCount);
});

const hasUnanswered = computed<boolean>(() => unansweredCount.value > 0);

function handleCancel(): void {
  if (props.submitting) {
    return;
  }
  emit('update:visible', false);
}

function handleClose(): void {
  handleCancel();
}

function handleLocate(targetIndex: number): void {
  if (props.submitting) {
    return;
  }
  emit('locate-unanswered', targetIndex);
  emit('update:visible', false);
}

function handleConfirm(): void {
  if (props.submitting) {
    return;
  }
  emit('confirm', {
    confirm_unanswered: hasUnanswered.value,
  });
}
</script>

<style lang="scss" scoped>
@import './SubmitConfirmModal.scss';
</style>
