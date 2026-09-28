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

    <!-- 课程文件夹选择与管理栏 -->
    <view class="folders-section">
      <view class="section-title-row">
        <text class="section-title">我的课程</text>
        <text class="action-text-btn" @tap="openCreateFolderModal">+ 新建课程</text>
      </view>

      <scroll-view scroll-x class="folders-scroll" :show-scrollbar="false">
        <view class="folders-tabs">
          <view
            :class="['folder-tab-pill', folderStore.currentFolderId === 'all' ? 'active' : '']"
            @tap="switchFolder('all')"
          >
            <text class="folder-tab-name">全部讲义</text>
          </view>
          <view
            v-for="folder in folderStore.folders"
            :key="folder.id"
            :class="['folder-tab-pill', folderStore.currentFolderId === folder.id ? 'active' : '']"
            @tap="switchFolder(folder.id)"
          >
            <text class="folder-tab-name">{{ folder.name }}</text>
            <text v-if="folder.ready_material_count" class="folder-count-badge">
              {{ folder.ready_material_count }}
            </text>
          </view>
          <view
            :class="['folder-tab-pill', folderStore.currentFolderId === '__none__' ? 'active' : '']"
            @tap="switchFolder('__none__')"
          >
            <text class="folder-tab-name">未分类</text>
          </view>
        </view>
      </scroll-view>
      <view v-if="activeFolderDetail" class="folder-actions">
        <text class="folder-action" @tap="openRenameFolder">重命名课程</text>
        <text class="folder-action folder-action-danger" @tap="confirmArchiveFolder">归档课程</text>
      </view>
    </view>

    <!-- 资料快速导入入口 Card -->
    <view class="paper-card upload-card" @tap="handleChooseFile">
      <view class="upload-icon-wrapper">
        <text class="upload-icon">📄</text>
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
        <text class="cqp-title">🎯 课程全景刷题</text>
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
      <view
        v-for="item in materialStore.materialList"
        :key="item.id"
        class="paper-card material-card"
        @tap="goToDetail(item)"
      >
        <view class="card-header">
          <text class="material-name">{{ item.title || '无标题资料' }}</text>
          <view :class="['status-badge', `status-${item.status}`]">
            {{ getStatusText(item) }}
          </view>
        </view>

        <view class="card-body">
          <text class="meta-date">上传：{{ item.created_at?.slice(0, 10) || '今日' }}</text>
          <text v-if="item.page_count" class="meta-page">{{ item.page_count }} 页</text>
          <text v-if="item.key_points_count" class="meta-points">{{ item.key_points_count }} 考点</text>
        </view>

        <view class="card-footer">
          <button
            v-if="canStartMaterialParse(item) || item.status === 'failed'"
            class="manual-parse-btn"
            @tap.stop="handleManualParse(item)"
          >
            {{ item.status === 'failed' ? '重试解析' : '开始解析' }}
          </button>

          <view v-else-if="isMaterialParsing(item)" class="processing-hint">
            <text class="spinner-icon">⌛</text>
            <text class="hint-text">正在抽取考点拓扑...</text>
          </view>

          <!-- 已解析状态：知识树学习与出题入口 -->
          <view v-else-if="item.status === 'ready'" class="ready-actions">
            <text class="action-link-study" @tap.stop="goToDetail(item)">知识图谱 →</text>
            <text class="action-link-practice" @tap.stop="goToQuestions(item)">智能出题 →</text>
          </view>
        </view>
      </view>

      <view v-if="materialStore.materialList.length === 0" class="empty-state">
        <text class="empty-text">当前分类下暂无讲义，点击上方卡片导入</text>
      </view>
    </view>

    <!-- 课程全局悬浮助教入口 -->
    <view class="floating-coach-btn" @tap="openGlobalCoach">
      <text class="coach-btn-icon">💡</text>
      <text class="coach-btn-text">AI助教</text>
    </view>

    <!-- AI 助教抽屉 -->
    <AiCoachDrawer
      v-model:visible="showCoachDrawer"
      title="课程随身助教"
      :context-text="coachContextText"
      :folder-id="activeFolderDetail?.id"
    />

    <!-- 新建课程弹窗 -->
    <view v-if="showFolderModal" class="modal-overlay">
      <!-- 关闭热区独立成元素：@tap.self 在小程序端被编译器丢弃，绑在容器上会导致点内容（含输入框）即关闭 -->
      <view class="modal-backdrop" @tap="closeFolderModal" />
      <view class="modal-content paper-card">
        <view class="modal-header">
          <text class="modal-title">{{ folderToRename ? '重命名课程' : '新建课程文件夹' }}</text>
          <text class="modal-close" @tap="closeFolderModal">✕</text>
        </view>
        <view class="modal-body">
          <input
            v-model="newFolderName"
            class="folder-input"
            :maxlength="30"
            :placeholder="folderToRename?.name || '例如：概率论与数理统计、操作系统'"
          />
        </view>
        <view class="modal-footer">
          <button class="modal-cancel-btn" @tap="closeFolderModal">取消</button>
          <button
            class="paper-btn-primary modal-confirm-btn"
            :loading="isCreatingFolder"
            @tap="handleCreateFolder"
          >
            {{ folderToRename ? '保存' : '创建' }}
          </button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { onPullDownRefresh } from '@dcloudio/uni-app'
