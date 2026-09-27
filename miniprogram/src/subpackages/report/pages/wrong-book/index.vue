<template>
  <view class="wrong-book-page">
    <!-- 多维联动筛选栏 -->
    <WrongRecordFilterBar
      :model-value="activeFilters"
      :knowledge-points="knowledgePoints"
      :material-id="materialId"
      @filter-change="handleFilterChange"
      @reset="handleResetFilters"
    />

    <!-- 批量多选快捷控制栏 -->
    <WrongBookBatchBar
      v-if="wrongRecords.length > 0"
      :all-selected="isAllSelected"
      :selected-count="selectedRecordCount"
      @toggle-select-all="handleToggleSelectAll"
      @clear="handleClearSelection"
    />

    <!-- 骨架屏加载状态 -->
    <view v-if="loading && wrongRecords.length === 0" class="skeleton-wrapper">
      <view v-for="i in 3" :key="i" class="skeleton-card">
        <view class="skeleton-line short" />
        <view class="skeleton-line tall" />
        <view class="skeleton-line medium" />
      </view>
    </view>

    <!-- 异常状态 -->
    <view v-else-if="error" class="error-state">
      <text class="error-text">{{ error }}</text>
      <view class="retry-btn" @tap="handleRetry">
        <text>重新加载</text>
      </view>
    </view>

    <!-- 空状态展示 -->
    <view v-else-if="wrongRecords.length === 0" class="empty-state">
      <text class="empty-title">{{ hasActiveFilter ? '无匹配错题记录' : '暂无错题记录' }}</text>
      <text class="empty-subtitle">
        {{
          hasActiveFilter
            ? '可尝试调整或重置筛选条件查找错题'
            : '太棒了，当前知识范围内暂无待攻克错题！'
        }}
      </text>
      <view v-if="hasActiveFilter" class="reset-filter-btn" @tap="handleResetFilters">
        <text>清空筛选条件</text>
      </view>
    </view>

    <!-- 错题卡片列表 -->
    <view v-else class="records-list">
      <WrongRecordCard
        v-for="record in wrongRecords"
        :key="record.id"
        :record="record"
        :selectable="true"
        :selected="selectedRecordIds.includes(record.id)"
        :mastering="masteringId === record.id"
        @toggle-select="handleToggleSelect"
        @toggle-mastered="handleToggleMastered"
      />

      <view class="list-footer">
        <text v-if="loadingMore" class="loading-more-text">正在加载更多错题...</text>
        <text v-else-if="!hasMore" class="no-more-text">已加载全部错题</text>
      </view>
    </view>

    <!-- 吸底一键继续练习操作栏 -->
    <ContinuePracticeBar
      v-if="wrongRecords.length > 0"
      :material-id="materialId"
      :knowledge-point-ids="targetKnowledgePointIds"
      :source-type="'wrong_record'"
      :count="selectedRecordCount"
      :title="'错题巩固练习'"
      :button-text="continueButtonText"
      :show-info="selectedRecordCount > 0"
      :disabled="wrongRecords.length === 0 || targetKnowledgePointIds.length === 0"
      @success="onContinueSuccess"
    />
  </view>
</template>

<script setup lang="ts">
/**
 * index.vue (subpackages/report/pages/wrong-book)
 * Wrong Book page with filtering, cards list, and continue practice bar.
 * Complies with docs/DESIGN.md & spec ZL-136. Zero-Emoji. Max lines <= 300.
 */

import { ref, computed, onMounted } from 'vue';
import { onLoad, onPullDownRefresh, onReachBottom } from '@dcloudio/uni-app';
import { useReportStore } from '@/stores/reportStore';
import { fetchWrongBook, toggleWrongRecordResolved } from '@/api/diagnosis';
import type { WrongRecordItem, WrongRecordQueryParams } from '@/types/report';
import type { PracticeSession } from '@/types/practice';

import WrongRecordFilterBar from '../../components/WrongRecordFilterBar.vue';
import WrongRecordCard from '../../components/WrongRecordCard.vue';
import WrongBookBatchBar from '../../components/WrongBookBatchBar.vue';
import ContinuePracticeBar from '../../components/ContinuePracticeBar.vue';

interface Props {
  materialId?: string;
  knowledgePointId?: string;
}

const props = withDefaults(defineProps<Props>(), {
  materialId: '',
  knowledgePointId: '',
});

const reportStore = useReportStore();
const loading = ref(false);
const loadingMore = ref(false);
const error = ref<string | null>(null);
const materialId = ref(props.materialId || '');
const knowledgePoints = ref<Array<{ id: string; name: string }>>([]);
const masteringId = ref<string | null>(null);

const wrongRecords = computed(() => reportStore.wrongRecords);
const selectedRecordIds = computed(() => reportStore.selectedRecordIds);
const selectedRecordCount = computed(() => reportStore.selectedRecordCount);
const activeFilters = computed(() => reportStore.wrongFilters);
const hasMore = computed(() => reportStore.wrongHasMore);
const currentPage = computed(() => reportStore.wrongPage);

