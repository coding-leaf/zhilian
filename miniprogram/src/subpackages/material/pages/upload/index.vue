<template>
  <view class="upload-page-container">
    <view class="paper-card upload-box">
      <text class="title">导入资料与质检</text>
      <text class="desc">支持选取微信聊天文件、文档 (PDF/DOCX) 或图片进行深度知识提取。</text>
    </view>
  </view>
</template>

<script setup lang="ts">
</script>

<style scoped>
.upload-page-container {
  padding: 32rpx;
  min-height: 100vh;
}
.upload-box {
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
