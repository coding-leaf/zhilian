<template>
  <view class="index-container">
    <!-- 顶部温润书卷 Hero Header -->
    <view class="hero-section">
      <view class="hero-header-row">
        <view class="hero-tag">智练 · 智能学研闭环</view>
        <view v-if="!authStore.isLoggedIn()" class="login-trigger-btn" @tap="goToLogin">
          <text class="login-trigger-text">快捷登录</text>
        </view>
        <view v-else class="user-status-pill">
          <text class="user-status-text">{{ authStore.user?.nickname || '学术探索者' }}</text>
        </view>
      </view>
      <text class="hero-title">深阅读，专研习</text>
      <text class="hero-subtitle">课程知识拓扑抽取 · 多题型针对性刷题 · 错题举一反三</text>
    </view>

    <FolderFilterBar
      :folders="folderStore.folders"
      :current-folder-id="folderStore.currentFolderId"
      :active-folder="activeFolderDetail"
      @select="switchFolder"
      @create="openCreateFolderModal"
      @rename="openRenameFolder"
      @archive="confirmArchiveFolder"
    />

    <!-- 资料快速导入入口 Card -->
    <view class="paper-card upload-card" @tap="chooseFile">
      <view class="upload-icon-badge">
        <text class="upload-icon-text">资料</text>
      </view>
      <view class="upload-info">
        <text class="upload-title">导入学习资料</text>
        <text class="upload-desc">
          {{ currentFolderName ? `将导入至「${currentFolderName}」` : '支持微信聊天文档 (PDF/DOCX) 或图片讲义' }}
        </text>
      </view>
      <view class="upload-action">
        <text class="action-btn-text">上传</text>
      </view>
    </view>

    <!-- 课程快捷刷题入口 (如果当前课程有就绪考点) -->
    <view
      v-if="activeFolderDetail && activeFolderDetail.knowledge_point_count > 0"
      class="paper-card course-quick-practice"
      @tap="goToCourseGenerate"
    >
      <view class="cqp-info">
        <text class="cqp-title">课程全景刷题</text>
        <text class="cqp-desc">当前课程涵盖 {{ activeFolderDetail.knowledge_point_count }} 个核心考点，点击自选知识点组卷</text>
      </view>
      <text class="cqp-arrow">→</text>
    </view>

    <!-- 讲义列表 -->
    <view class="section-title-row">
      <text class="section-title">课程讲义库</text>
      <view class="title-right">
        <text class="section-refresh" @tap="refreshMaterials">刷新</text>
      </view>
    </view>

    <view class="materials-list">
      <MaterialItemCard
        v-for="item in materialStore.materialList"
        :key="item.id"
        :item="item"
        :deleting="deletingId === item.id"
        @open="goToDetail"
        @parse="handleManualParse"
        @questions="goToQuestions"
        @delete="requestDelete"
      />

      <view v-if="materialStore.materialList.length === 0" class="empty-state">
        <text class="empty-text">当前分类下暂无讲义，点击上方卡片导入</text>
      </view>
    </view>

    <!-- 课程全局悬浮助教入口 -->
    <view class="floating-coach-btn" @tap="showCoachDrawer = true">
      <text class="coach-btn-tag">AI</text>
      <text class="coach-btn-text">助教</text>
    </view>

    <AiCoachDrawer
      v-model:visible="showCoachDrawer"
      title="课程随身助教"
      :context-text="coachContextText"
      :folder-id="activeFolderDetail?.id"
    />

    <FolderFormModal
      v-model:visible="showFolderModal"
      :renaming="folderToRename"
      :initial-name="initialFolderName"
      :submitting="isCreatingFolder"
      @submit="submitFolderModal"
    />
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onPullDownRefresh } from '@dcloudio/uni-app'
import { useMaterialStore } from '@/stores/material'
import { useAuthStore } from '@/stores/auth'
import { useFolderStore } from '@/stores/folder'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import { canStartMaterialParse } from '@/utils/materialState'
import { createPoller } from '@/utils/poller'
import type { MaterialItem } from '@/types'
import FolderFilterBar from './components/FolderFilterBar.vue'
import FolderFormModal from './components/FolderFormModal.vue'
import MaterialItemCard from './components/MaterialItemCard.vue'
import { useMaterialDelete } from './composables/useMaterialDelete'
import { useFolderModal } from './composables/useFolderModal'
import { useMaterialUpload } from './composables/useMaterialUpload'