import { useMaterialStore } from '@/stores/material'
import { useAuthStore } from '@/stores/auth'
import { useFolderStore } from '@/stores/folder'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import { canStartMaterialParse, isMaterialParsing, materialStatusText as getStatusText } from '@/utils/materialState'
import type { MaterialItem } from '@/types'

const materialStore = useMaterialStore()
const authStore = useAuthStore()
const folderStore = useFolderStore()

const showFolderModal = ref(false)
const newFolderName = ref('')
const folderToRename = ref<{ id: string; name: string } | null>(null)
const isCreatingFolder = ref(false)
const showCoachDrawer = ref(false)

const currentFolderName = computed(() => {
  if (folderStore.currentFolderId === 'all') return ''
  if (folderStore.currentFolderId === '__none__') return '未分类'
  const target = folderStore.folders.find((f) => f.id === folderStore.currentFolderId)
  return target?.name || ''
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

onMounted(async () => {
  if (!authStore.isLoggedIn()) {
    await authStore.loginWithWechat()
  }
  await Promise.all([
    folderStore.loadFolders(),
    materialStore.loadMaterialList(folderStore.currentFolderId),
  ])
})

onPullDownRefresh(async () => {
  await Promise.all([
    folderStore.loadFolders(),
    materialStore.loadMaterialList(folderStore.currentFolderId),
  ])
  uni.stopPullDownRefresh()
})

const switchFolder = async (folderId: string) => {
  folderStore.setCurrentFolderId(folderId)
  uni.showLoading({ title: '加载资料...' })
  await materialStore.loadMaterialList(folderId)
  uni.hideLoading()
}

const refreshMaterials = () => {
  materialStore.loadMaterialList(folderStore.currentFolderId)
}

const openCreateFolderModal = () => {
  folderToRename.value = null
  newFolderName.value = ''
  showFolderModal.value = true
}

const closeFolderModal = () => {
  showFolderModal.value = false
}

const handleCreateFolder = async () => {
  const name = newFolderName.value.trim()
  if (!name) {
    uni.showToast({ title: '请输入课程名称', icon: 'none' })
    return
  }
  isCreatingFolder.value = true
  try {
    const f = folderToRename.value
      ? await folderStore.renameFolder(folderToRename.value.id, name)
      : await folderStore.createFolder(name)
    uni.showToast({ title: folderToRename.value ? '课程已重命名' : '创建成功', icon: 'success' })
    closeFolderModal()
    await switchFolder(f.id)
  } catch (err: any) {
    uni.showToast({ title: err?.message || '创建失败', icon: 'none' })
  } finally {
    isCreatingFolder.value = false
  }
}

const openRenameFolder = () => {
  if (!activeFolderDetail.value) return
  folderToRename.value = { id: activeFolderDetail.value.id, name: activeFolderDetail.value.name }
  newFolderName.value = activeFolderDetail.value.name
  showFolderModal.value = true
}

const confirmArchiveFolder = () => {
  if (!activeFolderDetail.value) return
  const folder = activeFolderDetail.value
  uni.showModal({
    title: '归档课程',
    content: `归档「${folder.name}」？课程资料仍会保留。`,
    confirmColor: '#b91c1c',
    success: async ({ confirm }) => {
      if (!confirm) return
      await folderStore.archiveFolder(folder.id)
      await materialStore.loadMaterialList('all')
      uni.showToast({ title: '课程已归档', icon: 'success' })
    },
  })
}

const handleManualParse = async (item: MaterialItem) => {
  if (!canStartMaterialParse(item) && item.status !== 'failed') return
  uni.showLoading({ title: '启动流水线...' })
  try {
    await materialStore.triggerParse(item.id)
    uni.hideLoading()
    uni.showToast({ title: '流水线已启动', icon: 'success' })
    // 启动轮询
    materialStore.pollMaterialStatus(item.id).catch(() => {})
  } catch (err: any) {
    uni.hideLoading()
    uni.showToast({ title: err?.message || '触发失败', icon: 'none' })
  }
}

const handleChooseFile = () => {
  const targetFolderId = folderStore.currentFolderId === 'all' || folderStore.currentFolderId === '__none__'
    ? undefined
    : folderStore.currentFolderId

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
            const item = await materialStore.upload(file.path, file.name, targetFolderId)
            uni.hideLoading()
            uni.showToast({ title: '上传成功', icon: 'success' })
            goToDetail(item)
          } catch {
            uni.hideLoading()
          }
        }
      },
      fail: () => {},
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
          const item = await materialStore.upload(path, '学习讲义', targetFolderId)
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
    fail: () => uni.showToast({ title: '打开讲义失败，请重试', icon: 'none' }),
  })
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

