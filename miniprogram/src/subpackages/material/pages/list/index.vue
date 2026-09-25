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
      <view v-if="loading && materialStore.materialsList.length === 0" class="loading-state">
        <text class="loading-text">正在加载资料...</text>
      </view>

      <view v-else-if="materialStore.materialsList.length === 0" class="empty-state">
        <view class="empty-badge">空</view>
        <text class="empty-title">暂无学习资料</text>
        <text class="empty-desc">上传课件、讲义或真题，开始智能练习</text>
        <button class="empty-import-btn" @tap="handleOpenUpload">立即导入资料</button>
      </view>

      <view v-else class="cards-list">
        <MaterialCard
          v-for="item in materialStore.materialsList"
          :key="item.id"
          :material="item"
          @click="handleCardClick"
          @delete="handleCardDelete"
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
import { ref, computed, onMounted } from 'vue';
import { onPullDownRefresh, onReachBottom } from '@dcloudio/uni-app';
import { useMaterialStore } from '@/stores/materialStore';
import { fetchMaterialList, deleteMaterial } from '@/api/material';
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
const activeTab = ref('all');
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const loading = ref(false);
const uploadVisible = ref(false);

const currentStatus = computed(() => {
  const item = tabs.find((t) => t.key === activeTab.value);
  return item?.status;
});

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
        materialStore.setMaterialsList(items);
      } else {
        materialStore.appendMaterialsList(items);
      }
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

onReachBottom(async () => {
  if (materialStore.materialsList.length < total.value && !loading.value) {
    page.value += 1;
    await loadData(false);
  }
});

onMounted(() => {
  void loadData(true);
});

defineExpose({
  loadData,
  activeTab,
  uploadVisible,
  handleSelectTab,
  handleCardClick,
  handleCardDelete,
  handleOpenUpload,
  handleUploadSuccess,
});
</script>

<style lang="scss" scoped src="./list.scss"></style>
