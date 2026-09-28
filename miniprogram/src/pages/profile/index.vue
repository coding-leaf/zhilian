<template>
  <view class="profile-page">
    <!-- 用户信息头部卡片 -->
    <view class="user-card">
      <view class="avatar-wrap">
        <view class="avatar-circle">
          <text class="avatar-text">{{ avatarChar }}</text>
        </view>
      </view>
      <view class="user-info">
        <view class="user-name-row">
          <text class="user-nickname">{{
            userStore.isAuthenticated ? userDisplayName : '未登录学员'
          }}</text>
          <text v-if="userStore.isAuthenticated" class="user-tag">正式学员</text>
        </view>
        <text class="user-desc">
          {{
            userStore.isAuthenticated
              ? '学号: ' + (userStore.userId?.slice(0, 8) || '---')
              : '登录后同步学习记录与离线数据'
          }}
        </text>
      </view>
      <button v-if="!userStore.isAuthenticated" class="btn-login-header" @tap="handleLogin">
        立即登录
      </button>
    </view>

    <!-- 学习资产概览 (累计练习数、掌握考点数、已攻克错题数) -->
    <view class="assets-section">
      <text class="section-title">学习资产总览</text>
      <view class="assets-grid">
        <view class="asset-card" @tap="handleNavigateHome">
          <text class="asset-num">{{ totalPracticesCount }}</text>
          <text class="asset-label">累计练习 (次)</text>
        </view>
        <view class="asset-card" @tap="handleNavigateReview">
          <text class="asset-num text-success">{{ masteredKnowledgeCount }}</text>
          <text class="asset-label">已掌握考点</text>
        </view>
        <view class="asset-card" @tap="handleNavigateReview">
          <text class="asset-num text-warning">{{ masteredWrongCount }}</text>
          <text class="asset-label">已攻克错题</text>
        </view>
      </view>
    </view>

    <!-- 课程与治理入口 -->
    <view class="menu-section">
      <text class="section-title">学习管理</text>
      <view class="menu-list">
        <view class="menu-item" @tap="handleOpenArchivedDrawer">
          <view class="menu-left">
            <text class="menu-title">归档课程管理箱</text>
            <text class="menu-sub"
              >查看、恢复或物理清理历史已归档的课程 ({{
                folderStore.archivedFolders.length
              }}个)</text
            >
          </view>
          <text class="menu-arrow">></text>
        </view>
      </view>
    </view>

    <!-- 数据安全与隐私治理专区 (J8) -->
    <view class="menu-section">
      <text class="section-title">数据治理与隐私安全</text>
      <view class="menu-list">
        <view class="menu-item" @tap="handleClearCache">
          <view class="menu-left">
            <text class="menu-title">本地缓存与草稿清理</text>
            <text class="menu-sub">清除本地离线暂存作答与临时文件缓存</text>
          </view>
          <text class="menu-action-label">清理</text>
        </view>
        <view class="menu-item" @tap="handleShowPrivacyPolicy">
          <view class="menu-left">
            <text class="menu-title">数据合规与隐私承诺</text>
            <text class="menu-sub">个人学习数据加密存储与多租户严格隔离说明</text>
          </view>
          <text class="menu-arrow">></text>
        </view>
        <view
          v-if="userStore.isAuthenticated"
          class="menu-item danger-item"
          @tap="handleConfirmDeleteAccount"
        >
          <view class="menu-left">
            <text class="menu-title text-danger">注销账号与彻底抹除数据</text>
            <text class="menu-sub">物理擦除所有资料、题目快照与学习记录（不可逆）</text>
          </view>
          <text class="menu-arrow text-danger">></text>
        </view>
      </view>
    </view>

    <!-- 底部退出登录按钮 -->
    <view v-if="userStore.isAuthenticated" class="logout-section">
      <button class="btn-logout" @tap="handleLogout">退出当前账号</button>
    </view>

    <!-- 归档课程管理抽屉/弹窗 -->
    <view v-if="isArchivedDrawerOpen" class="drawer-mask" @tap="isArchivedDrawerOpen = false">
      <view class="drawer-card" @tap.stop>
        <view class="drawer-header">
          <text class="drawer-title">归档课程管理箱</text>
          <text class="drawer-close" @tap="isArchivedDrawerOpen = false">关闭</text>
        </view>

        <view v-if="folderStore.archivedFolders.length === 0" class="drawer-empty">
          <text class="empty-hint">暂无已归档课程</text>
        </view>

        <view v-else class="drawer-list">
          <view
            v-for="folder in folderStore.archivedFolders"
            :key="folder.id"
            class="archived-item-card"
          >
            <view class="archived-item-info">
              <text class="archived-name">{{ folder.name }}</text>
              <text class="archived-meta">资料数: {{ folder.material_count || 0 }} 篇</text>
            </view>
            <view class="archived-actions">
              <button class="btn-restore" @tap="handleRestoreFolder(folder.id)">恢复</button>
              <button class="btn-delete-perm" @tap="handleDeleteFolderPermanently(folder.id)">
                删除
              </button>
            </view>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { onShow } from '@dcloudio/uni-app';
