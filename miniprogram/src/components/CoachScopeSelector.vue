<template>
  <view class="scope-selector">
    <view class="scope-mode-row">
      <text class="scope-mode-tag">{{ selectedFolder ? '限定课程' : '全局模式' }}</text>
      <text class="scope-mode-label">{{ modeLabel }}</text>
    </view>
    <scroll-view scroll-x class="scope-scroll" :show-scrollbar="false">
      <view class="scope-pills">
        <view
          :class="['scope-pill', !selectedFolderId ? 'active' : '']"
          @tap="emit('select', undefined)"
        >
          <text class="scope-pill-text">全部资料 · 全局</text>
        </view>
        <view
          v-for="folder in folders"
          :key="folder.id"
          :class="['scope-pill', selectedFolderId === folder.id ? 'active' : '']"
          @tap="emit('select', folder.id)"
        >
          <text class="scope-pill-text">{{ folder.name }}</text>
          <text v-if="folder.ready_material_count > 0" class="scope-pill-badge">
            {{ folder.ready_material_count }}
          </text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { FolderItem } from '@/types'

defineOptions({ options: { virtualHost: true } })

const props = defineProps<{
  folders: FolderItem[]
  selectedFolderId?: string
}>()

const emit = defineEmits<{
  (e: 'select', folderId?: string): void
}>()

const selectedFolder = computed<FolderItem | null>(() => {
  if (!props.selectedFolderId) return null
  return props.folders.find((folder) => folder.id === props.selectedFolderId) ?? null
})

const modeLabel = computed(() => {
  if (selectedFolder.value) {
    return `聚焦课程「${selectedFolder.value.name}」· 仅检索本课程 ${selectedFolder.value.ready_material_count} 份就绪资料`
  }
  return '全局学习模式（未限定课程）'
})
</script>

<style lang="scss" scoped>
.scope-selector {
  padding: 12rpx 28rpx 14rpx;
  background: var(--color-surface-slate);
  border-bottom: 1px solid var(--color-paper-border);
  flex-shrink: 0;
}
.scope-mode-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
  margin-bottom: 10rpx;
}
.scope-mode-tag {
  font-size: 20rpx;
  font-weight: 600;
  color: var(--color-academic-blue);
  background: var(--color-blue-bg);
  border: 1px solid var(--color-blue-border);
  padding: 2rpx 10rpx;
  border-radius: 6rpx;
  flex-shrink: 0;
}
.scope-mode-label {
  flex: 1;
  min-width: 0;
  font-size: 22rpx;
  color: var(--color-ink-slate-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scope-scroll {
  width: 100%;
  white-space: nowrap;
}
.scope-pills {
  display: inline-flex;
  gap: 12rpx;
  padding: 2rpx 0;
}
.scope-pill {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 8rpx 20rpx;
  border-radius: 999rpx;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-paper-border);
}
.scope-pill.active {
  background: var(--color-academic-blue);
  border-color: var(--color-academic-blue);
}
.scope-pill-text {
  font-size: 23rpx;
  font-weight: 500;
  color: var(--color-ink-body);
}
.scope-pill.active .scope-pill-text {
  color: var(--color-ink-on-primary);
  font-weight: 600;
}
.scope-pill-badge {
  font-size: 19rpx;
  padding: 2rpx 8rpx;
  border-radius: 10rpx;
  background: var(--color-scrim-light);
  color: var(--color-ink-subtle);
}
.scope-pill.active .scope-pill-badge {
  background: var(--color-white-translucent);
  color: var(--color-ink-on-primary);
}
</style>
