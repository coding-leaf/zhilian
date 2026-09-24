<template>
  <view class="material-card" @tap="emit('click', props.material)">
    <view class="card-header">
      <view class="format-badge">{{ formatLabel }}</view>
      <view class="title-wrap">
        <text class="material-title">{{ material.title }}</text>
      </view>
      <view :class="['status-capsule', 'status--' + statusTag.type]" :style="capsuleStyle">
        {{ statusTag.text }}
      </view>
    </view>
    <view class="card-body">
      <view class="meta-row">
        <text>{{ formattedSize }} · {{ formattedDate }}</text>
      </view>
      <view v-if="keyPointsSummary" class="points-text">{{ keyPointsSummary }}</view>
    </view>
    <view class="card-footer">
      <text class="footer-hint">查看解析与考点</text>
      <button class="delete-btn" @tap.stop="handleDelete">删除</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { MaterialItem } from '@/types/material';
import { resolveMaterialStatusTag } from '@/subpackages/material/utils/copywriting';

interface Props {
  material: MaterialItem;
}
interface Emits {
  (e: 'click', material: MaterialItem): void;
  (e: 'delete', material: MaterialItem): void;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const THEMES: Record<string, { bg: string; color: string; border: string }> = {
  primary: { bg: '#eff6ff', color: '#2563eb', border: '#bfdbfe' },
  success: { bg: '#ecfdf5', color: '#065f46', border: '#a7f3d0' },
  warning: { bg: '#fffbeb', color: '#92400e', border: '#fde68a' },
  danger: { bg: '#fef2f2', color: '#991b1b', border: '#fecaca' },
  info: { bg: '#f1f5f9', color: '#64748b', border: '#e2e8f0' },
};

const formatLabel = computed(() => (props.material.file_format || 'doc').toUpperCase());
const formattedSize = computed(() => {
  const bytes = props.material.file_size || 0;
  if (bytes < 1024) return `${bytes} B`;
  const isKb = bytes < 1048576;
  return `${(bytes / (isKb ? 1024 : 1048576)).toFixed(1)} ${isKb ? 'KB' : 'MB'}`;
});

const formattedDate = computed(() => {
  const d = new Date(props.material.created_at || '');
  if (Number.isNaN(d.getTime())) return props.material.created_at || '';
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
});

const statusTag = computed(() => {
  if (String(props.material.status || '').toUpperCase() === 'FAILED') {
    return { text: '解析失败', type: 'danger' as const };
  }
  return resolveMaterialStatusTag(props.material.status);
});

const capsuleStyle = computed(() => {
  const t = THEMES[statusTag.value.type] || THEMES.info;
  return `background-color:${t.bg};color:${t.color};border-color:${t.border};`;
});

const keyPointsSummary = computed(() => {
  const raw = props.material as unknown as Record<string, unknown>;
  const count = raw.key_points_count ?? raw.points_count;
  return typeof count === 'number' && count > 0 ? `${count} 个核心考点` : null;
});

function handleDelete(): void {
  uni.showModal({
    title: '删除资料',
    content: '确定要删除此资料吗？',
    confirmText: '删除',
    confirmColor: '#EF4444',
    cancelText: '取消',
    success: (res) => {
      if (res.confirm) emit('delete', props.material);
    },
  });
}
</script>

<style lang="scss" scoped>
.material-card {
  background: #ffffff;
  border-radius: 24rpx;
  border: 1px solid #e2e8f0;
  box-shadow: 0 8rpx 24rpx -4rpx rgba(15, 23, 42, 0.05);
  padding: 24rpx;
  margin-bottom: 20rpx;
  transition: transform 0.16s ease;
  &:active {
    transform: scale(0.985);
  }
}
.card-header,
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.format-badge {
  font-size: 20rpx;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8rpx;
  padding: 2rpx 10rpx;
  margin-right: 16rpx;
}
.title-wrap {
  flex: 1;
  min-width: 0;
  margin-right: 16rpx;
}
.material-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}
.status-capsule {
  font-size: 22rpx;
  font-weight: 600;
  padding: 4rpx 16rpx;
  border-radius: 9999rpx;
  border-width: 1px;
  border-style: solid;
}
.card-body {
  margin-top: 14rpx;
}
.meta-row {
  font-size: 22rpx;
  color: #64748b;
}
.points-text {
  margin-top: 8rpx;
  font-size: 24rpx;
  color: #2563eb;
  font-weight: 600;
}
.card-footer {
  margin-top: 16rpx;
  padding-top: 12rpx;
  border-top: 1px solid #f1f5f9;
}
.footer-hint {
  font-size: 22rpx;
  color: #94a3b8;
}
.delete-btn {
  font-size: 22rpx;
  color: #ef4444;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 9999rpx;
  padding: 4rpx 18rpx;
  line-height: 1.5;
  margin: 0;
}
</style>