const isAllSelected = computed(
  () =>
    wrongRecords.value.length > 0 &&
    wrongRecords.value.every((r) => selectedRecordIds.value.includes(r.id)),
);

const hasActiveFilter = computed(() => {
  const f = activeFilters.value;
  return Boolean(
    f.is_mastered !== undefined || f.error_type || f.question_type || f.knowledge_point_id,
  );
});

const targetKnowledgePointIds = computed(() => {
  const ids = new Set<string>();
  const source =
    selectedRecordIds.value.length > 0
      ? wrongRecords.value.filter((r) => selectedRecordIds.value.includes(r.id))
      : wrongRecords.value.filter((r) => !r.is_mastered);
  source.forEach((r) => r.knowledge_point_id && ids.add(r.knowledge_point_id));
  return Array.from(ids);
});

const continueButtonText = computed(() => {
  if (selectedRecordCount.value > 0) {
    return `巩固已选 ${selectedRecordCount.value} 道错题`;
  }
  return wrongRecords.value.some((r) => !r.is_mastered) ? '一键巩固待攻克错题' : '错题巩固练习';
});

async function loadData(page: number, isRefresh: boolean = false): Promise<void> {
  if (isRefresh) {
    loading.value = true;
    error.value = null;
  } else {
    loadingMore.value = true;
  }

  try {
    const params: WrongRecordQueryParams = {
      ...activeFilters.value,
      material_id: materialId.value || undefined,
      page,
      page_size: reportStore.wrongPageSize,
    };
    const res = await fetchWrongBook(params);
    if (res.code === 0 && res.data) {
      const items = res.data.items || [];
      const total = res.data.total ?? items.length;
      if (isRefresh) {
        reportStore.setWrongRecords(items, total);
        reportStore.clearSelectedRecords();
      } else {
        reportStore.appendWrongRecords(items, total);
      }
      reportStore.setWrongPage(page);
    } else if (isRefresh) {
      error.value = res.message || '获取错题列表失败';
    } else {
      uni.showToast({ title: res.message || '加载更多失败', icon: 'none' });
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : '网络连接异常';
    if (isRefresh) error.value = msg;
    else uni.showToast({ title: msg, icon: 'none' });
  } finally {
    loading.value = false;
    loadingMore.value = false;
    uni.stopPullDownRefresh();
  }
}

function handleFilterChange(newFilters: WrongRecordQueryParams): void {
  reportStore.setWrongFilters(newFilters);
  loadData(1, true);
}

function handleResetFilters(): void {
  reportStore.setWrongFilters({ material_id: materialId.value || undefined });
  loadData(1, true);
}

function handleToggleSelect(record: WrongRecordItem): void {
  reportStore.toggleSelectRecord(record.id);
}

function handleToggleSelectAll(): void {
  if (isAllSelected.value) {
    reportStore.clearSelectedRecords();
  } else {
    reportStore.selectAllRecords(wrongRecords.value.map((r) => r.id));
  }
}

function handleClearSelection(): void {
  reportStore.clearSelectedRecords();
}

async function handleToggleMastered(record: WrongRecordItem): Promise<void> {
  const target = !record.is_mastered;
  masteringId.value = record.id;
  reportStore.updateWrongRecordMastered(record.id, target);

  try {
    const res = await toggleWrongRecordResolved(record.id, target);
    if (res.code === 0) {
      uni.showToast({ title: target ? '已标为攻克' : '已移出攻克', icon: 'none' });
    } else {
      reportStore.updateWrongRecordMastered(record.id, !target);
      uni.showToast({ title: res.message || '更新状态失败', icon: 'none' });
    }
  } catch (err: unknown) {
    reportStore.updateWrongRecordMastered(record.id, !target);
    uni.showToast({ title: err instanceof Error ? err.message : '网络异常', icon: 'none' });
  } finally {
    masteringId.value = null;
  }
}

function handleRetry(): void {
  loadData(1, true);
}

function onContinueSuccess(session: PracticeSession): void {
  uni.showToast({ title: `已创建练习: ${session.title}`, icon: 'none' });
}

let isReady = false;
let isInitialLoaded = false;

onPullDownRefresh(() => {
  if (isReady) loadData(1, true);
});

onReachBottom(() => {
  if (isReady && !loading.value && !loadingMore.value && hasMore.value) {
    loadData(currentPage.value + 1, false);
  }
});

function initAndLoad(mid?: string, kid?: string): void {
  if (isInitialLoaded) return;
  isInitialLoaded = true;
  if (mid) materialId.value = mid;
  if (kid) reportStore.setWrongFilters({ ...activeFilters.value, knowledge_point_id: kid });
  loadData(1, true);
}

onMounted(() => {
  initAndLoad(props.materialId, props.knowledgePointId);
  isReady = true;
});

onLoad((query?: Record<string, string>) => {
  initAndLoad(
    query?.material_id || props.materialId,
    query?.knowledge_point_id || props.knowledgePointId,
  );
});
</script>

<style lang="scss" scoped>
@import './wrongBook.scss';
</style>
