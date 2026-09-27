<template>
  <view class="course-detail-page">
    <view v-if="loading && !folder" class="loading-state">
      <text class="loading-text">正在加载课程...</text>
    </view>

    <view v-else class="course-detail-content">
      <!-- 课程概览卡片 -->
      <view class="course-summary-card">
        <view class="summary-head">
          <text class="course-name">{{ courseName }}</text>
          <text class="course-desc">
            {{ folder ? folder.material_count : 0 }} 份资料 ·
            {{ folder ? folder.knowledge_point_count : 0 }} 个考点 ·
            {{ folder ? folder.question_count : 0 }} 道题目
          </text>
        </view>
        <view class="summary-actions">
          <button class="primary-action" @tap="handleOpenUpload">上传资料</button>
          <button class="ghost-action" @tap="handleOpenGenerate">智能出题</button>
          <button class="ghost-action" @tap="handleGoQuestions">课程题目</button>
        </view>
      </view>

      <!-- 课程内资料列表 -->
      <view v-if="listData.length === 0" class="empty-state">
        <view class="empty-badge">空</view>
        <text class="empty-title">课程暂无资料</text>
        <text class="empty-desc">上传课件、讲义或真题，开始智能练习</text>
        <button class="empty-import-btn" @tap="handleOpenUpload">立即导入资料</button>
      </view>

      <view v-else class="cards-list">
        <view v-for="item in listData" :key="item.id" class="material-row">
          <MaterialCard
            :material="item"
            @click="handleCardClick"
            @delete="handleCardDelete"
            @retry="handleCardRetry"
            @trigger-parse="handleCardTriggerParse"
          />
          <view class="row-move" role="button" @tap="handleOpenMove(item)">
            <text class="row-move-text">移动到其他课程</text>
          </view>
        </view>
      </view>
    </view>

    <MaterialUpload
      v-model="uploadVisible"
      :folder-id="targetFolderId"
      @success="handleUploadSuccess"
    />
    <MoveMaterialSheet
      v-model:visible="moveVisible"
      :folders="folderStore.folders"
      :current-folder-id="targetFolderId"
      :allow-unclassified="true"
      @select="handleMoveSelect"
    />
    <CourseGenerateDrawer
      v-model:visible="generateVisible"
      :folder-id="targetFolderId"
      @success="handleGenerateSuccess"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { onLoad, onShow, onPullDownRefresh } from '@dcloudio/uni-app';
import { useMaterialStore } from '@/stores/materialStore';
import { useFolderStore } from '@/stores/folderStore';
import {
  fetchMaterialList,
  deleteMaterial,
  retryMaterial,
  triggerMaterialParse,
  moveMaterialFolder,
} from '@/api/material';
import { fetchFolderDetail, fetchFolderList } from '@/api/folder';
import MaterialCard from '../../components/MaterialCard.vue';
import MaterialUpload from '@/components/common/MaterialUpload.vue';
import MoveMaterialSheet from '@/components/course/MoveMaterialSheet.vue';
import CourseGenerateDrawer from '@/components/course/CourseGenerateDrawer.vue';
import type { MaterialItem } from '@/types/material';
import type { FolderItem } from '@/types/folder';

defineOptions({ name: 'CourseDetailPage' });

const materialStore = useMaterialStore();
const folderStore = useFolderStore();

const targetFolderId = ref('');
const folder = ref<FolderItem | null>(null);
const listData = ref<MaterialItem[]>([]);
const loading = ref(false);
const uploadVisible = ref(false);
const moveVisible = ref(false);
const generateVisible = ref(false);
const moveTarget = ref<MaterialItem | null>(null);

const courseName = computed(() => folder.value?.name || '课程详情');

async function loadFolder(): Promise<void> {
  if (!targetFolderId.value) return;
  try {
    const res = await fetchFolderDetail(targetFolderId.value);
    if (res?.data) {
      folder.value = res.data;
      folderStore.setCurrentFolder(res.data);
    }
  } catch {
    uni.showToast({ title: '加载课程失败', icon: 'none' });
  }
}

