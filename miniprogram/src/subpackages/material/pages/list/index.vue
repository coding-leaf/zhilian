<template>
  <view class="material-list-page">
    <view v-if="isUnclassifiedView" class="scope-banner">
      <text class="scope-text">未分类资料</text>
      <text class="scope-hint">选择「移动到课程」将其归入课程</text>
    </view>

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
        <view v-for="item in listData" :key="item.id" class="list-row">
          <MaterialCard
            :material="item"
            @click="handleCardClick"
            @delete="handleCardDelete"
            @retry="handleCardRetry"
            @trigger-parse="handleCardTriggerParse"
          />
          <view class="row-move" role="button" @tap="handleOpenMove(item)">
            <text class="row-move-text">移动到课程</text>
          </view>
        </view>
      </view>
    </view>

    <view class="fab-upload-btn" @tap="handleOpenUpload">
      <text class="fab-plus">+</text>
      <text class="fab-label">导入资料</text>
    </view>

    <MaterialUpload
      v-model="uploadVisible"
      :folder-id="uploadFolderId"
      @success="handleUploadSuccess"
    />
    <MoveMaterialSheet
      v-model:visible="moveVisible"
      :folders="folderStore.folders"
      :current-folder-id="currentFolderId"
      :allow-unclassified="!isUnclassifiedView"
      @select="handleMoveSelect"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { onLoad, onShow, onHide, onPullDownRefresh, onReachBottom } from '@dcloudio/uni-app';
import { useMaterialStore } from '@/stores/materialStore';
import { useFolderStore } from '@/stores/folderStore';
import { fetchMaterialList } from '@/api/material';
import { UNCLASSIFIED_FOLDER_ID } from '@/types/folder';
import MaterialCard from '../../components/MaterialCard.vue';
import MaterialUpload from '@/components/common/MaterialUpload.vue';
import MoveMaterialSheet from '@/components/course/MoveMaterialSheet.vue';
import { useMaterialListPolling } from '../../composables/useMaterialListPolling';
import { useMaterialFolderMove } from '../../composables/useMaterialFolderMove';
import { useMaterialCardActions } from '../../composables/useMaterialCardActions';
import type { MaterialItem } from '@/types/material';

defineOptions({ name: 'MaterialListPage' });

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
const folderStore = useFolderStore();
const listData = ref<MaterialItem[]>([]);
const activeTab = ref('all');
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const loading = ref(false);
const uploadVisible = ref(false);
const targetFolderId = ref('');
const isPageVisible = ref(true);
let isComponentMounted = false;

const isUnclassifiedView = computed(() => targetFolderId.value === UNCLASSIFIED_FOLDER_ID);
const uploadFolderId = computed(() => (isUnclassifiedView.value ? '' : targetFolderId.value));
const currentFolderId = computed(() => (isUnclassifiedView.value ? null : targetFolderId.value));

const currentStatus = computed(() => {
  if (activeTab.value === 'all') return undefined;
  const item = tabs.find((t) => t.key === activeTab.value);
  return item?.status;
});

const { stopPolling, checkAndStartPolling } = useMaterialListPolling({
  items: listData,
  isPageVisible,
  onItemUpdated: (item) => materialStore.addMaterial(item),
});

const { moveVisible, loadMoveTargets, handleOpenMove, handleMoveSelect } = useMaterialFolderMove({
  listData,
});

const { handleCardClick, handleCardDelete, handleCardRetry, handleCardTriggerParse } =
  useMaterialCardActions({ refresh: () => loadData(true) });

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
      folder_id: targetFolderId.value || undefined,
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
  isPageVisible.value = true;
  if (hasShownOnce) {
    void loadData(true);
  } else {
    hasShownOnce = true;
  }
});

onHide(() => {
  if (!isComponentMounted) return;
  isPageVisible.value = false;
  stopPolling();
});

onUnmounted(() => {
  isComponentMounted = false;
  isPageVisible.value = false;
  stopPolling();
});

onLoad((query?: Record<string, string | undefined>) => {
  const resolved = query?.folder_id || query?.folderId || '';
  if (resolved) {
    targetFolderId.value = resolved;
  }
});

onMounted(() => {
  isComponentMounted = true;
  void loadData(true);
  void loadMoveTargets();
});

defineExpose({
  loadData,
  listData,
  activeTab,
  uploadVisible,
  moveVisible,
  targetFolderId,
  isUnclassifiedView,
  handleSelectTab,
  handleCardClick,
  handleCardDelete,
  handleCardRetry,
  handleCardTriggerParse,
  handleOpenMove,
  handleMoveSelect,
  handleOpenUpload,
  handleUploadSuccess,
  handleReachBottom,
  checkAndStartPolling,
  stopPolling,
});
</script>

<style lang="scss" scoped src="./list.scss"></style>
