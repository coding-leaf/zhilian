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
      <!-- 掌握度全景状态栏 -->
      <MasteryDashboardBar
        :overview="reportStore.masteryOverview"
        :loading="loading"
        @tap-detail="handleNavigateReport"
      />

      <!-- 快捷上传横幅 -->
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
import { usePracticeStore } from '@/stores/practiceStore';
import { useReportStore } from '@/stores/reportStore';
import { fetchMasteryOverview } from '@/api/diagnosis';
import { fetchMaterialList } from '@/api/material';
import type { MaterialItem } from '@/types/material';
import MasteryDashboardBar from '@/components/home/MasteryDashboardBar.vue';
import QuickUploadBar from '@/components/home/QuickUploadBar.vue';
import RecentLearningSection from '@/components/home/RecentLearningSection.vue';
import NewbieGuideCard from '@/components/home/NewbieGuideCard.vue';
import { extractLatestDraftPractice } from '@/utils/recentLearning';

const userStore = useUserStore();
const materialStore = useMaterialStore();
const practiceStore = usePracticeStore();
const reportStore = useReportStore();

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

  const [masteryRes, materialsRes] = await Promise.allSettled([
    fetchMasteryOverview(),
    fetchMaterialList({ page: 1, page_size: 5 }),
  ]);

  if (masteryRes.status === 'fulfilled' && masteryRes.value?.data) {
    reportStore.setMasteryOverview(masteryRes.value.data);
  }

  if (materialsRes.status === 'fulfilled' && materialsRes.value?.data?.items) {
    materialStore.setMaterialsList(materialsRes.value.data.items);
  }

  loading.value = false;
  hasLoadedOnce.value = true;
}

function handleNavigateLogin(): void {
  uni.navigateTo({
    url: '/pages/auth/login',
  });
}

function handleLogout(): void {
  userStore.logout();
}

function handleNavigateReport(): void {
  uni.navigateTo({
    url: '/subpackages/report/pages/detail/index',
  });
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
  });
}

function handleQuickQuiz(mat: MaterialItem): void {
  uni.navigateTo({
    url: `/subpackages/material/pages/knowledge-tree/index?id=${mat.id}`,
  });
}

function handleViewMaterial(materialId: string): void {
  uni.navigateTo({
    url: `/subpackages/material/pages/detail/index?id=${materialId}`,
  });
}

function handleViewAllMaterials(): void {
  uni.navigateTo({
    url: '/subpackages/material/pages/list/index',
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
