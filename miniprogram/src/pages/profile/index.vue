<template>
  <view class="profile-container">
    <view class="paper-card profile-card">
      <view class="avatar-box">
        <text class="avatar-placeholder">👤</text>
      </view>
      <view class="user-meta">
        <text class="user-name">{{ authStore.user?.nickname || (authStore.isLoggedIn() ? '智练学员' : '未登录') }}</text>
        <text class="user-id">ID: {{ authStore.user?.id || '点击下方登录' }}</text>
      </view>
    </view>

    <!-- 登录/退出控制卡片 -->
    <view class="action-card-section">
      <button
        v-if="!authStore.isLoggedIn()"
        class="paper-btn-primary action-btn"
        @tap="goToLogin"
      >
        微信一键登录
      </button>

      <button
        v-else
        class="logout-btn"
        @tap="handleLogout"
      >
        退出当前账号
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

onMounted(async () => {
  if (authStore.isLoggedIn() && !authStore.user) {
    await authStore.fetchProfile()
  }
})

const goToLogin = () => {
  uni.navigateTo({
    url: '/pages/auth/login',
  })
}

const handleLogout = () => {
  uni.showModal({
    title: '退出登录',
    content: '确认退出当前账号吗？',
    confirmColor: '#B91C1C',
    success: (res) => {
      if (res.confirm) {
        authStore.clearAuth()
        uni.showToast({ title: '已退出登录', icon: 'none' })
      }
    },
  })
}
</script>

<style scoped>
.profile-container {
  padding: 32rpx;
  min-height: 100vh;
}

.profile-card {
  padding: 36rpx 32rpx;
  display: flex;
  align-items: center;
  margin-bottom: 32rpx;
}

.avatar-box {
  width: 96rpx;
  height: 96rpx;
  border-radius: 48rpx;
  background: #f5f5f4;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 48rpx;
  margin-right: 24rpx;
}

.user-name {
  display: block;
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1917;
}

.user-id {
  font-size: 24rpx;
  color: #a8a29e;
}

.action-card-section {
  margin-top: 48rpx;
}

.action-btn {
  height: 88rpx;
  font-size: 30rpx;
}

.logout-btn {
  height: 88rpx;
  background: #fee2e2;
  color: #b91c1c;
  font-size: 30rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 500;
}
</style>
