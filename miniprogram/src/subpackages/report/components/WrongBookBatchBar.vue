<template>
  <view class="batch-action-bar">
    <view class="batch-left">
      <view class="batch-select-btn" @tap="$emit('toggle-select-all')">
        <view class="select-box" :class="{ checked: allSelected }">
          <view v-if="allSelected" class="check-dot" />
        </view>
        <text>{{ allSelected ? '取消全选' : '全选本页' }}</text>
      </view>
      <text class="selected-count-tip">
        已选 <text class="num">{{ selectedCount }}</text> 道
      </text>
    </view>

    <view v-if="selectedCount > 0" class="batch-right">
      <view class="clear-btn" @tap="$emit('clear')">
        <text>清空选择</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * WrongBookBatchBar.vue
 * Batch selection toolbar for wrong book items.
 * Complies with docs/DESIGN.md & spec ZL-136.
 * Zero-Emoji Policy enforced.
 */

defineProps<{
  allSelected: boolean;
  selectedCount: number;
}>();

defineEmits<{
  (e: 'toggle-select-all'): void;
  (e: 'clear'): void;
}>();
</script>

<style lang="scss" scoped>
@import './WrongBookBatchBar.scss';
</style>