const openGlobalCoach = () => {
  showCoachDrawer.value = true
}

const goToLogin = () => {
  uni.navigateTo({
    url: '/pages/auth/login',
    fail: () => uni.showToast({ title: '打开登录页失败', icon: 'none' }),
  })
}
</script>

<style scoped>
.index-container {
  padding: 32rpx;
  padding-bottom: 140rpx;
  min-height: 100vh;
}

.hero-section {
  padding: 24rpx 8rpx 36rpx 8rpx;
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
  font-size: 24rpx;
  color: #78716c;
  line-height: 1.5;
}

/* 课程文件夹栏 */
.folders-section {
  margin-bottom: 32rpx;
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20rpx;
  padding: 0 4rpx;
}

.section-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1917;
}

.action-text-btn {
  font-size: 26rpx;
  font-weight: 600;
  color: #1e3a8a;
}

.folders-scroll {
  white-space: nowrap;
  width: 100%;
}

.folders-tabs {
  display: inline-flex;
  gap: 16rpx;
  padding: 4rpx 0;
}

.folder-actions {
  display: flex;
  justify-content: flex-end;
  gap: 28rpx;
  padding: 14rpx 4rpx 0;
}

.folder-action {
  color: #245c51;
  font-size: 23rpx;
}

.folder-action-danger {
  color: #b91c1c;
}

.folder-tab-pill {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 12rpx 24rpx;
  background: #f5f5f4;
  border-radius: 24rpx;
  border: 1px solid transparent;
  transition: all 0.2s;
}

.folder-tab-pill.active {
  background: #1e3a8a;
  border-color: #1e3a8a;
}

.folder-tab-name {
  font-size: 26rpx;
  color: #44403c;
  font-weight: 500;
}

.folder-tab-pill.active .folder-tab-name {
  color: #ffffff;
  font-weight: 600;
}

.folder-count-badge {
  font-size: 20rpx;
  background: rgba(0, 0, 0, 0.08);
  padding: 2rpx 10rpx;
  border-radius: 12rpx;
  color: #78716c;
}

