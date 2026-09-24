<template>
  <view class="practice-header">
    <!-- 左侧：退出按钮 -->
    <view class="header-action header-exit" @tap="handleExit">
      <text class="action-text">退出</text>
    </view>

    <!-- 中间：标题与进度时间信息 -->
    <view class="header-center">
      <text class="practice-title">{{ title }}</text>
      <view class="meta-capsule">
        <text class="progress-badge">{{ displayProgress }}</text>
        <text class="capsule-divider">|</text>
        <text class="timer-text">{{ formattedTime }}</text>
      </view>
    </view>

    <!-- 右侧：答题卡入口 -->
    <view class="header-action header-sheet" @tap="handleOpenSheet">
      <text class="action-text sheet-text">答题卡</text>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * PracticeHeader.vue
 * Practice Header component showing progress, timer, exit and sheet entry.
 * Reference: docs/sdlc/ZL-134/spec.md
 * Zero-Emoji Policy enforced.
 */

import { computed } from 'vue';
import { formatDurationSeconds } from '../utils/draft';

interface Props {
  title?: string;
  currentIndex?: number;
  totalQuestions?: number;
  elapsedSeconds?: number;
}

const props = withDefaults(defineProps<Props>(), {
  title: '练习作答',
  currentIndex: 0,
  totalQuestions: 0,
  elapsedSeconds: 0,
});

const emit = defineEmits<{
  (e: 'open-sheet'): void;
  (e: 'exit'): void;
}>();

const displayProgress = computed<string>(() => {
  const current = props.totalQuestions > 0 ? props.currentIndex + 1 : 0;
  return `${current}/${props.totalQuestions}`;
});

const formattedTime = computed<string>(() => {
  return formatDurationSeconds(props.elapsedSeconds);
});

function handleExit(): void {
  emit('exit');
}

function handleOpenSheet(): void {
  emit('open-sheet');
}
</script>

<style lang="scss" scoped>
@import './PracticeHeader.scss';
</style>
