<template>
  <view class="login-container">
    <view class="paper-card login-card">
      <text class="title">登录智练</text>
      <text class="desc">一键同步你的个人讲义、作答进度与精准学情诊断报告。</text>
      <button class="paper-btn-primary login-btn" :loading="isLoading" @tap="handleLogin">
        微信一键快速登录
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const isLoading = ref<boolean>(false)

const handleLogin = async () => {
  isLoading.value = true
  try {
    const success = await authStore.loginWithWechat()
    if (success) {
      uni.showToast({ title: '登录成功', icon: 'success' })
      setTimeout(() => {
        uni.switchTab({ url: '/pages/index/index' })
      }, 500)
    }
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
.login-container {
  padding: 48rpx 32rpx;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-card {
  width: 100%;
  padding: 48rpx 36rpx;
  text-align: center;
}
.title {
  display: block;
  font-size: 40rpx;
  font-weight: 700;
  color: #1c1917;
  margin-bottom: 16rpx;
}
.desc {
  display: block;
  font-size: 26rpx;
  color: #78716c;
  line-height: 1.5;
  margin-bottom: 48rpx;
}
.login-btn {
  height: 88rpx;
  font-size: 30rpx;
}
</style>
