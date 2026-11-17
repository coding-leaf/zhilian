<template>
  <view class="folders-section">
    <view class="section-title-row">
      <text class="section-title">我的课程</text>
      <text class="action-text-btn" @tap="emit('create')">+ 新建课程</text>
    </view>

    <scroll-view scroll-x class="folders-scroll" :show-scrollbar="false">
      <view class="folders-tabs">
        <view
          :class="['folder-tab-pill', currentFolderId === 'all' ? 'active' : '']"
          @tap="emit('select', 'all')"
        >
          <text class="folder-tab-name">全部讲义</text>
        </view>
        <view
          v-for="folder in folders"
          :key="folder.id"
          :class="['folder-tab-pill', currentFolderId === folder.id ? 'active' : '']"
          @tap="emit('select', folder.id)"
        >
          <text class="folder-tab-name">{{ folder.name }}</text>
          <text v-if="folder.ready_material_count" class="folder-count-badge">
            {{ folder.ready_material_count }}
          </text>
        </view>
        <view
          :class="['folder-tab-pill', currentFolderId === '__none__' ? 'active' : '']"
          @tap="emit('select', '__none__')"
        >
          <text class="folder-tab-name">未分类</text>
        </view>
      </view>
    </scroll-view>

    <view v-if="activeFolder" class="folder-actions">
      <text class="folder-action" @tap="emit('rename')">重命名课程</text>
      <text class="folder-action folder-action-danger" @tap="emit('archive')">归档课程</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import type { FolderItem } from '@/types'

defineProps<{
  folders: FolderItem[]
  currentFolderId: string
  activeFolder: FolderItem | null
}>()

const emit = defineEmits<{
  (e: 'select', folderId: string): void
  (e: 'create'): void
  (e: 'rename'): void
  (e: 'archive'): void
}>()
</script>

<style lang="scss" scoped>
@import '../../../styles/common.scss';

.folders-section {
  margin-bottom: 32rpx;
}

.action-text-btn {
  font-size: 26rpx;
  font-weight: 600;
  color: var(--color-academic-blue);
}

.folders-scroll {
  white-space: nowrap;
  width: 100%;
}

.folders-tabs {
  display: inline-flex;
  gap: 16rpx;
  padding: 4rpx 0;
}

.folder-actions {
  display: flex;
  justify-content: flex-end;
  gap: 28rpx;
  padding: 14rpx 4rpx 0;
}

.folder-action {
  color: var(--color-teal-dark);
  font-size: 23rpx;
}

.folder-action-danger {
  color: var(--color-wrong);
}

.folder-tab-pill {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 12rpx 24rpx;
  background: var(--color-surface-muted);
  border-radius: 24rpx;
  border: 1px solid transparent;
  transition: all 0.2s;
}

.folder-tab-pill.active {
  background: var(--color-academic-blue);
  border-color: var(--color-academic-blue);
}

.folder-tab-name {
  font-size: 26rpx;
  color: var(--color-ink-body);
  font-weight: 500;
}

.folder-tab-pill.active .folder-tab-name {
  color: var(--color-ink-on-primary);
  font-weight: 600;
}

.folder-count-badge {
  font-size: 20rpx;
  background: var(--color-scrim-light);
  padding: 2rpx 10rpx;
  border-radius: 12rpx;
  color: var(--color-ink-subtle);
}

.folder-tab-pill.active .folder-count-badge {
  background: var(--color-white-translucent);
  color: var(--color-ink-on-primary);
}
</style>
