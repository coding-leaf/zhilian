<template>
  <view v-if="visible" class="sheet-mask" @tap="handleClose">
    <view class="sheet-drawer" @tap.stop>
      <!-- 头部：标题与关闭 -->
      <view class="sheet-header">
        <view class="header-left">
          <text class="title">答题卡</text>
          <text class="subtitle">已完成 {{ answeredCount }}/{{ totalCount }}</text>
        </view>
        <view class="close-btn" @tap="handleClose">关闭</view>
      </view>

      <!-- 状态图例 -->
      <view class="sheet-legend">
        <view class="legend-item">
          <view class="legend-dot legend-current" />
          <text class="legend-text">当前题</text>
        </view>
        <view class="legend-item">
          <view class="legend-dot legend-answered" />
          <text class="legend-text">已作答</text>
        </view>
        <view class="legend-item">
          <view class="legend-dot legend-unanswered" />
          <text class="legend-text">未作答</text>
        </view>
      </view>

      <!-- 题号网格 -->
      <scroll-view class="sheet-scroll" scroll-y>
        <view class="sheet-grid">
          <view
            v-for="(qid, index) in questionList"
            :key="qid"
            class="sheet-cell"
            :class="getCellStatusClass(index, qid)"
            @tap="handleSelectQuestion(index)"
          >
            {{ index + 1 }}
          </view>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * AnswerSheetDrawer.vue
 * Answer sheet drawer component with 3-state cell matrix.
 * Reference: docs/sdlc/ZL-134/spec.md
 * Zero-Emoji Policy enforced.
 */

import { computed } from 'vue';
import { isAnswerFilled } from '../utils/draft';

interface Props {
  visible?: boolean;
  totalCount?: number;
  currentIndex?: number;
  answers?: Record<string, unknown>;
  questionIds?: string[];
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  totalCount: 0,
  currentIndex: 0,
  answers: () => ({}),
  questionIds: () => [],
});

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void;
  (e: 'select', targetIndex: number): void;
}>();

const questionList = computed<string[]>(() => {
  if (props.questionIds && props.questionIds.length > 0) {
    return props.questionIds;
  }
  // Fallback to synthetic indices if ids not explicitly provided
  return Array.from({ length: props.totalCount }, (_, i) => String(i));
});

const answeredCount = computed<number>(() => {
  let count = 0;
  for (const qid of questionList.value) {
    if (isAnswerFilled(props.answers[qid])) {
      count += 1;
    }
  }
  return count;
});

function getCellStatusClass(index: number, qid: string): string {
  if (index === props.currentIndex) {
    return 'cell-current';
  }
  const ans = props.answers[qid];
  if (isAnswerFilled(ans)) {
    return 'cell-answered';
  }
  return 'cell-unanswered';
}

function handleSelectQuestion(index: number): void {
  emit('select', index);
  emit('update:visible', false);
}

function handleClose(): void {
  emit('update:visible', false);
}
</script>

<style lang="scss" scoped>
@import './AnswerSheetDrawer.scss';
</style>
