<template>
  <view v-if="visible" class="sheet-overlay answer-card-overlay">
    <!-- 关闭热区独立成元素：@tap.self 在小程序端被编译器丢弃，绑在容器上会导致点内容即关闭 -->
    <view class="modal-backdrop" @tap="close" />
    <view class="sheet-panel card-drawer-sheet paper-card">
      <view class="drawer-title-row">
        <text class="drawer-title">答题卡索引</text>
        <text class="modal-close" @tap="close">关闭</text>
      </view>
      <view class="grid-numbers">
        <view
          v-for="(question, idx) in questions"
          :key="question.id"
          :class="[
            'num-item',
            currentIndex === idx ? 'current' : '',
            isQuestionAnswered(question.id) ? 'answered' : '',
          ]"
          @tap="emit('jump', idx)"
        >
          {{ idx + 1 }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { isAnswered } from '@/utils/practiceHelpers'
import type { QuestionItem } from '@/types'

const props = defineProps<{
  visible: boolean
  questions: QuestionItem[]
  currentIndex: number
  userAnswers: Record<string, unknown>
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'jump', index: number): void
}>()

const isQuestionAnswered = (questionId: string) => isAnswered(props.userAnswers[questionId])
const close = () => emit('update:visible', false)
</script>

<style lang="scss" scoped>
@import '../../../styles/modal.scss';

.answer-card-overlay {
  z-index: var(--z-sheet);
}

.card-drawer-sheet {
  padding: 32rpx 32rpx calc(32rpx + env(safe-area-inset-bottom));
  max-height: 60vh;
  background: var(--color-bg-card);
}

.drawer-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 28rpx;
}

.drawer-title {
  font-size: 30rpx;
  font-weight: 700;
  color: var(--color-ink-primary);
}

.grid-numbers {
  display: flex;
  flex-wrap: wrap;
  gap: 20rpx;
}

.num-item {
  width: 80rpx;
  height: 80rpx;
  border-radius: 40rpx;
  background: var(--color-surface-muted);
  color: var(--color-ink-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
  font-weight: 600;
  border: 1px solid var(--color-paper-border);
}

.num-item.answered {
  background: var(--color-blue-bg);
  color: var(--color-academic-blue);
  border-color: var(--color-blue-border-strong);
}

.num-item.current {
  border: 2px solid var(--color-academic-blue);
  font-weight: 700;
}
</style>
