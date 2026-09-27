<template>
  <view class="material-list-page">
    <view class="filter-tabs">
      <view
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-item"
        :class="{ active: activeTab === tab.key }"
        @tap="handleSelectTab(tab.key)"
      >
        <text class="tab-label">{{ tab.label }}</text>
      </view>
    </view>

    <view class="list-container">
      <view v-if="loading && listData.length === 0" class="loading-state">
        <text class="loading-text">正在加载资料...</text>
      </view>

      <view v-else-if="listData.length === 0" class="empty-state">
        <view class="empty-badge">空</view>
        <text class="empty-title">暂无学习资料</text>
        <text class="empty-desc">上传课件、讲义或真题，开始智能练习</text>
        <button class="empty-import-btn" @tap="handleOpenUpload">立即导入资料</button>
      </view>

      <view v-else class="cards-list">
        <MaterialCard
          v-for="item in listData"
          :key="item.id"
          :material="item"
          @click="handleCardClick"
          @delete="handleCardDelete"
          @retry="handleCardRetry"
          @trigger-parse="handleCardTriggerParse"
        />
      </view>
    </view>

    <view class="fab-upload-btn" @tap="handleOpenUpload">
      <text class="fab-plus">+</text>
      <text class="fab-label">导入资料</text>
    </view>

    <MaterialUpload v-model="uploadVisible" @success="handleUploadSuccess" />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { onShow, onHide, onPullDownRefresh, onReachBottom } from '@dcloudio/uni-app';
import { useMaterialStore } from '@/stores/materialStore';
import {
  fetchMaterialList,
  fetchMaterialStatus,
  deleteMaterial,
  retryMaterial,
  triggerMaterialParse,
} from '@/api/material';
import MaterialCard from '../../components/MaterialCard.vue';
import MaterialUpload from '@/components/common/MaterialUpload.vue';
import type { MaterialItem } from '@/types/material';

interface TabItem {
  key: string;
  label: string;
  status?: string;
}

const tabs: TabItem[] = [
  { key: 'all', label: '全部' },
  { key: 'parsing', label: '解析中', status: 'parsing' },
  { key: 'retake', label: '待重拍', status: 'retake_required' },
  { key: 'ready', label: '已完成', status: 'ready' },
];

const materialStore = useMaterialStore();
const listData = ref<MaterialItem[]>([]);
const activeTab = ref('all');
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const loading = ref(false);
const uploadVisible = ref(false);

const currentStatus = computed(() => {
  if (activeTab.value === 'all') return undefined;
  const item = tabs.find((t) => t.key === activeTab.value);
  return item?.status;
});

let pollTimer: ReturnType<typeof setTimeout> | null = null;
let currentPollInterval = 1500;
const backoffFactor = 1.5;
const maxPollInterval = 8000;
const maxTimeoutMs = 180000;
let pollStartTime = 0;
let isPageVisible = true;
let isComponentMounted = false;

