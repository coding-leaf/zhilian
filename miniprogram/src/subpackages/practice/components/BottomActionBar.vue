<template>
  <view class="bottom-action-bar">
    <view class="action-container">
      <!-- 上一题按钮 -->
      <button
        class="action-btn btn-prev"
        :class="{ disabled: isPrevDisabled }"
        :disabled="isPrevDisabled"
        @tap="handlePrev"
      >
        上一题
      </button>

      <!-- 交卷按钮 -->
      <button
        class="action-btn btn-submit"
        :class="{
          disabled: isSubmitting,
          'btn-primary': isLastQuestion,
          'btn-secondary': !isLastQuestion,
        }"
        :disabled="isSubmitting"
        @tap="handleSubmit"
      >
        {{ isSubmitting ? '提交中...' : '交卷' }}
      </button>

      <!-- 下一题按钮 -->
      <button
        class="action-btn btn-next"
        :class="{
          disabled: isNextDisabled,
          'btn-primary': !isLastQuestion,
          'btn-secondary': isLastQuestion,
        }"
        :disabled="isNextDisabled"
        @tap="handleNext"
      >
        下一题
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * BottomActionBar.vue
 * Floating bottom action bar with Prev, Next and Submit buttons.
 * Reference: docs/sdlc/ZL-134/spec.md
 * Zero-Emoji Policy enforced.
 */

import { computed } from 'vue';

interface Props {
  currentIndex?: number;
  totalCount?: number;
  isSubmitting?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  currentIndex: 0,
  totalCount: 0,
  isSubmitting: false,
});

const emit = defineEmits<{
  (e: 'prev'): void;
  (e: 'next'): void;
  (e: 'submit'): void;
}>();

const isPrevDisabled = computed<boolean>(() => {
  return props.currentIndex <= 0 || props.isSubmitting;
});

const isNextDisabled = computed<boolean>(() => {
  return props.currentIndex >= props.totalCount - 1 || props.isSubmitting;
});

const isLastQuestion = computed<boolean>(() => {
  return props.totalCount > 0 && props.currentIndex >= props.totalCount - 1;
});

function handlePrev(): void {
  if (isPrevDisabled.value) {
    return;
  }
  emit('prev');
}

function handleNext(): void {
  if (isNextDisabled.value) {
    return;
  }
  emit('next');
}

function handleSubmit(): void {
  if (props.isSubmitting) {
    return;
  }
  emit('submit');
}
</script>

<style lang="scss" scoped>
@import './BottomActionBar.scss';
</style>
