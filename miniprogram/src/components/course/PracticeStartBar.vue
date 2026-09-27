<template>
  <view class="practice-start-bar">
    <view class="bar-info">
      <text class="bar-count">共 {{ total }} 题</text>
      <text class="bar-tip">{{ tipText }}</text>
    </view>
    <button
      class="start-btn"
      :class="{ disabled: isDisabled }"
      :disabled="isDisabled"
      @tap="handleTap"
    >
      {{ displayText }}
    </button>
  </view>
</template>

<script setup lang="ts">
/**
 * PracticeStartBar.vue
 * Sticky bottom action bar for starting a course-scoped practice.
 * Presentation only: parent owns the createPractice side effect.
 * Zero-Emoji policy enforced; lines <= 300.
 */

import { computed } from 'vue';

interface Props {
  total?: number;
  starting?: boolean;
  disabled?: boolean;
  tipText?: string;
}

const props = withDefaults(defineProps<Props>(), {
  total: 0,
  starting: false,
  disabled: false,
  tipText: '从本课程题库智能组卷',
});

const emit = defineEmits<{
  (e: 'start'): void;
}>();

const isDisabled = computed<boolean>(() => props.disabled || props.starting || props.total <= 0);

const displayText = computed<string>(() => {
  if (props.starting) return '正在组卷...';
  return '开始答题';
});

function handleTap(): void {
  if (isDisabled.value) return;
  emit('start');
}

defineExpose({ isDisabled, displayText, handleTap });
</script>

<style lang="scss" scoped>
@import './PracticeStartBar.scss';
</style>