.folder-tab-pill.active .folder-count-badge {
  background: rgba(255, 255, 255, 0.2);
  color: #ffffff;
}

.upload-card {
  padding: 32rpx 28rpx;
  display: flex;
  align-items: center;
  margin-bottom: 32rpx;
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
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1917;
  margin-bottom: 6rpx;
}

.upload-desc {
  display: block;
  font-size: 22rpx;
  color: #78716c;
}

.upload-action {
  padding-left: 16rpx;
}

.action-btn-text {
  font-size: 26rpx;
  color: #1e3a8a;
  font-weight: 600;
  background: #eff6ff;
  padding: 10rpx 24rpx;
  border-radius: 8rpx;
}

/* 课程全局快捷刷题卡片 */
.course-quick-practice {
  padding: 28rpx 32rpx;
  background: linear-gradient(135deg, #eff6ff 0%, #ffffff 100%);
  border: 1px solid #bfdbfe;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 32rpx;
}

.cqp-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #1e3a8a;
  display: block;
  margin-bottom: 6rpx;
}

.cqp-desc {
  font-size: 22rpx;
  color: #3b82f6;
  display: block;
}

.cqp-arrow {
  font-size: 32rpx;
  color: #1e3a8a;
  font-weight: 700;
}

.section-refresh {
  font-size: 24rpx;
  color: #78716c;
}

.material-card {
  padding: 28rpx 30rpx;
  margin-bottom: 24rpx;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14rpx;
}

.material-name {
  font-size: 30rpx;
  font-weight: 600;
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

.status-ready {
  background: #ecfdf5;
  color: #059669;
}

.status-parsing {
  background: #fffbeb;
  color: #d97706;
}

.status-failed {
  background: #fef2f2;
  color: #dc2626;
}

.status-pending {
  background: #f5f5f4;
  color: #78716c;
}

.card-body {
  display: flex;
  gap: 20rpx;
  margin-bottom: 16rpx;
}

.meta-date,
.meta-page,
.meta-points {
  font-size: 22rpx;
  color: #a8a29e;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  border-top: 1px dashed #f5f5f4;
  padding-top: 16rpx;
}

.manual-parse-btn {
  font-size: 24rpx;
  color: #ffffff;
  background: #1e3a8a;
  padding: 6rpx 20rpx;
  border-radius: 8rpx;
}

.processing-hint {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.spinner-icon {
  font-size: 24rpx;
}

.hint-text {
  font-size: 24rpx;
  color: #d97706;
}

.ready-actions {
  display: flex;
  gap: 24rpx;
}

.action-link-study {
  font-size: 26rpx;
  color: #0d9488;
  font-weight: 500;
}

.action-link-practice {
  font-size: 26rpx;
  color: #1e3a8a;
  font-weight: 600;
}

.empty-state {
  text-align: center;
  padding: 64rpx 0;
}

.empty-text {
  font-size: 26rpx;
  color: #a8a29e;
}

/* 全局悬浮 AI 助教挂件 */
.floating-coach-btn {
  position: fixed;
  right: 32rpx;
  bottom: 160rpx;
  background: #1e3a8a;
  box-shadow: 0 6rpx 20rpx rgba(30, 58, 138, 0.35);
  border-radius: 40rpx;
  padding: 14rpx 24rpx;
  display: flex;
  align-items: center;
  gap: 8rpx;
  z-index: 100;
}

.coach-btn-icon {
  font-size: 28rpx;
}

.coach-btn-text {
  color: #ffffff;
  font-size: 24rpx;
  font-weight: 600;
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

.folder-input {
  width: 100%;
  height: 80rpx;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
  border-radius: 8rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
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

/* 关闭热区：由独立元素承载「点外部关闭」，容器不再绑 tap（见模板注释）。
   内容必须显式提升 z-index，否则会被绝对定位的 backdrop 盖住。 */
.modal-backdrop {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 0;
}

.modal-content {
  position: relative;
  z-index: 1;
}
</style>

