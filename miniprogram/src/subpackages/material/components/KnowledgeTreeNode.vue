<template>
  <view class="knowledge-tree-node" :class="[`level-${level}`]">
    <view class="node-main-row" :style="{ paddingLeft: `${(level - 1) * 28}rpx` }">
      <!-- 折叠/展开切换触控区 (>= 88rpx) -->
      <view v-if="hasChildren" class="collapse-hit-area" @tap.stop="handleToggleCollapse">
        <wd-icon
          :name="isCollapsed ? 'arrow-right' : 'arrow-down'"
          size="28rpx"
          custom-class="collapse-icon"
        />
      </view>
      <view v-else class="collapse-placeholder" />

      <!-- 复选框触控区 (>= 88rpx) -->
      <view class="checkbox-hit-area" @tap.stop="handleToggleSelect">
        <view
          class="custom-checkbox"
          :class="{ checked: isChecked, indeterminate: isIndeterminate }"
        >
          <wd-icon v-if="isChecked" name="check" size="24rpx" custom-class="check-icon" />
          <view v-else-if="isIndeterminate" class="checkbox-dash" />
        </view>
      </view>

      <!-- 节点名称与说明文本区 -->
      <view class="node-content" @tap="handleToggleSelect">
        <view class="title-row">
          <text class="node-name">{{ nodeTitle }}</text>
          <!-- 低可信度黄色警告徽章 (FR-18) -->
          <wd-tag
            v-if="node.is_low_confidence"
            type="warning"
            plain
            size="small"
            custom-class="low-conf-badge"
          >
            低可信度
          </wd-tag>
        </view>
        <text v-if="node.description" class="node-desc">
          {{ node.description }}
        </text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { getActivePinia } from 'pinia';
import { useMaterialStore } from '@/stores/materialStore';
import type { KnowledgeTreeNode as KnowledgeNodeType } from '@/types/material';
import { collectNodeAndDescendantIds, getNodeCheckStatus } from '../utils/tree';

interface Props {
  node: KnowledgeNodeType;
  level?: number;
  selectedIds?: string[];
  collapsedMap?: Record<string, boolean>;
}

const props = withDefaults(defineProps<Props>(), {
  level: 1,
  selectedIds: () => [],
  collapsedMap: () => ({}),
});

const emit = defineEmits<{
  (e: 'toggle-select', id: string): void;
  (e: 'toggle-collapse', id: string): void;
}>();

const nodeTitle = computed<string>(() => {
  return props.node.name || props.node.title || '未命名考点';
});

const hasChildren = computed<boolean>(() => {
  return Array.isArray(props.node.children) && props.node.children.length > 0;
});

const checkStatus = computed(() => getNodeCheckStatus(props.node, new Set(props.selectedIds)));

const isChecked = computed<boolean>(() => checkStatus.value === 'checked');
const isIndeterminate = computed<boolean>(() => checkStatus.value === 'indeterminate');

const isCollapsed = computed<boolean>(() => {
  return Boolean(props.collapsedMap[props.node.id]);
});

function handleToggleSelect(): void {
  const ids = collectNodeAndDescendantIds(props.node);
  // checked -> clear the whole subtree; indeterminate/unchecked -> select all.
  const willSelect = checkStatus.value !== 'checked';
  if (getActivePinia()) {
    const materialStore = useMaterialStore();
    materialStore.toggleKnowledgeSubtree(ids, willSelect);
  }
  emit('toggle-select', props.node.id);
}

function handleToggleCollapse(): void {
  emit('toggle-collapse', props.node.id);
}
</script>

<style lang="scss" scoped>
.knowledge-tree-node {
  width: 100%;
}

.node-main-row {
  display: flex;
  align-items: center;
  min-height: $touch-target-min;
  border-bottom: 1rpx solid $--wot-color-gray-4;
  background-color: #ffffff;
  transition: background-color 0.15s ease;

  &:active {
    background-color: $--wot-color-gray-1;
  }
}

.collapse-hit-area,
.collapse-placeholder {
  width: $touch-target-min;
  height: $touch-target-min;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

:deep(.collapse-icon) {
  color: $--wot-color-gray-6;
}

.checkbox-hit-area {
  width: $touch-target-min;
  height: $touch-target-min;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.custom-checkbox {
  width: 38rpx;
  height: 38rpx;
  border-radius: $radius-sm;
  border: 2rpx solid $--wot-color-gray-5;
  background-color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;

  &.checked {
    background-color: $--wot-color-theme;
    border-color: $--wot-color-theme;
  }

  &.indeterminate {
    background-color: $--wot-color-theme;
    border-color: $--wot-color-theme;
  }
}

.checkbox-dash {
  width: 20rpx;
  height: 4rpx;
  border-radius: 2rpx;
  background-color: #ffffff;
}

:deep(.check-icon) {
  color: #ffffff;
}

.node-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: $spacing-xs $spacing-sm $spacing-xs 0;
}

.title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: $spacing-xs;
}

.node-name {
  font-size: $font-size-body;
  font-weight: $font-weight-medium;
  color: $--wot-color-gray-8;
  line-height: $line-height-card;
}

.level-1 > .node-main-row .node-name {
  font-size: $font-size-card;
  font-weight: $font-weight-bold;
  color: $--wot-color-gray-9;
}

.node-desc {
  font-size: $font-size-caption;
  color: $--wot-color-gray-7;
  line-height: $line-height-snug;
  margin-top: 4rpx;
}

:deep(.low-conf-badge) {
  margin-left: $spacing-xs;
  font-size: 20rpx;
  line-height: 1;
}
</style>
