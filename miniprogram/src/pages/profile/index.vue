<template>
  <view class="profile-container">
    <!-- 用户信息卡片 -->
    <view class="paper-card profile-card">
      <view class="avatar-box" @tap="openEditModal">
        <image
          v-if="authStore.user?.avatar_url"
          class="avatar-image"
          :src="authStore.user.avatar_url"
          mode="aspectFill"
        />
        <text v-else class="avatar-placeholder">👤</text>
        <view class="edit-badge">✎</view>
      </view>
      <view class="user-meta" @tap="openEditModal">
        <view class="name-row">
          <text class="user-name">{{ authStore.user?.nickname || (authStore.isLoggedIn() ? '智练学员' : '未登录') }}</text>
          <text v-if="authStore.isLoggedIn()" class="edit-hint">编辑</text>
        </view>
        <text class="user-id">ID: {{ authStore.user?.id || '点击下方登录' }}</text>
      </view>
    </view>

    <!-- 学习统计面板 -->
    <view class="paper-card stats-card">
      <text class="card-title">学习足迹</text>
      <view class="stats-grid">
        <view class="grid-item">
          <text class="grid-num">{{ folderStore.folders.length }}</text>
          <text class="grid-label">已建课程</text>
        </view>
        <view class="grid-item">
          <text class="grid-num">{{ readyMaterialCount }}</text>
          <text class="grid-label">就绪讲义</text>
        </view>
        <view class="grid-item">
          <text class="grid-num">{{ totalKnowledgePoints }}</text>
          <text class="grid-label">涵盖考点</text>
        </view>
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

    <!-- 修改个人信息弹窗 -->
    <view v-if="showEditModal" class="modal-overlay" @tap.self="closeEditModal">
      <view class="modal-content paper-card">
        <view class="modal-header">
          <text class="modal-title">编辑个人资料</text>
          <text class="modal-close" @tap="closeEditModal">✕</text>
        </view>
        <view class="modal-body">
          <view class="form-item">
            <text class="form-label">昵称</text>
            <input
              v-model="editNickname"
              class="form-input"
              :maxlength="20"
              placeholder="请输入新昵称"
            />
          </view>
          <view class="form-item">
            <text class="form-label">头像链接 (URL)</text>
            <input
              v-model="editAvatarUrl"
              class="form-input"
              placeholder="请输入头像图片地址或保持默认"
            />
          </view>
        </view>
        <view class="modal-footer">
          <button class="modal-cancel-btn" @tap="closeEditModal">取消</button>
          <button
            class="paper-btn-primary modal-confirm-btn"
            :loading="isSaving"
            @tap="handleSaveProfile"
          >
            保存修改
          </button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useFolderStore } from '@/stores/folder'

const authStore = useAuthStore()
const folderStore = useFolderStore()

const showEditModal = ref(false)
const editNickname = ref('')
const editAvatarUrl = ref('')
const isSaving = ref(false)

const readyMaterialCount = computed(() => {
  return folderStore.folders.reduce((acc, f) => acc + (f.ready_material_count || 0), 0)
})

const totalKnowledgePoints = computed(() => {
  return folderStore.folders.reduce((acc, f) => acc + (f.knowledge_point_count || 0), 0)
})

onMounted(async () => {
  if (authStore.isLoggedIn()) {
    if (!authStore.user) {
      await authStore.fetchProfile()
    }
    await folderStore.loadFolders()
  }
})

const openEditModal = () => {
  if (!authStore.isLoggedIn()) {
    goToLogin()
    return
  }
  editNickname.value = authStore.user?.nickname || ''
  editAvatarUrl.value = authStore.user?.avatar_url || ''
  showEditModal.value = true
}

const closeEditModal = () => {
  showEditModal.value = false
}

const handleSaveProfile = async () => {
  if (!editNickname.value.trim()) {
    uni.showToast({ title: '昵称不能为空', icon: 'none' })
    return
  }
  isSaving.value = true
  try {
    await authStore.updateProfile({
      nickname: editNickname.value.trim(),
      avatar_url: editAvatarUrl.value.trim() || undefined,
    })
    uni.showToast({ title: '修改成功', icon: 'success' })
    closeEditModal()
  } catch (err: any) {
    uni.showToast({ title: err?.message || '保存失败', icon: 'none' })
  } finally {
    isSaving.value = false
  }
}

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
  width: 100rpx;
  height: 100rpx;
  border-radius: 50rpx;
  background: #f5f5f4;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 48rpx;
  margin-right: 24rpx;
  position: relative;
  overflow: hidden;
  border: 1px solid #e7e5e4;
}

.avatar-image {
  width: 100%;
  height: 100%;
}

.edit-badge {
  position: absolute;
  bottom: 0;
  right: 0;
  background: rgba(30, 58, 138, 0.8);
  color: #ffffff;
  font-size: 18rpx;
  width: 32rpx;
  height: 32rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-meta {
  flex: 1;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.user-name {
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1917;
}

.edit-hint {
  font-size: 22rpx;
  color: #1e3a8a;
  background: #eff6ff;
  padding: 2rpx 10rpx;
  border-radius: 6rpx;
}

.user-id {
  display: block;
  font-size: 24rpx;
  color: #a8a29e;
  margin-top: 6rpx;
}

.stats-card {
  padding: 32rpx;
  margin-bottom: 32rpx;
}

.card-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #1c1917;
  display: block;
  margin-bottom: 24rpx;
}

.stats-grid {
  display: flex;
  justify-content: space-around;
  align-items: center;
}

.grid-item {
  text-align: center;
}

.grid-num {
  font-size: 38rpx;
  font-weight: 700;
  color: #1e3a8a;
  display: block;
}

.grid-label {
  font-size: 24rpx;
  color: #78716c;
  margin-top: 4rpx;
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

/* 弹窗 */
.modal-overlay {
  position: fixed;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(2px);
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32rpx;
}

.modal-content {
  width: 100%;
  max-width: 600rpx;
  padding: 36rpx 32rpx;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
}

.modal-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1917;
}

.modal-close {
  font-size: 32rpx;
  color: #a8a29e;
  padding: 8rpx;
}

.form-item {
  margin-bottom: 24rpx;
}

.form-label {
  display: block;
  font-size: 26rpx;
  color: #57534e;
  font-weight: 500;
  margin-bottom: 12rpx;
}

.form-input {
  width: 100%;
  height: 76rpx;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
  border-radius: 8rpx;
  padding: 0 16rpx;
  font-size: 26rpx;
}

.modal-footer {
  display: flex;
  gap: 16rpx;
  margin-top: 32rpx;
}

.modal-cancel-btn {
  flex: 1;
  height: 76rpx;
  font-size: 26rpx;
  background: #f5f5f4;
  color: #57534e;
  border-radius: 8rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-confirm-btn {
  flex: 1;
  height: 76rpx;
  font-size: 26rpx;
}
</style>