import { useUserStore } from '@/stores/userStore';
import { useFolderStore } from '@/stores/folderStore';
import { fetchFolderList, restoreFolder, archiveFolder } from '@/api/folder';
import { fetchMasteryOverview, fetchWrongBook } from '@/api/diagnosis';
import { deleteAccount } from '@/api/user';
import { storage } from '@/utils/storage';

const userStore = useUserStore();
const folderStore = useFolderStore();

const isArchivedDrawerOpen = ref(false);
const totalPracticesCount = ref(0);
const masteredKnowledgeCount = ref(0);
const masteredWrongCount = ref(0);

const userDisplayName = computed(() => {
  return userStore.profile?.nickname || '认证学员';
});

const avatarChar = computed(() => {
  if (!userStore.isAuthenticated) return '?';
  const name = userDisplayName.value;
  return name.slice(0, 1).toUpperCase();
});

function handleLogin(): void {
  uni.navigateTo({
    url: '/pages/auth/login',
  });
}

function handleNavigateHome(): void {
  uni.switchTab({
    url: '/pages/index/index',
  });
}

function handleNavigateReview(): void {
  uni.switchTab({
    url: '/pages/review/index',
  });
}

function handleOpenArchivedDrawer(): void {
  isArchivedDrawerOpen.value = true;
  loadFolders();
}

async function handleRestoreFolder(folderId: string): Promise<void> {
  try {
    if (typeof uni.showLoading === 'function') uni.showLoading({ title: '正在恢复...' });
    await restoreFolder(folderId);
    if (typeof uni.hideLoading === 'function') uni.hideLoading();
    uni.showToast({ title: '课程已恢复', icon: 'success' });
    await loadFolders();
  } catch {
    if (typeof uni.hideLoading === 'function') uni.hideLoading();
    uni.showToast({ title: '恢复失败，请重试', icon: 'none' });
  }
}

function handleDeleteFolderPermanently(folderId: string): void {
  uni.showModal({
    title: '彻底删除课程',
    content: '彻底删除后，该课程及归类索引将被物理清理，是否确定删除？',
    confirmText: '确定删除',
    confirmColor: '#EF4444',
    success: async (res) => {
      if (res.confirm) {
        try {
          if (typeof uni.showLoading === 'function') uni.showLoading({ title: '正在清理...' });
          await archiveFolder(folderId);
          folderStore.removeFolder(folderId);
          if (typeof uni.hideLoading === 'function') uni.hideLoading();
          uni.showToast({ title: '已彻底删除', icon: 'success' });
        } catch {
          if (typeof uni.hideLoading === 'function') uni.hideLoading();
          uni.showToast({ title: '删除失败，请重试', icon: 'none' });
        }
      }
    },
  });
}

function handleClearCache(): void {
  uni.showModal({
    title: '清理本地缓存',
    content: '将清除本地离线作答草稿与缓存数据，是否继续？',
    confirmText: '确定清理',
    cancelText: '取消',
    success: (res) => {
      if (res.confirm) {
        try {
          const info = uni.getStorageInfoSync();
          info.keys.forEach((key) => {
            if (key.startsWith('practice_draft_')) {
              uni.removeStorageSync(key);
            }
          });
          uni.showToast({
            title: '缓存清理完成',
            icon: 'success',
          });
        } catch {
          uni.showToast({
            title: '清理完成',
            icon: 'none',
          });
        }
      }
    },
  });
}

