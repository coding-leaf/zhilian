<template>
  <view class="index-container">
    <!-- 顶部温润书卷 Hero Header -->
    <view class="hero-section">
      <view class="hero-header-row">
        <view class="hero-tag">智练 · 自主学习平台</view>
        <view v-if="!authStore.isLoggedIn()" class="login-trigger-btn" @tap="goToLogin">
          <text class="login-trigger-text">快捷登录</text>
        </view>
        <view v-else class="user-status-pill">
          <text class="user-status-text">已登录</text>
        </view>
      </view>
      <text class="hero-title">深阅读，专研习</text>
      <text class="hero-subtitle">上传一份讲义，开启针对性智能测验与精准学情诊断</text>
    </view>

    <!-- 资料快速导入入口 Card -->
    <view class="paper-card upload-card" @tap="handleChooseFile">
      <view class="upload-icon-wrapper">
        <text class="upload-icon">📄</text>
      </view>
      <view class="upload-info">
        <text class="upload-title">导入学习资料</text>
        <text class="upload-desc">支持微信聊天文件、文档 (PDF/DOCX) 或图片讲义</text>
      </view>
      <view class="upload-action">
        <text class="action-btn-text">选择</text>
      </view>
    </view>

    <!-- 快捷出题与学习进度 -->
    <view class="section-title-row">
      <text class="section-title">我的讲义库</text>
      <text class="section-refresh" @tap="refreshMaterials">刷新</text>
    </view>

    <!-- 讲义列表 -->
    <view class="materials-list">
      <view
        v-for="item in materialStore.materialList"
        :key="item.id"
        class="paper-card material-card"
        @tap="goToDetail(item)"
      >
        <view class="card-header">
          <text class="material-name">{{ item.title || '无标题资料' }}</text>
          <view :class="['status-badge', `status-${item.status.toLowerCase()}`]">
            {{ getStatusText(item.status) }}
          </view>
        </view>
        <view class="card-footer">
          <text class="meta-date">{{ item.created_at?.slice(0, 10) || '今日' }}</text>
          <text v-if="item.status === 'PARSED'" class="action-link">智能出题 →</text>
        </view>
      </view>

      <view v-if="materialStore.materialList.length === 0" class="empty-state">
        <text class="empty-text">暂无导入资料，点击上方卡片立即体验</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { onPullDownRefresh } from '@dcloudio/uni-app'
import { useMaterialStore } from '@/stores/material'
import { useAuthStore } from '@/stores/auth'
import type { MaterialItem } from '@/types'

const materialStore = useMaterialStore()
const authStore = useAuthStore()

onMounted(async () => {
  if (!authStore.isLoggedIn()) {
    await authStore.loginWithWechat()
  }
  await materialStore.loadMaterialList()
})

onPullDownRefresh(async () => {
  await materialStore.loadMaterialList()
  uni.stopPullDownRefresh()
})

const refreshMaterials = () => {
  materialStore.loadMaterialList()
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'PARSED':
      return '已解析'
    case 'PROCESSING':
      return '解析中'
    case 'FAILED':
      return '解析失败'
    default:
      return '待处理'
  }
}

const handleChooseFile = () => {
  // #ifdef MP-WEIXIN
  const wxAny = (globalThis as any).wx || (typeof wx !== 'undefined' ? wx : null)
  if (wxAny && wxAny.chooseMessageFile) {
    wxAny.chooseMessageFile({
      count: 1,
      type: 'all',
      success: async (res: any) => {
        const file = res.tempFiles?.[0]
        if (file) {
          uni.showLoading({ title: '正在上传讲义...' })
          try {
            const item = await materialStore.upload(file.path, file.name)
            uni.hideLoading()
            uni.showToast({ title: '上传成功', icon: 'success' })
            goToDetail(item)
          } catch {
            uni.hideLoading()
          }
        }
      },
      fail: () => {
        // 允许取消
      },
    })
    return
  }
  // #endif
  uni.chooseImage({
    count: 1,
    success: async (res: any) => {
      const path = res.tempFilePaths?.[0]
      if (path) {
        uni.showLoading({ title: '正在上传讲义...' })
        try {
          const item = await materialStore.upload(path, '学习讲义')
          uni.hideLoading()
          goToDetail(item)
        } catch {
          uni.hideLoading()
        }
      }
    },
  })
}

