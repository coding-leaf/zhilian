<template>
  <view class="guide-note-view">
    <view v-if="hasAnySection">
      <view v-if="guide.exam_positioning" class="guide-section">
        <text class="sec-heading">考法与直觉定位</text>
        <view class="paper-card block-card positioning-card">
          <RichContent :content="guide.exam_positioning" />
        </view>
      </view>

      <view v-if="guide.core_definition" class="guide-section">
        <text class="sec-heading">完整定义与直觉</text>
        <view class="paper-card block-card">
          <RichContent :content="guide.core_definition" />
        </view>
      </view>

      <view v-if="guide.symbol_table.length" class="guide-section">
        <text class="sec-heading">核心符号速查表</text>
        <view class="paper-card symbol-table-card">
          <view v-for="(row, idx) in guide.symbol_table" :key="idx" class="symbol-row">
            <view class="symbol-col">
              <RichContent :content="row.symbol" compact />
            </view>
            <view class="meaning-col">
              <text class="meaning-text">{{ row.meaning }}</text>
              <view v-if="row.note" class="symbol-note">
                <RichContent :content="row.note" compact muted />
              </view>
            </view>
          </view>
        </view>
      </view>

      <view v-if="guide.key_formulas.length" class="guide-section">
        <text class="sec-heading">核心结论公式</text>
        <view v-for="(formula, idx) in guide.key_formulas" :key="idx" class="formula-box">
          <RichContent :content="formula" />
        </view>
      </view>

      <view v-if="guide.derivation_steps.length" class="guide-section">
        <text class="sec-heading">逐步推导与流程链</text>
        <view class="derivation-stack">
          <view v-for="(step, idx) in guide.derivation_steps" :key="idx" class="paper-card step-card">
            <view class="step-head">
              <text class="step-badge">{{ idx + 1 }}</text>
              <text class="step-title">{{ step.step_title || `第 ${idx + 1} 步` }}</text>
            </view>
            <view v-if="step.formula" class="step-formula">
              <RichContent :content="step.formula" />
            </view>
            <view v-if="step.explanation" class="step-desc">
              <RichContent :content="step.explanation" compact />
            </view>
          </view>
        </view>
      </view>

      <view v-if="guide.memory_anchors.length" class="guide-section">
        <text class="sec-heading">30 秒考前速记锚点</text>
        <view class="anchor-card">
          <view v-for="(anchor, idx) in guide.memory_anchors" :key="idx" class="anchor-row">
            <view class="anchor-dot" />
            <view class="anchor-body">
              <RichContent :content="anchor" compact />
            </view>
          </view>
        </view>
      </view>
    </view>

    <view v-else class="paper-card empty-block">
      <text class="empty-block-text">当前考点精讲笔记内容为空，可点击右上角「重新生成」。</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RichContent from '@/components/RichContent.vue'
import type { StudyGuideContent } from '@/types'

defineOptions({
  options: {
    virtualHost: true,
    styleIsolation: 'apply-shared',
  },
})

const props = defineProps<{
  guide: StudyGuideContent
}>()

const hasAnySection = computed(() =>
  Boolean(
    props.guide.exam_positioning
    || props.guide.core_definition
    || props.guide.symbol_table.length
    || props.guide.key_formulas.length
    || props.guide.derivation_steps.length
    || props.guide.memory_anchors.length,
  ),
)
</script>

<style lang="scss" scoped>
@import '../../../styles/tokens.scss';

.guide-note-view { display: flex; flex-direction: column; }
.guide-section { margin-bottom: 28rpx; }
.sec-heading {
  display: block; font-size: 27rpx; font-weight: 700;
  color: $color-ink-primary; margin-bottom: 12rpx;
}
.block-card { padding: 22rpx 24rpx; }
.positioning-card { background: var(--color-surface-warm); border-color: var(--color-blue-border); }
.symbol-table-card { padding: 8rpx 22rpx; }
.symbol-row {
  display: flex; align-items: flex-start; gap: 18rpx;
  padding: 16rpx 0; border-bottom: 1px solid $color-surface-muted;
}
.symbol-row:last-child { border-bottom: none; }
.symbol-col {
  width: 150rpx; flex-shrink: 0; padding: 6rpx 10rpx;
  background: $color-surface-subtle; border-radius: 8rpx;
}
.meaning-col { flex: 1; min-width: 0; }
.meaning-text { display: block; font-size: 25rpx; color: $color-ink-primary; line-height: 1.5; }
.symbol-note { margin-top: 6rpx; }
.formula-box {
  background: $color-blue-bg; border: 1px solid $color-blue-border;
  border-radius: 12rpx; padding: 18rpx 22rpx; margin-bottom: 12rpx; overflow-x: auto;
}
.derivation-stack { display: flex; flex-direction: column; gap: 14rpx; }
.step-card { padding: 20rpx 22rpx; }
.step-head { display: flex; align-items: center; gap: 12rpx; margin-bottom: 10rpx; }
.step-badge {
  width: 38rpx; height: 38rpx; border-radius: 999rpx; background: $color-academic-teal;
  color: $color-ink-on-primary; font-size: 22rpx; font-weight: 700;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.step-title { flex: 1; min-width: 0; font-size: 26rpx; font-weight: 700; color: $color-ink-primary; }
.step-formula {
  background: var(--color-surface-slate); border-radius: 8rpx;
  padding: 14rpx 16rpx; margin-bottom: 10rpx; overflow-x: auto;
}
.step-desc { padding-left: 4rpx; }
.anchor-card {
  background: $color-warning-bg; border: 1px solid var(--color-warning-border);
  border-radius: 14rpx; padding: 20rpx 22rpx; display: flex; flex-direction: column; gap: 12rpx;
}
.anchor-row { display: flex; align-items: flex-start; gap: 12rpx; }
.anchor-dot {
  width: 10rpx; height: 10rpx; border-radius: 999rpx;
  background: $color-warm-amber; margin-top: 14rpx; flex-shrink: 0;
}
.anchor-body { flex: 1; min-width: 0; }
.empty-block { padding: 48rpx 28rpx; text-align: center; }
.empty-block-text { font-size: 25rpx; color: $color-ink-muted; }
</style>
