<template>
  <view class="guide-compare-view">
    <view v-if="comparisons.length || pitfalls.length">
      <view v-if="comparisons.length" class="compare-section">
        <text class="sec-heading">相邻易混概念对比</text>
        <view class="cards-stack">
          <view v-for="(item, idx) in comparisons" :key="idx" class="paper-card compare-card">
            <view class="compare-head">
              <text class="compare-tag">易混对比</text>
              <text class="compare-target">{{ item.target_concept }}</text>
            </view>

            <view v-if="item.similarities" class="compare-field">
              <text class="field-label">共同点</text>
              <RichContent :content="item.similarities" compact />
            </view>

            <view v-if="item.differences" class="compare-field">
              <text class="field-label">本质区别</text>
              <RichContent :content="item.differences" compact />
            </view>

            <view v-if="item.exam_distinction" class="distinction-box">
              <text class="distinction-label">考场区分口诀</text>
              <RichContent :content="item.exam_distinction" compact />
            </view>
          </view>
        </view>
      </view>

      <view v-if="pitfalls.length" class="compare-section">
        <text class="sec-heading pitfall-heading">考场高频避坑</text>
        <view class="cards-stack">
          <view v-for="(item, idx) in pitfalls" :key="idx" class="paper-card pitfall-card">
            <view v-if="item.mistake" class="pitfall-mistake">
              <text class="pitfall-tag">常见误区</text>
              <RichContent :content="item.mistake" compact />
            </view>

            <view v-if="item.why_wrong" class="pitfall-why">
              <text class="field-label">错因剖析</text>
              <RichContent :content="item.why_wrong" compact muted />
            </view>

            <view v-if="item.correction" class="pitfall-fix">
              <text class="fix-label">正确做法</text>
              <RichContent :content="item.correction" compact />
            </view>
          </view>
        </view>
      </view>
    </view>

    <view v-else class="paper-card empty-compare">
      <text class="empty-compare-title">暂无易混对比与避坑记录</text>
      <text class="empty-compare-desc">可点击右上角「重新生成」获取更完整的辨析提示，或切至「教材原文」核对细节。</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import RichContent from '@/components/RichContent.vue'
import type { StudyGuideComparison, StudyGuidePitfall } from '@/types'

defineOptions({
  options: {
    virtualHost: true,
    styleIsolation: 'apply-shared',
  },
})

defineProps<{
  comparisons: StudyGuideComparison[]
  pitfalls: StudyGuidePitfall[]
}>()
</script>

<style lang="scss" scoped>
@import '../../../styles/tokens.scss';

.guide-compare-view { display: flex; flex-direction: column; }
.compare-section { margin-bottom: 28rpx; }
.sec-heading {
  display: block; font-size: 27rpx; font-weight: 700;
  color: $color-ink-primary; margin-bottom: 12rpx;
}
.pitfall-heading { color: var(--color-danger-strong); }
.cards-stack { display: flex; flex-direction: column; gap: 16rpx; }
.compare-card { padding: 22rpx; }
.compare-head { display: flex; align-items: center; gap: 12rpx; margin-bottom: 14rpx; }
.compare-tag {
  font-size: 20rpx; font-weight: 600; color: $color-academic-blue;
  background: $color-blue-bg; border: 1px solid $color-blue-border;
  padding: 2rpx 12rpx; border-radius: 999rpx; flex-shrink: 0;
}
.compare-target { flex: 1; min-width: 0; font-size: 27rpx; font-weight: 700; color: $color-ink-primary; }
.compare-field { margin-bottom: 12rpx; }
.field-label {
  display: block; font-size: 22rpx; font-weight: 700;
  color: $color-ink-subtle; margin-bottom: 4rpx;
}
.distinction-box {
  background: var(--color-teal-bg); border: 1px solid $color-paper-border;
  border-radius: 10rpx; padding: 14rpx 16rpx;
}
.distinction-label {
  display: block; font-size: 22rpx; font-weight: 700;
  color: var(--color-teal-dark); margin-bottom: 4rpx;
}
.pitfall-card { padding: 22rpx; border-color: var(--color-danger-border); }
.pitfall-mistake {
  background: $color-danger-bg; border-radius: 10rpx; padding: 14rpx 16rpx; margin-bottom: 12rpx;
}
.pitfall-tag {
  display: inline-block; font-size: 20rpx; font-weight: 700; color: $color-wrong;
  background: var(--color-danger-bg-soft); padding: 2rpx 10rpx; border-radius: 6rpx; margin-bottom: 6rpx;
}
.pitfall-why { margin-bottom: 12rpx; }
.pitfall-fix {
  background: var(--color-success-bg-soft); border: 1px solid var(--color-success-border);
  border-radius: 10rpx; padding: 14rpx 16rpx;
}
.fix-label {
  display: block; font-size: 22rpx; font-weight: 700;
  color: var(--color-success-strong); margin-bottom: 4rpx;
}
.empty-compare { padding: 52rpx 28rpx; text-align: center; }
.empty-compare-title { display: block; font-size: 28rpx; font-weight: 700; color: $color-ink-secondary; }
.empty-compare-desc { display: block; font-size: 24rpx; color: $color-ink-muted; margin-top: 10rpx; line-height: 1.5; }
</style>
