<template>
  <view v-if="visible" class="sheet-mask" @tap="handleCancel">
    <view class="sheet-body" @tap.stop>
      <view class="sheet-header">
        <text class="sheet-title">移动到课程</text>
        <text class="sheet-close" @tap="handleCancel">关闭</text>
      </view>

      <scroll-view scroll-y class="sheet-scroll">
        <view
          v-if="allowUnclassified"
          class="course-option"
          :class="{ active: !currentFolderId }"
          @tap="handleSelect(null)"
        >
          <text class="option-name">未分类</text>
          <text v-if="!currentFolderId" class="option-flag">当前</text>
        </view>

        <view
          v-for="folder in folders"
          :key="folder.id"
          class="course-option"
          :class="{ active: currentFolderId === folder.id }"
          @tap="handleSelect(folder.id)"
        >
          <text class="option-name">{{ folder.name }}</text>
          <text v-if="currentFolderId === folder.id" class="option-flag">当前</text>
        </view>

        <view v-if="folders.length === 0 && !allowUnclassified" class="sheet-empty">
          <text class="empty-text">暂无可用课程</text>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
import type { FolderItem } from '@/types/folder';

interface Props {
  visible?: boolean;
  folders?: FolderItem[];
  currentFolderId?: string | null;
  allowUnclassified?: boolean;
}

interface Emits {
  (e: 'update:visible', value: boolean): void;
  (e: 'select', folderId: string | null): void;
  (e: 'cancel'): void;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  folders: () => [],
  currentFolderId: null,
  allowUnclassified: true,
});

const emit = defineEmits<Emits>();

function handleSelect(folderId: string | null): void {
  if (folderId === props.currentFolderId) {
    emit('update:visible', false);
    return;
  }
  emit('select', folderId);
  emit('update:visible', false);
}

function handleCancel(): void {
  emit('update:visible', false);
  emit('cancel');
}
</script>

<style lang="scss" scoped>
.sheet-mask {
  position: fixed;
  inset: 0;
  background-color: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: flex-end;
  z-index: 200;
}

.sheet-body {
  width: 100%;
  max-height: 70vh;
  background-color: #ffffff;
  border-top-left-radius: $radius-lg;
  border-top-right-radius: $radius-lg;
  box-shadow: $shadow-sheet;
  padding: $spacing-lg $spacing-lg calc(env(safe-area-inset-bottom) + #{$spacing-lg});
  box-sizing: border-box;
}

.sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-md;
}

.sheet-title {
  font-size: $font-size-section;
  font-weight: $font-weight-bold;
  color: $--wot-color-gray-9;
}

.sheet-close {
  font-size: $font-size-caption;
  color: $--wot-color-gray-7;
}

.sheet-scroll {
  max-height: 52vh;
}

.course-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: $option-card-min-height;
  border: 1.5px solid $--wot-color-gray-4;
  border-radius: $radius-md;
  padding: 0 $spacing-lg;
  margin-bottom: $spacing-md;
  background-color: #ffffff;

  &.active {
    border-color: $--wot-color-theme;
    background-color: $--wot-color-theme-light;
  }
}

.option-name {
  font-size: $font-size-card;
  color: $--wot-color-gray-9;
  font-weight: $font-weight-medium;
}

.option-flag {
  font-size: $font-size-caption;
  color: $--wot-color-theme;
  font-weight: $font-weight-bold;
}

.sheet-empty {
  padding: $spacing-xl 0;
  text-align: center;
}

.empty-text {
  font-size: $font-size-body;
  color: $--wot-color-gray-6;
}
</style>
