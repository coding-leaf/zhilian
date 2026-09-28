<template>
  <view class="review-container">
    <view class="paper-card summary-card">
      <text class="title">学情综合概览</text>
      <text class="desc">记录你的历次智能出题练习与薄弱点演进轨迹。</text>
    </view>
  </view>
</template>

<script setup lang="ts">
</script>

<style scoped>
.review-container {
  padding: 32rpx;
  min-height: 100vh;
}
.summary-card {
  padding: 36rpx 32rpx;
}
.title {
  display: block;
  font-size: 34rpx;
  font-weight: 700;
  color: #1c1917;
  margin-bottom: 8rpx;
}
.desc {
  font-size: 26rpx;
  color: #78716c;
}
</style>