const materialStore = useMaterialStore()
const authStore = useAuthStore()
const folderStore = useFolderStore()
const parsePoller = createPoller()

const { deletingId, requestDelete } = useMaterialDelete({
  deleteMaterial: materialStore.deleteMaterial,
})

const showCoachDrawer = ref(false)

const currentFolderName = computed(() => {
  if (folderStore.currentFolderId === 'all') return ''
  if (folderStore.currentFolderId === '__none__') return '未分类'
  return folderStore.folders.find((f) => f.id === folderStore.currentFolderId)?.name || ''
})

const activeFolderDetail = computed(() => {
  if (folderStore.currentFolderId === 'all' || folderStore.currentFolderId === '__none__') return null
  return folderStore.folders.find((f) => f.id === folderStore.currentFolderId) || null
})

const coachContextText = computed(() => {
  if (activeFolderDetail.value) {
    return `当前聚焦课程「${activeFolderDetail.value.name}」，涵盖 ${activeFolderDetail.value.knowledge_point_count} 个考点与 ${activeFolderDetail.value.ready_material_count} 份就绪资料。`
  }
  return '当前处于智练全景工作台，你可以随时询问学习方法、考点定义或复习建议。'
})

const switchFolder = async (folderId: string) => {
  folderStore.setCurrentFolderId(folderId)
  uni.showLoading({ title: '加载资料...' })
  await materialStore.loadMaterialList(folderId)
  uni.hideLoading()
}

const {
  showFolderModal,
  initialFolderName,
  folderToRename,
  isCreatingFolder,
  openCreateFolderModal,
  openRenameFolder,
  submitFolderModal,
  confirmArchiveFolder,
} = useFolderModal({
  activeFolderDetail,
  createFolder: folderStore.createFolder,
  renameFolder: folderStore.renameFolder,
  archiveFolder: folderStore.archiveFolder,
  onSwitched: switchFolder,
  onArchived: async () => { await materialStore.loadMaterialList('all') },
})

const goToDetail = (item: MaterialItem) => {
  uni.navigateTo({
    url: `/subpackages/material/pages/course/index?id=${item.id}`,
    fail: () => uni.showToast({ title: '打开讲义失败，请重试', icon: 'none' }),
  })
}

const { chooseFile } = useMaterialUpload({
  getCurrentFolderId: () => folderStore.currentFolderId,
  uploadMaterial: materialStore.upload,
  onUploaded: goToDetail,
})

onMounted(async () => {
  if (!authStore.isLoggedIn()) await authStore.loginWithWechat()
  await Promise.all([folderStore.loadFolders(), materialStore.loadMaterialList(folderStore.currentFolderId)])
})

onUnmounted(() => {
  parsePoller.dispose()
})

onPullDownRefresh(async () => {
  await Promise.all([folderStore.loadFolders(), materialStore.loadMaterialList(folderStore.currentFolderId)])
  uni.stopPullDownRefresh()
})

const refreshMaterials = () => materialStore.loadMaterialList(folderStore.currentFolderId)

const handleManualParse = async (item: MaterialItem) => {
  if (!canStartMaterialParse(item) && item.status !== 'failed') return
  uni.showLoading({ title: '启动流水线...' })
  try {
    await materialStore.triggerParse(item.id)
    uni.hideLoading()
    uni.showToast({ title: '流水线已启动', icon: 'success' })
    materialStore.pollMaterialStatus(item.id, 20, 1500, parsePoller).catch(() => {})
  } catch (err: any) {
    uni.hideLoading()
    uni.showToast({ title: err?.message || '触发失败', icon: 'none' })
  }
}

