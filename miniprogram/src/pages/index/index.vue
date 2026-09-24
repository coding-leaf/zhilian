<template>
  <view class="dashboard-page">
    <view class="dashboard-header">
      <view class="brand-title">智练工作台</view>
      <view class="user-status-bar">
        <text class="status-label">当前状态：</text>
        <text class="status-value">{{ userDisplayName }}</text>
        <button v-if="!userStore.isAuthenticated" class="auth-btn" @tap="handleNavigateLogin">
          登录账号
        </button>
        <button v-else class="auth-btn logout-btn" @tap="handleLogout">退出登录</button>
      </view>
    </view>

    <view class="metrics-grid">
      <view class="metric-card" @tap="handleNavigateMaterial">
        <view class="card-meta">资料总数</view>
        <view class="card-number">{{ materialCount }}</view>
        <view class="card-action">资料管理</view>
      </view>

      <view class="metric-card" @tap="handleNavigatePractice">
        <view class="card-meta">练习进度</view>
        <view class="card-number">{{ practiceProgressText }}</view>
        <view class="card-action">进入练习</view>
      </view>

      <view class="metric-card" @tap="handleNavigateReport">
        <view class="card-meta">学情诊断</view>
        <view class="card-number">{{ masteryScoreText }}</view>
        <view class="card-action">诊断报告</view>
      </view>

      <view class="metric-card" @tap="handleNavigateMistakes">
        <view class="card-meta">待巩固错题</view>
        <view class="card-number">{{ mistakeCountText }}</view>
        <view class="card-action">错题复习</view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useUserStore } from '@/stores/userStore';
import { useMaterialStore } from '@/stores/materialStore';
import { usePracticeStore } from '@/stores/practiceStore';
import { useReportStore } from '@/stores/reportStore';

const userStore = useUserStore();
const materialStore = useMaterialStore();
const practiceStore = usePracticeStore();
const reportStore = useReportStore();

const userDisplayName = computed(() => {
  if (!userStore.isAuthenticated) {
    return '未登录';
  }
  return userStore.profile?.nickname || '认证学员';
});

const materialCount = computed(() => {
  return materialStore.materialsList.length;
});

const practiceProgressText = computed(() => {
  const total = practiceStore.questions.length;
  if (total === 0) {
    return '暂无练习';
  }
  return `${practiceStore.currentIndex + 1}/${total}`;
});

const masteryScoreText = computed(() => {
  if (!reportStore.currentReport) {
    return '未诊断';
  }
  return `${Math.round(reportStore.overallMasteryRate)}分`;
});

const mistakeCountText = computed(() => {
  if (!reportStore.currentReport) {
    return '0道';
  }
  return `${reportStore.weakPointCount}道`;
});

function handleNavigateLogin(): void {
  uni.navigateTo({
    url: '/pages/auth/login',
  });
}

function handleLogout(): void {
  userStore.logout();
}

function handleNavigateMaterial(): void {
  uni.navigateTo({
    url: '/subpackages/material/index',
  });
}

function handleNavigatePractice(): void {
  uni.navigateTo({
    url: '/subpackages/material/index',
  });
}

function handleNavigateReport(): void {
  uni.navigateTo({
    url: '/subpackages/report/index',
  });
}

function handleNavigateMistakes(): void {
  uni.navigateTo({
    url: '/subpackages/report/index',
  });
}
</script>

<style lang="scss" scoped>
.dashboard-page {
  min-height: 100vh;
  background-color: #f8fafc;
  padding: 32rpx;
  box-sizing: border-box;
}

.dashboard-header {
  margin-bottom: 32rpx;
}

.brand-title {
  font-size: 36rpx;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 16rpx;
}

.user-status-bar {
  display: flex;
  align-items: center;
  font-size: 26rpx;
}

.status-label {
  color: #64748b;
}

.status-value {
  color: #0f172a;
  font-weight: 600;
  margin-right: 24rpx;
}

.auth-btn {
  font-size: 22rpx;
  padding: 6rpx 20rpx;
  border-radius: 9999rpx;
  background-color: #2563eb;
  color: #ffffff;
  border: none;
  line-height: 1.5;
  margin: 0;

  &.logout-btn {
    background-color: #f1f5f9;
    color: #64748b;
  }
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24rpx;
}

.metric-card {
  background-color: #ffffff;
  border-radius: 24rpx;
  padding: 28rpx;
  border: 1px solid #e2e8f0;
  box-shadow:
    0 8rpx 24rpx -4rpx rgba(15, 23, 42, 0.05),
    0 2rpx 6rpx -1rpx rgba(15, 23, 42, 0.02);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 180rpx;
}

.card-meta {
  font-size: 24rpx;
  color: #64748b;
}

.card-number {
  font-size: 36rpx;
  font-weight: 700;
  color: #2563eb;
  margin: 12rpx 0;
}

.card-action {
  font-size: 22rpx;
  color: #64748b;
}
</style>
