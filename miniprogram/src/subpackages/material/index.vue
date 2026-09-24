<template>
  <view class="subpackage-page">
    <view class="subpackage-card">
      <view class="page-title">资料管理</view>
      <view class="page-desc">资料上传、解析切片与知识点大纲功能预留</view>
      <button class="back-btn" @tap="handleNavigateHome">返回工作台</button>
    </view>
  </view>
</template>

<script setup lang="ts">
function handleNavigateHome(): void {
  uni.reLaunch({
    url: '/pages/index/index',
  });
}
</script>

<style lang="scss" scoped>
.subpackage-page {
  min-height: 100vh;
  background-color: #f8fafc;
  padding: 32rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}

.subpackage-card {
  width: 100%;
  background-color: #ffffff;
  border-radius: 24rpx;
  padding: 48rpx 36rpx;
  border: 1px solid #e2e8f0;
  box-shadow:
    0 8rpx 24rpx -4rpx rgba(15, 23, 42, 0.05),
    0 2rpx 6rpx -1rpx rgba(15, 23, 42, 0.02);
  text-align: center;
}

.page-title {
  font-size: 36rpx;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 12rpx;
}

.page-desc {
  font-size: 24rpx;
  color: #64748b;
  margin-bottom: 40rpx;
}

.back-btn {
  height: 80rpx;
  line-height: 80rpx;
  border-radius: 9999rpx;
  background-color: #2563eb;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 600;
  border: none;
}
</style>
