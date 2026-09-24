<template>
  <view class="option-card" :class="{ selected, disabled }" @tap="handleTap">
    <!-- 左侧指示器 (单选圆圈 / 多选微圆角方框) -->
    <view class="indicator-wrapper">
      <view v-if="type === 'radio'" class="indicator indicator-radio" :class="{ active: selected }">
        <view class="indicator-inner" />
      </view>
      <view v-else class="indicator indicator-checkbox" :class="{ active: selected }">
        <view class="indicator-check-mark" />
      </view>
    </view>

    <!-- 选项标识 Key (A, B, C...) -->
    <text v-if="optionKey" class="key-label" :class="{ 'selected-key': selected }">
      {{ optionKey }}.
    </text>

    <!-- 选项正文文本 -->
    <text class="option-content" :class="{ 'selected-content': selected }">
      {{ content }}
    </text>
  </view>
</template>

<script setup lang="ts">
/**
 * OptionCard.vue
 * Reusable Option Card Component for Practice Questions.
 * Complies with docs/DESIGN.md & Spec ZL-134.
 */

interface Props {
  optionKey?: string;
  content: string;
  selected?: boolean;
  type?: 'radio' | 'checkbox';
  disabled?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  optionKey: '',
  content: '',
  selected: false,
  type: 'radio',
  disabled: false,
});

const emit = defineEmits<{
  (e: 'select', key: string): void;
}>();

function handleTap(): void {
  if (props.disabled) {
    return;
  }
  emit('select', props.optionKey);
}
</script>

<style lang="scss" scoped>
@import './OptionCard.scss';
</style>
