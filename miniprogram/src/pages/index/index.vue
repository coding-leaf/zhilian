<template>
  <view class="index-container">
    <BackgroundTaskBar :auto-refresh="false" />

    <!-- 顶部温润书卷 Hero Header -->
    <view class="hero-section">
      <view class="hero-header-row">
        <view class="hero-tag">智练 · 即时备考工作台</view>
        <view v-if="!authStore.isLoggedIn()" class="login-trigger-btn" @tap="goToLogin">
          <text class="login-trigger-text">快捷登录</text>
        </view>
        <view v-else class="user-status-pill">
          <text class="user-status-text">{{ authStore.user?.nickname || '学术探索者' }}</text>
        </view>
      </view>
      <text class="hero-title">深阅读，专研习</text>
      <text class="hero-subtitle">讲义结构化考点 · 后台非阻塞组卷 · 实时学情沉淀</text>
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
          {{ currentFolderName ? `将导入至「${currentFolderName}」` : '支持微信聊天文档 (PDF/Word/TXT) 或拍照/相册' }}
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
      <text class="cqp-arrow">-></text>
    </view>

    <!-- 讲义列表 -->
    <view class="section-title-row">
      <text class="section-title">课程讲义库</text>
      <view class="title-right">
        <text class="section-refresh" @tap="refreshMaterials">
          {{ isLoadingList ? '加载中...' : '刷新' }}
        </text>
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

      <view v-if="!isLoadingList && materialStore.materialList.length === 0" class="empty-state">
        <text class="empty-text">当前分类下暂无讲义，点击上方卡片导入</text>
      </view>
    </view>

    <!-- 工作台全局悬浮助教入口 -->
    <view class="floating-coach-btn" @tap="openCoachDrawer">
      <text class="coach-btn-tag">AI</text>
      <text class="coach-btn-text">助教</text>
    </view>

    <AiCoachDrawer
      v-model:visible="showCoachDrawer"
      :title="coachTitle"
      :context-text="coachContextText"
      :folder-id="coachFocusedFolderId"
      :selectable-folders="coachSelectableFolders"
      :enable-scope-selector="true"
      @select-folder="selectCoachFolder"
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
import { computed, onMounted, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import { useMaterialStore } from '@/stores/material'
import { useAuthStore } from '@/stores/auth'
import { useFolderStore } from '@/stores/folder'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import BackgroundTaskBar from '@/components/BackgroundTaskBar.vue'
import { safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import { canStartMaterialParse } from '@/utils/materialState'
import { describeFailure, RequestError } from '@/utils/requestError'
import type { MaterialItem } from '@/types'
import FolderFilterBar from './components/FolderFilterBar.vue'
import FolderFormModal from './components/FolderFormModal.vue'
import MaterialItemCard from './components/MaterialItemCard.vue'
import { useMaterialDelete } from './composables/useMaterialDelete'
import { useFolderModal } from './composables/useFolderModal'
import { useHomeCoach } from './composables/useHomeCoach'
import { useMaterialUpload } from './composables/useMaterialUpload'

const materialStore = useMaterialStore()
const authStore = useAuthStore()
const folderStore = useFolderStore()
const taskStore = useBackgroundTaskStore()

const { deletingId, requestDelete } = useMaterialDelete({ deleteMaterial: materialStore.deleteMaterial })

const {
  showCoachDrawer, coachFocusedFolderId, coachSelectableFolders,
  coachTitle, coachContextText, openCoachDrawer, selectCoachFolder,
} = useHomeCoach(() => folderStore.folders)

const isLoadingList = ref(false)

const currentFolderName = computed(() => {
  if (folderStore.currentFolderId === 'all') return ''
  if (folderStore.currentFolderId === '__none__') return '未分类'
  return folderStore.folders.find((f) => f.id === folderStore.currentFolderId)?.name || ''
})

const activeFolderDetail = computed(() => {
  if (folderStore.currentFolderId === 'all' || folderStore.currentFolderId === '__none__') return null
  return folderStore.folders.find((f) => f.id === folderStore.currentFolderId) || null
})

const loadMaterialListNonBlocking = async (folderId: string) => {
  isLoadingList.value = true
  try {
    await materialStore.loadMaterialList(folderId)
  } finally {
    isLoadingList.value = false
  }
}

const switchFolder = async (folderId: string) => {
  folderStore.setCurrentFolderId(folderId)
  await loadMaterialListNonBlocking(folderId)
}

const {
  showFolderModal, initialFolderName, folderToRename, isCreatingFolder,
  openCreateFolderModal, openRenameFolder, submitFolderModal, confirmArchiveFolder,
} = useFolderModal({
  activeFolderDetail,
  createFolder: folderStore.createFolder,
  renameFolder: folderStore.renameFolder,
  archiveFolder: folderStore.archiveFolder,
  onSwitched: switchFolder,
  onArchived: async () => { await loadMaterialListNonBlocking('all') },
})

const goToDetail = (item: MaterialItem) => {
  uni.navigateTo({
    url: `/subpackages/material/pages/course/index?id=${item.id}`,
    fail: () => safeShowToast('打开讲义失败，请重试'),
  })
}

const { chooseFile } = useMaterialUpload({
  getCurrentFolderId: () => folderStore.currentFolderId,
  uploadMaterial: materialStore.upload,
  startParse: (id, title) => taskStore.startMaterialParse(id, title),
  refreshList: () => materialStore.loadMaterialList(folderStore.currentFolderId),
  onUploaded: goToDetail,
})

let hasCompletedInitialLoad = false
let inFlightRefresh: Promise<void> | null = null

const refreshAll = async () => {
  if (!authStore.isLoggedIn()) return
  if (inFlightRefresh) return inFlightRefresh
  inFlightRefresh = Promise.all([
    folderStore.loadFolders(),
    loadMaterialListNonBlocking(folderStore.currentFolderId),
    taskStore.refreshActiveTasks(),
  ])
    .then(() => undefined)
    .finally(() => {
      inFlightRefresh = null
    })
  return inFlightRefresh
}

onMounted(async () => {
  if (!authStore.isLoggedIn()) await authStore.loginWithWechat()
  await refreshAll()
  hasCompletedInitialLoad = true
})

onShow(() => {
  // 首次冷启已由 onMounted 统一拉取，避免与 onShow 重叠触发双倍并发请求
  if (!hasCompletedInitialLoad || inFlightRefresh || !authStore.isLoggedIn()) return
  void taskStore.refreshActiveTasks()
  void materialStore.loadMaterialList(folderStore.currentFolderId)
})

onPullDownRefresh(async () => {
  await refreshAll()
  uni.stopPullDownRefresh()
})

const refreshMaterials = () => {
  void refreshAll()
}

const handleManualParse = async (item: MaterialItem) => {
  if (!canStartMaterialParse(item) && item.status !== 'failed') return
  try {
    await withBlockingLoading('启动解析中...', async () => {
      await taskStore.startMaterialParse(item.id, item.title || '学习资料')
      await materialStore.loadMaterialList(folderStore.currentFolderId)
    })
    safeShowToast('已启动后台解析', 'success')
  } catch (err: any) {
    if (!(err instanceof RequestError)) {
      safeShowToast(describeFailure(err, '触发失败'))
    }
  }
}

const goToQuestions = (item: MaterialItem) => {
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?material_id=${item.id}`,
    fail: () => safeShowToast('打开出题页失败，请重试'),
  })
}

const goToCourseGenerate = () => {
  if (!activeFolderDetail.value) return
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?folder_id=${activeFolderDetail.value.id}`,
    fail: () => safeShowToast('打开出题页失败，请重试'),
  })
}

const goToLogin = () => {
  uni.navigateTo({
    url: '/pages/auth/login',
    fail: () => safeShowToast('打开登录页失败'),
  })
}
</script>

<style lang="scss" scoped>
@import './index.scss';
</style>