async function loadMaterials(): Promise<void> {
  if (!targetFolderId.value) return;
  loading.value = true;
  try {
    const res = await fetchMaterialList({
      folder_id: targetFolderId.value,
      page: 1,
      page_size: 50,
    });
    if (res?.data) {
      listData.value = res.data.items || [];
      for (const item of listData.value) {
        materialStore.addMaterial(item);
      }
    }
  } catch {
    uni.showToast({ title: '加载资料失败', icon: 'none' });
  } finally {
    loading.value = false;
  }
}

async function loadMoveTargets(): Promise<void> {
  try {
    const res = await fetchFolderList();
    if (res?.data?.items) {
      folderStore.setFolders(res.data.items.filter((item) => !item.is_archived));
    }
  } catch {
    // 移动目标加载失败不阻断课程页主流程
  }
}

async function refreshAll(): Promise<void> {
  await Promise.all([loadFolder(), loadMaterials()]);
}

function handleOpenUpload(): void {
  uploadVisible.value = true;
}

async function handleUploadSuccess(): Promise<void> {
  uploadVisible.value = false;
  await refreshAll();
}

function handleCardClick(item: MaterialItem): void {
  materialStore.setActiveMaterial(item.id, item.current_version_id || null);
  uni.navigateTo({
    url: `/subpackages/material/pages/detail/index?material_id=${item.id}`,
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

async function handleCardDelete(item: MaterialItem): Promise<void> {
  try {
    await deleteMaterial(item.id);
    uni.showToast({ title: '已删除资料', icon: 'none' });
    await refreshAll();
  } catch {
    uni.showToast({ title: '删除失败', icon: 'none' });
  }
}

async function handleCardRetry(item: MaterialItem): Promise<void> {
  try {
    await retryMaterial(item.id);
    uni.showToast({ title: '已发起重新解析', icon: 'success' });
    await loadMaterials();
  } catch {
    uni.showToast({ title: '重试失败，请稍后重试', icon: 'none' });
  }
}

async function handleCardTriggerParse(item: MaterialItem): Promise<void> {
  try {
    await triggerMaterialParse(item.id);
    uni.showToast({ title: '已开始解析', icon: 'success' });
    await loadMaterials();
  } catch {
    uni.showToast({ title: '发起解析失败，请稍后重试', icon: 'none' });
  }
}

function handleOpenMove(item: MaterialItem): void {
  moveTarget.value = item;
  moveVisible.value = true;
}

async function handleMoveSelect(folderId: string | null): Promise<void> {
  const target = moveTarget.value;
  if (!target) return;
  try {
    await moveMaterialFolder(target.id, folderId);
    listData.value = listData.value.filter((item) => item.id !== target.id);
    materialStore.updateMaterialFolder(target.id, folderId);
    uni.showToast({ title: '已移动资料', icon: 'success' });
    await loadFolder();
  } catch {
    uni.showToast({ title: '移动失败，请重试', icon: 'none' });
  } finally {
    moveTarget.value = null;
  }
}

function handleOpenGenerate(): void {
  generateVisible.value = true;
}

function handleGenerateSuccess(folderId: string): void {
  generateVisible.value = false;
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?folder_id=${folderId}`,
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

function handleGoQuestions(): void {
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?folder_id=${targetFolderId.value}`,
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

onLoad((query?: Record<string, string | undefined>) => {
  const resolved = query?.folder_id || query?.folderId || query?.id || '';
  if (resolved) {
    targetFolderId.value = resolved;
  }
});

onMounted(() => {
  void refreshAll();
  void loadMoveTargets();
});

let hasShownOnce = false;
onShow(() => {
  if (hasShownOnce) {
    void refreshAll();
  } else {
    hasShownOnce = true;
  }
});

onPullDownRefresh(async () => {
  try {
    await refreshAll();
  } finally {
    uni.stopPullDownRefresh();
  }
});

defineExpose({
  targetFolderId,
  folder,
  listData,
  loading,
  uploadVisible,
  moveVisible,
  generateVisible,
  courseName,
  loadFolder,
  loadMaterials,
  handleOpenUpload,
  handleUploadSuccess,
  handleOpenGenerate,
  handleGenerateSuccess,
  handleCardClick,
  handleCardDelete,
  handleCardRetry,
  handleCardTriggerParse,
  handleOpenMove,
  handleMoveSelect,
  handleGoQuestions,
});
</script>

<style lang="scss" scoped>
@import './course.scss';
</style>
