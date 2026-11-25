<template>
  <view class="guide-examples-view">
    <view v-if="examples.length" class="examples-stack">
      <view v-for="(item, idx) in examples" :key="idx" class="paper-card example-card">
        <view class="example-header">
          <text class="example-title">{{ item.title || `典型例题 ${idx + 1}` }}</text>
          <text v-if="item.question_type" class="example-type-tag">{{ item.question_type }}</text>
        </view>

        <view class="example-problem">
          <RichContent :content="item.problem" />
        </view>

        <view v-if="item.solution_idea" class="idea-box">
          <text class="idea-label">解题切入点</text>
          <RichContent :content="item.solution_idea" compact />
        </view>

        <button class="solution-toggle-btn" @tap="toggleExample(idx)">
          {{ isExpanded(idx) ? '收起标准解答' : '展开分步标准解答' }}
        </button>

        <view v-if="isExpanded(idx)" class="solution-panel">
          <view v-if="item.solution_steps.length" class="solution-steps">
            <text class="solution-subhead">分步标准解答</text>
            <view v-for="(step, sIdx) in item.solution_steps" :key="sIdx" class="sol-step-row">
              <text class="sol-step-num">{{ sIdx + 1 }}</text>
              <view class="sol-step-body">
                <RichContent :content="step" compact />
              </view>
            </view>
          </view>

          <view v-if="item.final_answer" class="final-answer-box">
            <text class="final-answer-label">最终答案</text>
            <RichContent :content="item.final_answer" />
          </view>
        </view>
      </view>
    </view>

    <view v-else class="paper-card empty-examples">
      <text class="empty-examples-title">暂无典型例题</text>
      <text class="empty-examples-desc">本考点精讲未附带例题，可点击底部「针对此考点出题」生成专项练习。</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import RichContent from '@/components/RichContent.vue'
import type { StudyGuideWorkedExample } from '@/types'

defineOptions({
  options: {
    virtualHost: true,
    styleIsolation: 'apply-shared',
  },
})

const props = defineProps<{
  examples: StudyGuideWorkedExample[]
}>()

const expandedMap = ref<Record<number, boolean>>({})

watch(
  () => props.examples,
  () => {
    expandedMap.value = {}
  },
)

const isExpanded = (idx: number): boolean => Boolean(expandedMap.value[idx])

const toggleExample = (idx: number) => {
  expandedMap.value = {
    ...expandedMap.value,
    [idx]: !expandedMap.value[idx],
  }
}
</script>

<style lang="scss" scoped>
@import '../../../styles/tokens.scss';

.guide-examples-view { display: flex; flex-direction: column; }
.examples-stack { display: flex; flex-direction: column; gap: 20rpx; }
.example-card { padding: 24rpx; }
.example-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 14rpx; margin-bottom: 14rpx;
}
.example-title {
  flex: 1; min-width: 0; font-size: 28rpx; font-weight: 700;
  color: $color-ink-primary; line-height: 1.4;
}
.example-type-tag {
  font-size: 21rpx; font-weight: 600; color: $color-academic-blue;
  background: $color-blue-bg; border: 1px solid $color-blue-border;
  padding: 4rpx 14rpx; border-radius: 999rpx; flex-shrink: 0;
}
.example-problem {
  background: $color-surface-subtle; border: 1px solid $color-paper-border;
  border-radius: 10rpx; padding: 18rpx 20rpx; margin-bottom: 14rpx;
}
.idea-box {
  background: var(--color-teal-bg); border-left: 4rpx solid $color-academic-teal;
  border-radius: 8rpx; padding: 14rpx 18rpx; margin-bottom: 16rpx;
}
.idea-label {
  display: block; font-size: 22rpx; font-weight: 700;
  color: var(--color-teal-dark); margin-bottom: 6rpx;
}
.solution-toggle-btn {
  width: 100%; height: 72rpx; margin: 0; line-height: 1.4;
  background: $color-blue-bg; color: $color-academic-blue;
  border: 1px solid $color-blue-border; border-radius: 10rpx;
  font-size: 25rpx; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  &::after { border: none; }
}
.solution-panel {
  margin-top: 16rpx; padding-top: 16rpx; border-top: 1px dashed $color-paper-border;
}
.solution-steps { display: flex; flex-direction: column; gap: 12rpx; margin-bottom: 16rpx; }
.solution-subhead { font-size: 24rpx; font-weight: 700; color: $color-ink-secondary; }
.sol-step-row { display: flex; align-items: flex-start; gap: 12rpx; }
.sol-step-num {
  width: 34rpx; height: 34rpx; border-radius: 999rpx; background: $color-academic-blue;
  color: $color-ink-on-primary; font-size: 20rpx; font-weight: 700;
  display: flex; align-items: center; justify-content: center; margin-top: 4rpx; flex-shrink: 0;
}
.sol-step-body { flex: 1; min-width: 0; }
.final-answer-box {
  background: var(--color-success-bg-soft); border: 1px solid var(--color-success-border);
  border-radius: 10rpx; padding: 16rpx 18rpx;
}
.final-answer-label {
  display: block; font-size: 22rpx; font-weight: 700;
  color: var(--color-success-strong); margin-bottom: 6rpx;
}
.empty-examples { padding: 52rpx 28rpx; text-align: center; }
.empty-examples-title { display: block; font-size: 28rpx; font-weight: 700; color: $color-ink-secondary; }
.empty-examples-desc { display: block; font-size: 24rpx; color: $color-ink-muted; margin-top: 10rpx; line-height: 1.5; }
</style>
