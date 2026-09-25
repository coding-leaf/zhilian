<template>
  <view class="recent-learning-section">
    <!-- 模块头部 -->
    <view class="section-header">
      <text class="section-title">最近学习</text>
    </view>

    <!-- 智能第一轨：进行中练习草稿置顶卡片 -->
    <view
      v-if="activePractice"
      class="active-practice-card"
      role="button"
      aria-label="继续上次练习"
      @tap="handleContinuePractice(activePractice.practiceId)"
    >
      <view class="practice-card-top">
        <view class="practice-left-header">
          <text class="practice-badge">进行中</text>
          <text class="practice-title">{{ activePractice.title }}</text>
        </view>
        <text class="practice-time">{{ activePractice.updatedAtText }}</text>
      </view>

      <view class="practice-progress-box">
        <view class="progress-track">
          <view class="progress-fill" :style="{ width: practiceProgressPct + '%' }" />
        </view>
        <view class="progress-meta-row">
          <text class="progress-text">
            已答 {{ activePractice.answeredCount }}/{{ activePractice.totalCount }} 题
          </text>
          <text class="progress-pct">{{ practiceProgressPct }}%</text>
        </view>
      </view>

      <view class="practice-action-row">
        <view class="btn-continue" @tap.stop="handleContinuePractice(activePractice.practiceId)">
          继续练习
        </view>
      </view>
    </view>

    <!-- 智能第二轨：最近 2 份学习资料列表 -->
    <view v-if="displayedMaterials.length > 0" class="materials-list">
      <view
        v-for="mat in displayedMaterials"
        :key="mat.id"
        class="material-item-card"
        role="button"
        :aria-label="mat.title"
        @tap="handleViewMaterial(mat.id)"
      >
        <view class="material-info-col">
          <view class="material-title-row">
            <text class="format-tag">{{ (mat.file_format || 'PDF').toUpperCase() }}</text>
            <text class="material-title">{{ mat.title }}</text>
            <text :class="['status-tag', 'status--' + getStatusInfo(mat.status).type]">
              {{ getStatusInfo(mat.status).text }}
            </text>
          </view>
          <view class="material-meta-row">
            <text>{{ formatSize(mat.file_size) }}</text>
            <text class="meta-dot">·</text>
            <text>{{ resolvePointsText(mat) }}</text>
          </view>
        </view>

        <view class="material-action-col">
          <view class="btn-quick-quiz" @tap.stop="handleQuickQuiz(mat)">去出题</view>
        </view>
      </view>
    </view>

    <!-- 暂无学习记录空占位（仅当既无草稿也无资料时呈现） -->
    <view
      v-if="!activePractice && displayedMaterials.length === 0 && !loading"
      class="empty-placeholder"
    >
      <text class="empty-text">暂无最近学习记录</text>
    </view>

    <!-- 底部查看全部资料跳转链接 -->
    <view
      class="section-footer"
      role="button"
      aria-label="查看全部资料"
      @tap="handleViewAllMaterials"
    >
      <text class="footer-link">查看全部资料</text>
      <text class="arrow-char">&gt;</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { MaterialItem, MaterialStatus } from '@/types/material';
import type { ActivePracticeInfo } from '@/utils/recentLearning';
import { resolveMaterialStatusTag } from '@/utils/copywriting';

defineOptions({
  name: 'RecentLearningSection',
});

interface Props {
  activePractice?: ActivePracticeInfo | null;
  recentMaterials?: MaterialItem[];
  loading?: boolean;
}

interface Emits {
  (e: 'continue-practice', practiceId: string): void;
  (e: 'quick-quiz', material: MaterialItem): void;
  (e: 'generate-questions', materialId: string): void;
  (e: 'view-material', materialId: string): void;
  (e: 'view-all-materials'): void;
  (e: 'view-all'): void;
}

const props = withDefaults(defineProps<Props>(), {
  activePractice: null,
  recentMaterials: () => [],
  loading: false,
});

const emit = defineEmits<Emits>();

const displayedMaterials = computed(() => {
  return (props.recentMaterials || []).slice(0, 2);
});

const practiceProgressPct = computed(() => {
  if (!props.activePractice || !props.activePractice.totalCount) return 0;
  return Math.min(
    100,
    Math.round((props.activePractice.answeredCount / props.activePractice.totalCount) * 100),
  );
});

function getStatusInfo(status: MaterialStatus): { text: string; type: string } {
  if (String(status || '').toUpperCase() === 'FAILED') {
    return { text: '解析异常', type: 'danger' };
  }
  return resolveMaterialStatusTag(status);
}

function formatSize(bytes?: number): string {
  const b = bytes || 0;
  if (b < 1024) return `${b} B`;
  const isKb = b < 1048576;
  return `${(b / (isKb ? 1024 : 1048576)).toFixed(1)} ${isKb ? 'KB' : 'MB'}`;
}

function resolvePointsText(item: MaterialItem): string {
  const raw = item as unknown as Record<string, unknown>;
  const points = raw.key_points_count ?? raw.points_count;
  if (typeof points === 'number' && points > 0) {
    return `${points} 个考点`;
  }
  const pages = raw.page_count ?? raw.pages_count;
  if (typeof pages === 'number' && pages > 0) {
    return `${pages} 页`;
  }
  return '待提取考点';
}

function handleContinuePractice(practiceId: string): void {
  emit('continue-practice', practiceId);
}

function handleQuickQuiz(mat: MaterialItem): void {
  emit('quick-quiz', mat);
  emit('generate-questions', mat.id);
}

function handleViewMaterial(materialId: string): void {
  emit('view-material', materialId);
}

function handleViewAllMaterials(): void {
  emit('view-all-materials');
  emit('view-all');
}
</script>

<style lang="scss" scoped>
@import './RecentLearningSection.scss';
</style>
