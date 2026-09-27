<template>
  <view class="course-card" role="button" :aria-label="folder.name" @tap="handleEnter">
    <view class="course-head">
      <view class="course-badge">{{ initial }}</view>
      <view class="course-title-wrap">
        <text class="course-name">{{ folder.name }}</text>
        <text class="course-meta">{{ metaText }}</text>
      </view>
      <view class="enter-pill">
        <text class="enter-text">进入</text>
      </view>
    </view>

    <view class="course-stats">
      <view class="stat-item">
        <text class="stat-num">{{ folder.material_count }}</text>
        <text class="stat-label">资料</text>
      </view>
      <view class="stat-item">
        <text class="stat-num">{{ folder.knowledge_point_count }}</text>
        <text class="stat-label">考点</text>
      </view>
      <view class="stat-item">
        <text class="stat-num">{{ folder.question_count }}</text>
        <text class="stat-label">题目</text>
      </view>
    </view>

    <view class="course-actions">
      <text class="action-link" @tap.stop="handleRename">重命名</text>
      <text class="action-link danger" @tap.stop="handleArchive">归档</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { FolderItem } from '@/types/folder';

defineOptions({ name: 'CourseCard' });

interface Props {
  folder: FolderItem;
}

interface Emits {
  (e: 'enter', folder: FolderItem): void;
  (e: 'rename', folder: FolderItem): void;
  (e: 'archive', folder: FolderItem): void;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const initial = computed(() => (props.folder.name || '课').slice(0, 1));

const metaText = computed(() => {
  const raw = props.folder.last_practice_at;
  if (!raw) {
    return `${props.folder.ready_material_count} 份已就绪`;
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return '最近有练习';
  }
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `最近练习 ${month}-${day}`;
});

function handleEnter(): void {
  emit('enter', props.folder);
}

function handleRename(): void {
  emit('rename', props.folder);
}

function handleArchive(): void {
  emit('archive', props.folder);
}
</script>

<style lang="scss" scoped src="./CourseCard.scss"></style>