function handleShowPrivacyPolicy(): void {
  uni.showModal({
    title: '隐私与数据合规承诺',
    content:
      '智练严格遵循最小必要与数据安全原则：学习资料与题目实行严格的多租户逻辑隔离；传输与存储全程加密；账号注销即刻触发全量数据的物理擦除与永久注销。',
    showCancel: false,
    confirmText: '我已知晓',
  });
}

function handleConfirmDeleteAccount(): void {
  uni.showModal({
    title: '高危警告：注销账号',
    content:
      '注销后，您创建的所有课程文件夹、学习讲义、题目快照与作答诊断记录将被物理删除且无法恢复。是否继续？',
    confirmText: '下一步',
    confirmColor: '#EF4444',
    cancelText: '取消',
    success: (firstRes) => {
      if (firstRes.confirm) {
        uni.showModal({
          title: '最终确认：物理抹除',
          content: '这是最后一步确认。注销后当前学号及所有学习资产将彻底销毁，不可逆回。确定注销？',
          confirmText: '彻底注销',
          confirmColor: '#EF4444',
          cancelText: '我再想想',
          success: async (secondRes) => {
            if (secondRes.confirm) {
              try {
                if (typeof uni.showLoading === 'function')
                  uni.showLoading({ title: '正在执行物理擦除...' });
                await deleteAccount();
                userStore.logout();
                storage.clear();
                if (typeof uni.hideLoading === 'function') uni.hideLoading();
                uni.showToast({
                  title: '账号已彻底注销',
                  icon: 'success',
                });
                setTimeout(() => {
                  uni.reLaunch({
                    url: '/pages/auth/login',
                  });
                }, 800);
              } catch (error) {
                if (typeof uni.hideLoading === 'function') uni.hideLoading();
                uni.showToast({
                  title: '注销失败，请稍后重试',
                  icon: 'none',
                });
              }
            }
          },
        });
      }
    },
  });
}

function handleLogout(): void {
  uni.showModal({
    title: '退出登录',
    content: '退出登录后，本地未提交的练习仍将安全保留，是否确认退出？',
    confirmText: '确认退出',
    cancelText: '取消',
    success: (res) => {
      if (res.confirm) {
        userStore.logout();
        uni.showToast({
          title: '已退出登录',
          icon: 'success',
        });
      }
    },
  });
}

async function loadAssets(): Promise<void> {
  try {
    let practiceCount = 0;
    try {
      const storageInfo = uni.getStorageInfoSync?.();
      if (storageInfo?.keys) {
        practiceCount = storageInfo.keys.filter((k: string) =>
          k.startsWith('practice_draft_'),
        ).length;
      }
    } catch {
      // 忽略平台不支持
    }
    totalPracticesCount.value = practiceCount;

    const [overviewRes, wrongRes] = await Promise.all([
      fetchMasteryOverview().catch(() => null),
      fetchWrongBook({ is_mastered: true }).catch(() => null),
    ]);

    if (overviewRes?.data) {
      masteredKnowledgeCount.value = overviewRes.data.mastered_count || 0;
      if (overviewRes.data.total_points && totalPracticesCount.value === 0) {
        totalPracticesCount.value = overviewRes.data.total_points;
      }
    }

    if (wrongRes?.data?.items) {
      masteredWrongCount.value = wrongRes.data.items.length;
    }
  } catch {
    // 静默兜底
  }
}

async function loadFolders(): Promise<void> {
  try {
    const res = await fetchFolderList({ include_archived: true });
    if (res.data?.items) {
      folderStore.setFolderList(res.data.items);
    }
  } catch {
    // 静默兜底
  }
}

onMounted(() => {
  if (userStore.isAuthenticated) {
    userStore.hydrateProfile();
  }
  loadAssets();
  loadFolders();
});

onShow(() => {
  if (userStore.isAuthenticated) {
    userStore.hydrateProfile();
  }
  loadAssets();
  loadFolders();
});
</script>

<style lang="scss" scoped src="./profile.scss"></style>