const goToQuestions = (item: MaterialItem) => {
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?material_id=${item.id}`,
    fail: () => uni.showToast({ title: '打开出题页失败，请重试', icon: 'none' }),
  })
}

const goToCourseGenerate = () => {
  if (!activeFolderDetail.value) return
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?folder_id=${activeFolderDetail.value.id}`,
    fail: () => uni.showToast({ title: '打开出题页失败，请重试', icon: 'none' }),
  })
}

const goToLogin = () => {
  uni.navigateTo({
    url: '/pages/auth/login',
    fail: () => uni.showToast({ title: '打开登录页失败', icon: 'none' }),
  })
}
</script>

<style lang="scss" scoped>
@import '../../styles/common.scss';

.index-container { padding: 32rpx; padding-bottom: 140rpx; min-height: 100vh; }
.hero-section { padding: 24rpx 8rpx 36rpx 8rpx; }
.hero-header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16rpx; }
.hero-tag { display: inline-block; font-size: 22rpx; color: var(--color-academic-blue); background-color: var(--color-blue-tint); padding: 6rpx 16rpx; border-radius: 6rpx; font-weight: 500; }
.login-trigger-btn { background: var(--color-academic-blue); padding: 8rpx 20rpx; border-radius: 24rpx; }
.login-trigger-text { font-size: 22rpx; color: var(--color-ink-on-primary); font-weight: 600; }
.user-status-pill { background: var(--color-teal-tint); padding: 6rpx 16rpx; border-radius: 20rpx; }
.user-status-text { font-size: 22rpx; color: var(--color-academic-teal); font-weight: 500; }
.hero-title { display: block; font-size: 44rpx; font-weight: 700; color: var(--color-ink-primary); letter-spacing: -0.5rpx; margin-bottom: 12rpx; }
.hero-subtitle { display: block; font-size: 24rpx; color: var(--color-ink-subtle); line-height: 1.5; }
.upload-card { padding: 32rpx 28rpx; display: flex; align-items: center; margin-bottom: 32rpx; }
.upload-icon-badge { width: 72rpx; height: 72rpx; border-radius: 16rpx; background: var(--color-blue-bg); border: 1px solid var(--color-blue-border); display: flex; align-items: center; justify-content: center; margin-right: 24rpx; flex-shrink: 0; }
.upload-icon-text { font-size: 24rpx; font-weight: 700; color: var(--color-academic-blue); }
.upload-info { flex: 1; }
.upload-title { display: block; font-size: 30rpx; font-weight: 600; color: var(--color-ink-primary); margin-bottom: 6rpx; }
.upload-desc { display: block; font-size: 22rpx; color: var(--color-ink-subtle); }
.upload-action { padding-left: 16rpx; }
.action-btn-text { font-size: 26rpx; color: var(--color-academic-blue); font-weight: 600; background: var(--color-blue-bg); padding: 10rpx 24rpx; border-radius: 8rpx; }
.course-quick-practice { padding: 28rpx 32rpx; background: linear-gradient(135deg, var(--color-blue-bg) 0%, var(--color-paper-card) 100%); border: 1px solid var(--color-blue-border); display: flex; align-items: center; justify-content: space-between; margin-bottom: 32rpx; }
.cqp-title { font-size: 28rpx; font-weight: 700; color: var(--color-academic-blue); display: block; margin-bottom: 6rpx; }
.cqp-desc { font-size: 22rpx; color: var(--color-blue-accent); display: block; }
.cqp-arrow { font-size: 32rpx; color: var(--color-academic-blue); font-weight: 700; }
.floating-coach-btn { position: fixed; right: 32rpx; bottom: 160rpx; background: var(--color-academic-blue); box-shadow: 0 6rpx 20rpx var(--color-blue-shadow); border-radius: 40rpx; padding: 14rpx 24rpx; display: flex; align-items: center; gap: 8rpx; z-index: 100; }
.coach-btn-tag { font-size: 20rpx; font-weight: 700; color: var(--color-academic-blue); background: var(--color-paper-card); padding: 2rpx 10rpx; border-radius: 16rpx; }
.coach-btn-text { color: var(--color-ink-on-primary); font-size: 24rpx; font-weight: 600; }
</style>
