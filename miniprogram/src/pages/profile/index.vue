<template>
  <view class="profile-container">
    <!-- 用户信息卡片 -->
    <view class="paper-card profile-card">
      <view class="avatar-box" @tap="chooseAvatar">
        <image
          v-if="authStore.user?.avatar_url"
          class="avatar-image"
          :src="authStore.user.avatar_url"
          mode="aspectFill"
        />
        <text v-else class="avatar-placeholder">{{ avatarInitial }}</text>
        <view class="edit-badge">改</view>
      </view>
      <view class="user-meta" @tap="openEditModal">
        <view class="name-row">
          <text class="user-name">{{ displayName }}</text>
          <text v-if="authStore.isLoggedIn()" class="edit-hint">编辑</text>
        </view>
        <text class="user-id">ID: {{ authStore.user?.id || '点击下方登录' }}</text>
      </view>
    </view>

    <!-- 学习统计面板 -->
    <LearningStatisticsCard :state="statisticsState" @retry="refreshStatistics" />

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

    <ProfileEditModal
      v-model:visible="showEditModal"
      :initial-nickname="authStore.user?.nickname || ''"
      :uploading-avatar="isUploadingAvatar"
      :saving="isSaving"
      @choose-avatar="chooseAvatar"
      @save="handleSaveProfile"
    />
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import { useAuthStore } from '@/stores/auth'
import LearningStatisticsCard from './components/LearningStatisticsCard.vue'
import ProfileEditModal from './components/ProfileEditModal.vue'
import { useLearningStatistics } from './composables/useLearningStatistics'

const authStore = useAuthStore()
const { state: statisticsState, refresh: refreshStatistics } = useLearningStatistics()

const showEditModal = ref(false)
const isSaving = ref(false)
const isUploadingAvatar = ref(false)

const displayName = computed(
  () => authStore.user?.nickname || (authStore.isLoggedIn() ? '智练学员' : '未登录'),
)

const avatarInitial = computed(() => (displayName.value ? displayName.value.slice(0, 1) : '学'))

onShow(() => {
  if (authStore.isLoggedIn() && !authStore.user) {
    void authStore.fetchProfile()
  }
  return refreshStatistics()
})

onPullDownRefresh(async () => {
  try {
    await refreshStatistics()
  } finally {
    uni.stopPullDownRefresh()
  }
})

const goToLogin = () => {
  uni.navigateTo({
    url: '/pages/auth/login',
    fail: () => uni.showToast({ title: '打开登录页失败', icon: 'none' }),
  })
}

const openEditModal = () => {
  if (!authStore.isLoggedIn()) {
    goToLogin()
    return
  }
  showEditModal.value = true
}

const chooseAvatar = () => {
  if (!authStore.isLoggedIn()) return goToLogin()
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success: async ({ tempFilePaths }) => {
      const path = tempFilePaths[0]
      if (!path) return
      isUploadingAvatar.value = true
      try {
        await authStore.updateAvatar(path)
        uni.showToast({ title: '头像已更新', icon: 'success' })
      } catch {
        uni.showToast({ title: '头像上传失败，原头像已保留', icon: 'none' })
      } finally {
        isUploadingAvatar.value = false
      }
    },
  })
}

const handleSaveProfile = async (nickname: string) => {
  isSaving.value = true
  try {
    await authStore.updateProfile({ nickname })
    uni.showToast({ title: '修改成功', icon: 'success' })
    showEditModal.value = false
  } catch (err: any) {
    uni.showToast({ title: err?.message || '保存失败', icon: 'none' })
  } finally {
    isSaving.value = false
  }
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

<style lang="scss" scoped>
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
  background: var(--color-blue-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 24rpx;
  position: relative;
  overflow: hidden;
  border: 1px solid var(--color-paper-border);
}

.avatar-placeholder {
  font-size: 36rpx;
  font-weight: 700;
  color: var(--color-academic-blue);
}

.avatar-image {
  width: 100%;
  height: 100%;
}

.edit-badge {
  position: absolute;
  bottom: 0;
  right: 0;
  background: var(--color-blue-badge);
  color: var(--color-ink-on-primary);
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
  color: var(--color-ink-primary);
}

.edit-hint {
  font-size: 22rpx;
  color: var(--color-academic-blue);
  background: var(--color-blue-bg);
  padding: 2rpx 10rpx;
  border-radius: 6rpx;
}

.user-id {
  display: block;
  font-size: 24rpx;
  color: var(--color-ink-muted);
  margin-top: 6rpx;
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
  background: var(--color-danger-bg-soft);
  color: var(--color-wrong);
  font-size: 30rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 500;
}
</style>
