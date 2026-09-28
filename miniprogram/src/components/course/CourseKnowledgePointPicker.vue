<template>
  <view class="kp-picker">
    <view class="kp-head">
      <text class="section-label">考点范围（可选）</text>
      <text class="kp-summary">{{ summaryText }}</text>
    </view>

    <view v-if="loading" class="kp-state">正在加载考点...</view>

    <view v-else-if="error" class="kp-state kp-error">
      <text class="kp-error-text">考点加载失败</text>
      <text class="kp-retry" @tap="loadPoints">重新加载</text>
    </view>

    <view v-else-if="groups.length === 0" class="kp-state">
      课程暂无可用考点，将按课程全部考点出题
    </view>

    <scroll-view v-else scroll-y class="kp-scroll">
      <view v-for="group in groups" :key="group.material_id" class="kp-group">
        <view class="kp-group-head" @tap="toggleGroup(group)">
          <text class="kp-group-title">{{ group.material_title }}</text>
          <text class="kp-group-action">{{ groupFullySelected(group) ? '取消全选' : '全选' }}</text>
        </view>
        <view
          v-for="point in group.knowledge_points"
          :key="point.id"
          class="kp-item"
          :class="{ active: selectedSet.has(point.id) }"
          @tap="togglePoint(point.id)"
        >
          <view class="kp-box" :class="{ checked: selectedSet.has(point.id) }" />
          <text class="kp-name">{{ point.name }}</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
/**
 * CourseKnowledgePointPicker.vue
 * Course-scoped knowledge point picker grouped by source material.
 * Selected ids are surfaced via `update:selectedIds`; an empty selection means
 * "use the whole course scope" (backend default). Zero-Emoji; lines <= 300.
 */

import { ref, computed, watch } from 'vue';
import { fetchFolderKnowledgePoints } from '@/api/folder';
import type { FolderKnowledgePointGroup } from '@/types/folder';

interface Props {
  folderId?: string;
  selectedIds?: string[];
}

interface Emits {
  (e: 'update:selectedIds', ids: string[]): void;
}

const props = withDefaults(defineProps<Props>(), {
  folderId: '',
  selectedIds: () => [],
});

const emit = defineEmits<Emits>();

const groups = ref<FolderKnowledgePointGroup[]>([]);
const loading = ref(false);
const error = ref(false);

const selectedSet = computed<Set<string>>(() => new Set(props.selectedIds));

const summaryText = computed<string>(() => {
  if (selectedSet.value.size === 0) {
    return '默认：课程全部考点';
  }
  return `已选 ${selectedSet.value.size} 个考点，仅出所选考点`;
});

async function loadPoints(): Promise<void> {
  if (!props.folderId) {
    return;
  }
  loading.value = true;
  try {
    const res = await fetchFolderKnowledgePoints(props.folderId);
    groups.value = res?.data?.groups ?? [];
    error.value = false;
  } catch {
    error.value = true;
    groups.value = [];
  } finally {
    loading.value = false;
  }
}

function togglePoint(pointId: string): void {
  const next = new Set(props.selectedIds);
  if (next.has(pointId)) {
    next.delete(pointId);
  } else {
    next.add(pointId);
  }
  emit('update:selectedIds', Array.from(next));
}

function groupFullySelected(group: FolderKnowledgePointGroup): boolean {
  return (
    group.knowledge_points.length > 0 &&
    group.knowledge_points.every((point) => selectedSet.value.has(point.id))
  );
}

function toggleGroup(group: FolderKnowledgePointGroup): void {
  const next = new Set(props.selectedIds);
  if (groupFullySelected(group)) {
    for (const point of group.knowledge_points) {
      next.delete(point.id);
    }
  } else {
    for (const point of group.knowledge_points) {
      next.add(point.id);
    }
  }
  emit('update:selectedIds', Array.from(next));
}

watch(
  () => props.folderId,
  (value) => {
    if (value) {
      void loadPoints();
    }
  },
  { immediate: true },
);

defineExpose({
  groups,
  loading,
  error,
  summaryText,
  loadPoints,
  togglePoint,
  toggleGroup,
  groupFullySelected,
});
</script>

<style lang="scss" scoped>
.kp-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: $spacing-sm;
}

.kp-summary {
  font-size: $font-size-caption;
  color: $--wot-color-gray-6;
}

.kp-state {
  padding: $spacing-md 0;
  font-size: $font-size-caption;
  color: $--wot-color-gray-7;
}

.kp-error {
  display: flex;
  align-items: center;
  gap: $spacing-md;
}

.kp-error-text {
  color: $--wot-color-danger-text;
}

.kp-retry {
  color: $--wot-color-theme;
  font-weight: $font-weight-bold;
}

.kp-scroll {
  max-height: 420rpx;
}

.kp-group {
  margin-bottom: $spacing-md;
}

.kp-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $spacing-sm 0;
}

.kp-group-title {
  font-size: $font-size-card;
  font-weight: $font-weight-medium;
  color: $--wot-color-gray-9;
}

.kp-group-action {
  font-size: $font-size-caption;
  color: $--wot-color-theme;
}

.kp-item {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  min-height: 64rpx;
  padding-left: $spacing-md;
}

.kp-box {
  width: 32rpx;
  height: 32rpx;
  border: 2rpx solid $--wot-color-gray-5;
  border-radius: 8rpx;
  box-sizing: border-box;

  &.checked {
    background-color: $--wot-color-theme;
    border-color: $--wot-color-theme;
  }
}

.kp-name {
  font-size: $font-size-body;
  color: $--wot-color-gray-8;
}
</style>
