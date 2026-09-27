<template>
  <view class="archived-item">
    <view class="archived-info">
      <text class="archived-name">{{ folder.name }}</text>
      <text class="archived-remaining">{{ remainingText }}</text>
    </view>
    <button class="restore-btn" @tap="handleRestore">恢复</button>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { FolderItem } from '@/types/folder';
import { formatPurgeRemaining } from '@/utils/purgeTime';

defineOptions({ name: 'ArchivedCourseItem' });

interface Props {
  folder: FolderItem;
  now?: Date;
}

interface Emits {
  (e: 'restore', folder: FolderItem): void;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const remainingText = computed(() => formatPurgeRemaining(props.folder.purge_after, props.now));

function handleRestore(): void {
  emit('restore', props.folder);
}
</script>

<style lang="scss" scoped>
.archived-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: $--wot-color-gray-2;
  border: 1px solid $--wot-color-gray-4;
  border-radius: $radius-md;
  padding: $spacing-md $spacing-lg;
  margin-bottom: $spacing-md;
}

.archived-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  margin-right: $spacing-md;
}

.archived-name {
  font-size: $font-size-card;
  font-weight: $font-weight-bold;
  color: $--wot-color-gray-8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.archived-remaining {
  font-size: $font-size-caption;
  color: $--wot-color-warning-text;
  margin-top: 4rpx;
}

.restore-btn {
  min-height: 56rpx;
  padding: 0 $spacing-lg;
  font-size: $font-size-caption;
  font-weight: $font-weight-bold;
  border-radius: $radius-pill;
  background-color: $--wot-color-theme-light;
  color: $--wot-color-theme;
  border: 1px solid $--wot-color-theme-border;
  line-height: 1.5;
  margin: 0;
}
</style>