function stopPolling(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function checkAndStartPolling(): void {
  stopPolling();
  if (!isPageVisible) {
    return;
  }
  const hasPending = listData.value.some(
    (item) => item.status === 'parsing' || item.status === 'pending',
  );
  if (!hasPending) {
    return;
  }
  pollStartTime = Date.now();
  currentPollInterval = 1500;
  scheduleNextPoll();
}

function scheduleNextPoll(): void {
  stopPolling();
  const delay = currentPollInterval;
  currentPollInterval = Math.min(Math.round(currentPollInterval * backoffFactor), maxPollInterval);

  pollTimer = setTimeout(async () => {
    if (!isPageVisible || Date.now() - pollStartTime > maxTimeoutMs) {
      stopPolling();
      return;
    }
    await pollPendingItems();
  }, delay);
}

async function pollPendingItems(): Promise<void> {
  const pendingItems = listData.value.filter(
    (item) => item.status === 'parsing' || item.status === 'pending',
  );
  if (pendingItems.length === 0) {
    stopPolling();
    return;
  }

  try {
    const results = await Promise.allSettled(
      pendingItems.map((item) => fetchMaterialStatus(item.id)),
    );
    for (const res of results) {
      if (res.status === 'fulfilled' && res.value?.data) {
        const updated = res.value.data;
        const targetIndex = listData.value.findIndex((m) => m.id === updated.id);
        if (targetIndex >= 0) {
          listData.value[targetIndex] = { ...listData.value[targetIndex], ...updated };
          materialStore.addMaterial(listData.value[targetIndex]);
        }
      }
    }
  } catch {
    // 忽略偶发网络轮询异常
  }

  const stillPending = listData.value.some(
    (item) => item.status === 'parsing' || item.status === 'pending',
  );
  if (stillPending && isPageVisible && Date.now() - pollStartTime <= maxTimeoutMs) {
    scheduleNextPoll();
  } else {
    stopPolling();
  }
}

async function loadData(reset = false): Promise<void> {
  if (loading.value) return;
  if (reset) {
    page.value = 1;
  }
  loading.value = true;
  try {
    const res = await fetchMaterialList({
      page: page.value,
      page_size: pageSize,
      status: currentStatus.value,
    });
    if (res && res.data) {
      const items = res.data.items || [];
      total.value = res.data.total ?? items.length;
      if (reset) {
        listData.value = items;
      } else {
        // Deduplicate by id: offset drift (inserts/deletes during paging) can
        // otherwise re-deliver an item and cause duplicate keys / rows.
        const existingIds = new Set(listData.value.map((item) => item.id));
        const newItems = items.filter((item) => !existingIds.has(item.id));
        listData.value = [...listData.value, ...newItems];
      }
      for (const item of items) {
        materialStore.addMaterial(item);
      }
      checkAndStartPolling();
    }
  } catch (err: unknown) {
    uni.showToast({ title: '加载资料失败', icon: 'none' });
  } finally {
    loading.value = false;
  }
}

function handleSelectTab(key: string): void {
  if (activeTab.value === key) return;
  activeTab.value = key;
  stopPolling();
  void loadData(true);
}

function handleCardClick(item: MaterialItem): void {
  materialStore.setActiveMaterial(item.id, item.current_version_id || null);
  uni.navigateTo({
    url: `../detail/index?id=${item.id}`,
  });
}

async function handleCardDelete(item: MaterialItem): Promise<void> {
  try {
    await deleteMaterial(item.id);
    uni.showToast({ title: '已删除资料', icon: 'none' });
    await loadData(true);
  } catch (err: unknown) {
    uni.showToast({ title: '删除失败', icon: 'none' });
  }
}

async function handleCardRetry(item: MaterialItem): Promise<void> {
  try {
    if (typeof uni !== 'undefined' && typeof uni.showLoading === 'function') {
      uni.showLoading({ title: '正在发起重试...' });
    }
    await retryMaterial(item.id);
    uni.showToast({ title: '已发起重新解析', icon: 'success' });
    await loadData(true);
  } catch {
    uni.showToast({ title: '重试失败，请稍后重试', icon: 'none' });
  } finally {
    if (typeof uni !== 'undefined' && typeof uni.hideLoading === 'function') {
      uni.hideLoading();
    }
  }
}

async function handleCardTriggerParse(item: MaterialItem): Promise<void> {
  try {
    if (typeof uni !== 'undefined' && typeof uni.showLoading === 'function') {
      uni.showLoading({ title: '正在开始解析...' });
    }
    await triggerMaterialParse(item.id);
    uni.showToast({ title: '已开始解析', icon: 'success' });
    await loadData(true);
  } catch {
    uni.showToast({ title: '发起解析失败，请稍后重试', icon: 'none' });
  } finally {
    if (typeof uni !== 'undefined' && typeof uni.hideLoading === 'function') {
      uni.hideLoading();
    }
  }
}

function handleOpenUpload(): void {
  uploadVisible.value = true;
}

function handleUploadSuccess(): void {
  uploadVisible.value = false;
  void loadData(true);
}

onPullDownRefresh(async () => {
  await loadData(true);
  uni.stopPullDownRefresh();
});

async function handleReachBottom(): Promise<void> {
  if (listData.value.length < total.value && !loading.value) {
    page.value += 1;
    await loadData(false);
  }
}

onReachBottom(handleReachBottom);

// The first `onShow` fires together with the initial mount; let `onMounted`
// own the first-screen fetch so the two lifecycles cannot double-request.
// Subsequent `onShow` events mean the user returned to the page -> refresh.
let hasShownOnce = false;
onShow(() => {
  isPageVisible = true;
  if (hasShownOnce) {
    void loadData(true);
  } else {
    hasShownOnce = true;
  }
});

onHide(() => {
  if (!isComponentMounted) return;
  isPageVisible = false;
  stopPolling();
});

onUnmounted(() => {
  isComponentMounted = false;
  isPageVisible = false;
  stopPolling();
});

onMounted(() => {
  isComponentMounted = true;
  void loadData(true);
});

defineExpose({
  loadData,
  listData,
  activeTab,
  uploadVisible,
  handleSelectTab,
  handleCardClick,
  handleCardDelete,
  handleCardRetry,
  handleCardTriggerParse,
  handleOpenUpload,
  handleUploadSuccess,
  handleReachBottom,
  checkAndStartPolling,
  stopPolling,
});
</script>

<style lang="scss" scoped src="./list.scss"></style>
