<template>
  <view class="dashboard-page">
    <!-- 顶部沉浸式问候栏 -->
    <view class="dashboard-header">
      <view class="greeting-col">
        <text class="brand-title">智练工作台</text>
        <text class="user-greeting">{{ greetingText }}</text>
      </view>
      <view class="auth-action-col">
        <button v-if="!userStore.isAuthenticated" class="btn-login" @tap="handleNavigateLogin">
          登录
        </button>
        <button v-else class="btn-logout" @tap="handleLogout">退出</button>
      </view>
    </view>

    <!-- 骨架屏加载态 -->
    <view v-if="loading && !hasLoadedOnce" class="dashboard-skeleton">
      <wd-skeleton theme="paragraph" />
    </view>

    <!-- 核心工作台内容区 -->
    <view v-else class="dashboard-content">
      <!-- 课程文件夹信息架构入口 -->
      <CourseListSection
        :folders="folderStore.folders"
        :archived-folders="folderStore.archivedFolders"
        :unclassified-count="folderStore.unclassifiedCount"
        @enter="handleEnterCourse"
        @view-unclassified="handleViewUnclassified"
        @changed="handleCoursesChanged"
      />

      <!-- 快捷上传横幅（未选课程即落未分类） -->
      <QuickUploadBar ref="quickUploadRef" @upload-success="handleUploadSuccess" />

      <!-- 智能双轨：新手引导卡 或 最近学习流 -->
      <NewbieGuideCard v-if="isNewbie" @start-first="handleStartFirst" />
      <RecentLearningSection
        v-else
        :active-practice="activePractice"
        :recent-materials="recentMaterials"
        :loading="loading"
        @continue-practice="handleContinuePractice"
        @quick-quiz="handleQuickQuiz"
        @view-material="handleViewMaterial"
        @view-all-materials="handleViewAllMaterials"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { onShow, onPullDownRefresh } from '@dcloudio/uni-app';
import { useUserStore } from '@/stores/userStore';
import { useMaterialStore } from '@/stores/materialStore';
import { useFolderStore } from '@/stores/folderStore';
import { usePracticeStore } from '@/stores/practiceStore';
import { fetchMaterialList } from '@/api/material';
import { fetchFolderList } from '@/api/folder';
import { UNCLASSIFIED_FOLDER_ID } from '@/types/folder';
import type { MaterialItem } from '@/types/material';
import type { FolderItem } from '@/types/folder';
import QuickUploadBar from '@/components/home/QuickUploadBar.vue';
import CourseListSection from '@/components/home/CourseListSection.vue';
import RecentLearningSection from '@/components/home/RecentLearningSection.vue';
import NewbieGuideCard from '@/components/home/NewbieGuideCard.vue';
import { extractLatestDraftPractice } from '@/utils/recentLearning';

const userStore = useUserStore();
const materialStore = useMaterialStore();
const folderStore = useFolderStore();
const practiceStore = usePracticeStore();

const loading = ref(false);
const hasLoadedOnce = ref(false);
const quickUploadRef = ref<InstanceType<typeof QuickUploadBar> | null>(null);

const userDisplayName = computed(() => {
  if (!userStore.isAuthenticated) {
    return '未登录';
  }
  return userStore.profile?.nickname || '认证学员';
});

const greetingText = computed(() => {
  if (!userStore.isAuthenticated) {
    return '登录同步学习进度与定制复习方案';
  }
  return `你好，${userDisplayName.value}，今日保持高效专注`;
});

const recentMaterials = computed(() => materialStore.materialsList);

const activePractice = computed(() => {
  return extractLatestDraftPractice(practiceStore.drafts, materialStore.materialsList);
});

const isNewbie = computed(() => {
  return materialStore.materialsList.length === 0 && !activePractice.value;
});

async function loadDashboardData(showSkeleton = true): Promise<void> {
  if (showSkeleton) {
    loading.value = true;
  }

  practiceStore.loadDraftFromStorage();

  const [foldersRes, materialsRes, unclassifiedRes] = await Promise.allSettled([
    fetchFolderList({ include_archived: true }),
    fetchMaterialList({ page: 1, page_size: 5 }),
    fetchMaterialList({ folder_id: UNCLASSIFIED_FOLDER_ID, page: 1, page_size: 1 }),
  ]);

  if (foldersRes.status === 'fulfilled' && foldersRes.value?.data?.items) {
    folderStore.setFolderList(foldersRes.value.data.items);
  }

  if (materialsRes.status === 'fulfilled' && materialsRes.value?.data?.items) {
    materialStore.setMaterialsList(materialsRes.value.data.items);
  }

  if (unclassifiedRes.status === 'fulfilled') {
    folderStore.setUnclassifiedCount(unclassifiedRes.value?.data?.total ?? 0);
  }

  loading.value = false;
  hasLoadedOnce.value = true;
}

function handleNavigateLogin(): void {
  uni.navigateTo({
    url: '/pages/auth/login',
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

function handleLogout(): void {
  userStore.logout();
}

function handleEnterCourse(folder: FolderItem): void {
  folderStore.setCurrentFolder(folder);
  uni.navigateTo({
    url: `/subpackages/material/pages/course/index?folder_id=${folder.id}`,
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

function handleViewUnclassified(): void {
  uni.navigateTo({
    url: `/subpackages/material/pages/list/index?folder_id=${UNCLASSIFIED_FOLDER_ID}`,
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

function handleCoursesChanged(): void {
  void loadDashboardData(false);
}

async function handleUploadSuccess(): Promise<void> {
  await loadDashboardData(false);
}

function handleStartFirst(): void {
  if (quickUploadRef.value) {
    quickUploadRef.value.open();
  }
}

function handleContinuePractice(practiceId: string): void {
  uni.navigateTo({
    url: `/subpackages/practice/pages/session/index?id=${practiceId}`,
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

function handleQuickQuiz(mat: MaterialItem): void {
  uni.navigateTo({
    url: `/subpackages/material/pages/knowledge-tree/index?material_id=${mat.id}`,
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

function handleViewMaterial(materialId: string): void {
  uni.navigateTo({
    url: `/subpackages/material/pages/detail/index?material_id=${materialId}`,
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

function handleViewAllMaterials(): void {
  uni.navigateTo({
    url: '/subpackages/material/pages/list/index',
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

onMounted(() => {
  loadDashboardData(true);
});

onShow(() => {
  practiceStore.loadDraftFromStorage();
  if (hasLoadedOnce.value && !loading.value) {
    void loadDashboardData(false);
  }
});

onPullDownRefresh(async () => {
  try {
    await loadDashboardData(false);
  } finally {
    uni.stopPullDownRefresh();
  }
});

defineExpose({
  loadDashboardData,
  loading,
  hasLoadedOnce,
  isNewbie,
  activePractice,
  recentMaterials,
});
</script>

<style lang="scss" scoped>
@import './index.scss';
</style>