const goToDetail = (item: MaterialItem) => {
  uni.navigateTo({
    url: `/subpackages/material/pages/course/index?id=${item.id}`,
  })
}

const goToLogin = () => {
  uni.navigateTo({
    url: '/pages/auth/login',
  })
}
</script>

<style scoped>
.index-container {
  padding: 32rpx;
  min-height: 100vh;
}

.hero-section {
  padding: 32rpx 8rpx 48rpx 8rpx;
}

.hero-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.hero-tag {
  display: inline-block;
  font-size: 22rpx;
  color: #1e3a8a;
  background-color: rgba(30, 58, 138, 0.08);
  padding: 6rpx 16rpx;
  border-radius: 6rpx;
  font-weight: 500;
}

.login-trigger-btn {
  background: #1e3a8a;
  padding: 8rpx 20rpx;
  border-radius: 24rpx;
}

.login-trigger-text {
  font-size: 22rpx;
  color: #ffffff;
  font-weight: 600;
}

.user-status-pill {
  background: rgba(13, 148, 136, 0.1);
  padding: 6rpx 16rpx;
  border-radius: 20rpx;
}

.user-status-text {
  font-size: 22rpx;
  color: #0d9488;
  font-weight: 500;
}

.hero-title {
  display: block;
  font-size: 44rpx;
  font-weight: 700;
  color: #1c1917;
  letter-spacing: -0.5rpx;
  margin-bottom: 12rpx;
}

.hero-subtitle {
  display: block;
  font-size: 26rpx;
  color: #78716c;
  line-height: 1.5;
}

.upload-card {
  padding: 36rpx 32rpx;
  display: flex;
  align-items: center;
  margin-bottom: 48rpx;
}

.upload-icon-wrapper {
  font-size: 48rpx;
  margin-right: 24rpx;
}

.upload-info {
  flex: 1;
}

.upload-title {
  display: block;
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1917;
  margin-bottom: 6rpx;
}

.upload-desc {
  display: block;
  font-size: 24rpx;
  color: #78716c;
}

.upload-action {
  padding-left: 16rpx;
}

.action-btn-text {
  font-size: 26rpx;
  color: #1e3a8a;
  font-weight: 600;
  background: #f0f4ff;
  padding: 10rpx 24rpx;
  border-radius: 8rpx;
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
  padding: 0 4rpx;
}

.section-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1917;
}

.section-refresh {
  font-size: 24rpx;
  color: #78716c;
}

.material-card {
  padding: 28rpx 32rpx;
  margin-bottom: 20rpx;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.material-name {
  font-size: 30rpx;
  font-weight: 500;
  color: #1c1917;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 16rpx;
}

.status-badge {
  font-size: 22rpx;
  padding: 4rpx 14rpx;
  border-radius: 6rpx;
}

.status-parsed {
  background: #ecfdf5;
  color: #059669;
}

.status-processing {
  background: #fffbeb;
  color: #d97706;
}

.status-failed {
  background: #fef2f2;
  color: #dc2626;
}

.status-waiting {
  background: #f5f5f4;
  color: #78716c;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.meta-date {
  font-size: 24rpx;
  color: #a8a29e;
}

.action-link {
  font-size: 26rpx;
  color: #1e3a8a;
  font-weight: 500;
}

.empty-state {
  text-align: center;
  padding: 64rpx 0;
}

.empty-text {
  font-size: 26rpx;
  color: #a8a29e;
}
</style>
