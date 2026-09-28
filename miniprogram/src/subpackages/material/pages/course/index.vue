<template>
  <view class="course-container">
    <!-- 资料头部卡片 -->
    <view v-if="material" class="paper-card detail-card">
      <view class="detail-header">
        <text class="title">{{ material.title }}</text>
        <view :class="['badge', `badge-${material.status.toLowerCase()}`]">
          {{ getStatusText(material.status) }}
        </view>
      </view>

      <view class="meta-section">
        <text class="meta-item">上传时间：{{ material.created_at?.slice(0, 19).replace('T', ' ') }}</text>
        <text v-if="material.page_count" class="meta-item">解析页数：{{ material.page_count }} 页</text>
        <text v-if="material.key_points_count" class="meta-item">抽取考点：{{ material.key_points_count }} 个</text>
      </view>

      <!-- 状态对应提示 -->
      <view v-if="material.status === 'WAITING'" class="status-box waiting-box">
        <text class="status-tips">讲义已上传，尚未开始解析。点击下方按钮手动启动解析流水线。</text>
        <button class="paper-btn-primary parse-btn" @tap="handleStartParse">开始解析</button>
      </view>

      <view v-else-if="material.status === 'PROCESSING'" class="status-box loading-box">
        <text class="loading-spinner">⌛</text>
        <text class="loading-tips">智能解析中，正在提取关键知识点与切片...</text>
      </view>

      <view v-else-if="material.status === 'FAILED'" class="status-box error-box">
        <text class="error-tips">解析失败：{{ material.error_message || '文档内容异常或排队超时' }}</text>
        <button class="retry-btn" @tap="handleStartParse">重试解析</button>
      </view>

      <view v-else-if="material.status === 'PARSED'" class="status-box ready-box">
        <text class="ready-tips">✓ 讲义解析已就绪，已构建完整考点树与证据溯源切片。</text>
      </view>
    </view>

    <!-- 知识树层级与知识点列表 (解析成功后展示) -->
    <view v-if="material?.status === 'PARSED'" class="knowledge-tree-section">
      <view class="section-title-row">
        <text class="section-title">知识点拓扑图谱</text>
        <text class="section-subtitle">点击知识点查看深入讲解与教材原文切片</text>
      </view>

      <view v-if="knowledgeNodes.length > 0" class="tree-container">
        <view
          v-for="node in knowledgeNodes"
          :key="node.id"
          class="paper-card tree-node-card"
          @tap="openPointDetail(node)"
        >
          <view class="node-header">
            <view class="node-title-group">
              <text :class="['level-tag', `level-${node.level}`]">L{{ node.level }}</text>
              <text class="node-name">{{ node.name }}</text>
            </view>
            <text class="node-arrow">→</text>
          </view>
          <text v-if="node.description" class="node-desc">{{ node.description }}</text>
          <view v-if="node.key_phrases && node.key_phrases.length" class="phrases-row">
            <text v-for="(kp, kidx) in node.key_phrases" :key="kidx" class="phrase-tag">
              #{{ kp }}
            </text>
          </view>
        </view>
      </view>

      <view v-else class="empty-tree">
        <text class="empty-tree-text">知识点正在建树中，请稍后下拉刷新...</text>
      </view>
    </view>

    <!-- 底部出题与复习操作栏 -->
    <view v-if="material?.status === 'PARSED'" class="bottom-action-bar">
      <button class="action-coach-btn" @tap="openMaterialCoach">
        💡 讲义助教
      </button>
      <button class="paper-btn-primary action-generate-btn" @tap="goToQuestionConfig">
        按知识点组卷出题
      </button>
    </view>

    <!-- 知识点详情与原文切片弹窗/抽屉 -->
    <view v-if="showPointModal" class="modal-overlay" @tap.self="closePointModal">
      <view class="point-sheet paper-card">
        <view class="sheet-header">
          <view class="sheet-title-box">
            <text class="sheet-tag">L{{ selectedPoint?.level || 1 }} 核心考点</text>
            <text class="sheet-title">{{ selectedPoint?.name }}</text>
          </view>
          <text class="sheet-close" @tap="closePointModal">✕</text>
        </view>

        <scroll-view scroll-y class="sheet-body">
          <!-- AI 概念深入剖析 -->
          <view class="point-section">
            <text class="sec-label">📘 知识点定义与深入解析</text>
            <text class="sec-content">
              {{ selectedPoint?.description || '暂无详细讲解，可点击下方按钮由 AI 助教启发式答疑。' }}
            </text>
          </view>

          <!-- 原文切片溯源 Snippets -->
          <view class="point-section">
            <text class="sec-label">📖 教材原文依据切片 ({{ pointSnippets.length }}处溯源)</text>
            <view v-if="isLoadingSnippets" class="loading-snippets">
              <text class="loading-text">正在检索教材溯源切片...</text>
            </view>
            <view v-else-if="pointSnippets.length > 0" class="snippets-list">
              <view
                v-for="(snip, sIdx) in pointSnippets"
                :key="snip.id || sIdx"
                class="snippet-item"
              >
                <view class="snip-meta">
                  <text class="snip-page">第 {{ snip.page_number || '1' }} 页</text>
                  <text v-if="snip.similarity" class="snip-sim">匹配度: {{ (snip.similarity * 100).toFixed(0) }}%</text>
                </view>
                <text class="snip-content">{{ snip.content }}</text>
              </view>
            </view>
            <view v-else class="empty-snippets">
              <text class="empty-snippets-text">当前考点由全局讲义语义归纳，无单一独立切片。</text>
            </view>
          </view>
        </scroll-view>

        <view class="sheet-footer">
          <button class="paper-btn-primary ask-coach-btn" @tap="askAboutPoint">
            问助教：针对本知识点提问
          </button>
        </view>
      </view>
    </view>

    <!-- AI 助教抽屉 -->
    <AiCoachDrawer
      v-model:visible="showCoach"
      :title="coachTitle"
      :context-text="coachContext"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad, onPullDownRefresh } from '@dcloudio/uni-app'
import { useMaterialStore } from '@/stores/material'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import type { MaterialItem, KnowledgeTreeNode, KnowledgeSnippet } from '@/types'

const materialStore = useMaterialStore()
const materialId = ref<string>('')
const material = ref<MaterialItem | null>(null)
const knowledgeNodes = ref<KnowledgeTreeNode[]>([])

const showPointModal = ref(false)
const selectedPoint = ref<KnowledgeTreeNode | null>(null)
const pointSnippets = ref<KnowledgeSnippet[]>([])
const isLoadingSnippets = ref(false)

const showCoach = ref(false)
const coachTitle = ref('讲义专属助教')
const coachContext = ref('')

const loadDetail = async () => {
  if (!materialId.value) return
  try {
    material.value = await materialStore.pollMaterialStatus(materialId.value, 1)
    if (material.value.status === 'PARSED') {
      const tree = await materialStore.loadKnowledgeTree(materialId.value)
      if (tree && tree.nodes) {
        knowledgeNodes.value = flattenTree(tree.nodes)
      }
    }
  } catch (err) {
    console.error(err)
  }
}

// 扁平化展示知识树列表（层级缩进或保留 level 标签）
const flattenTree = (nodes: KnowledgeTreeNode[]): KnowledgeTreeNode[] => {
  const result: KnowledgeTreeNode[] = []
  const traverse = (list: KnowledgeTreeNode[]) => {
    for (const n of list) {
      result.push(n)
      if (n.children && n.children.length > 0) {
        traverse(n.children)
      }
    }
  }
  traverse(nodes)
  return result
}

onLoad(async (options) => {
  if (options && options.id) {
    materialId.value = options.id
    await loadDetail()
    // 若处理中则轮询
    if (material.value?.status === 'PROCESSING' || material.value?.status === 'WAITING') {
      try {
        material.value = await materialStore.pollMaterialStatus(materialId.value)
        if (material.value.status === 'PARSED') {
          const tree = await materialStore.loadKnowledgeTree(materialId.value)
          if (tree && tree.nodes) {
            knowledgeNodes.value = flattenTree(tree.nodes)
          }
        }
      } catch {
        // 超时
      }
    }
  }
})

onPullDownRefresh(async () => {
  await loadDetail()
  uni.stopPullDownRefresh()
})

const getStatusText = (status: string) => {
  switch (status) {
    case 'PARSED':
      return '已完成'
    case 'PROCESSING':
      return '解析中'
    case 'FAILED':
      return '解析失败'
    default:
      return '待解析'
  }
}

const handleStartParse = async () => {
  if (!materialId.value) return
  uni.showLoading({ title: '启动流水线...' })
  try {
    await materialStore.triggerParse(materialId.value)
    uni.hideLoading()
    uni.showToast({ title: '开始解析', icon: 'success' })
    material.value = await materialStore.pollMaterialStatus(materialId.value)
    if (material.value.status === 'PARSED') {
      const tree = await materialStore.loadKnowledgeTree(materialId.value)
      if (tree && tree.nodes) {
        knowledgeNodes.value = flattenTree(tree.nodes)
      }
    }
  } catch (err: any) {
    uni.hideLoading()
    uni.showToast({ title: err?.message || '解析启动失败', icon: 'none' })
  }
}

const openPointDetail = async (node: KnowledgeTreeNode) => {
  selectedPoint.value = node
  showPointModal.value = true
  pointSnippets.value = []
  isLoadingSnippets.value = true

  const res = await materialStore.loadKnowledgePointWithSnippets(node.id)
  if (res && res.snippets) {
    pointSnippets.value = res.snippets.snippets || []
  }
  isLoadingSnippets.value = false
}

const closePointModal = () => {
  showPointModal.value = false
}

const askAboutPoint = () => {
  if (!selectedPoint.value) return
  coachTitle.value = `考点答疑: ${selectedPoint.value.name}`
  coachContext.value = `当前知识点：${selectedPoint.value.name}。概要：${selectedPoint.value.description || '无'}`
  closePointModal()
  showCoach.value = true
}

const openMaterialCoach = () => {
  coachTitle.value = `讲义助教: ${material.value?.title || '讲义答疑'}`
  coachContext.value = `当前讲义包含 ${knowledgeNodes.value.length} 个核心考点，涵盖知识树已建立。`
  showCoach.value = true
}

const goToQuestionConfig = () => {
  if (!materialId.value) return
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?material_id=${materialId.value}`,
  })
}
</script>

<style scoped>
.course-container {
  padding: 32rpx;
  padding-bottom: 180rpx;
  min-height: 100vh;
}

.detail-card {
  padding: 36rpx 32rpx;
  margin-bottom: 32rpx;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24rpx;
}

.title {
  font-size: 36rpx;
  font-weight: 700;
  color: #1c1917;
  flex: 1;
  margin-right: 16rpx;
  line-height: 1.4;
}

.badge {
  font-size: 24rpx;
  padding: 4rpx 14rpx;
  border-radius: 6rpx;
  white-space: nowrap;
}

.badge-parsed {
  background: #ecfdf5;
  color: #059669;
}

.badge-processing {
  background: #fffbeb;
  color: #d97706;
}

.badge-failed {
  background: #fef2f2;
  color: #dc2626;
}

.badge-waiting {
  background: #f5f5f4;
  color: #78716c;
}

.meta-section {
  border-top: 1px solid #f5f5f4;
  padding-top: 20rpx;
  margin-bottom: 24rpx;
}

.meta-item {
  display: block;
  font-size: 24rpx;
  color: #78716c;
  margin-bottom: 8rpx;
}

.status-box {
  padding: 24rpx;
  border-radius: 12rpx;
  font-size: 26rpx;
}

.waiting-box {
  background: #fafaf9;
  border: 1px dashed #d6d3d1;
}

.status-tips {
  display: block;
  font-size: 24rpx;
  color: #78716c;
  margin-bottom: 16rpx;
}

.parse-btn {
  height: 68rpx;
  font-size: 26rpx;
}

.loading-box {
  background: #fbfbf9;
  color: #d97706;
  display: flex;
  align-items: center;
}

.loading-spinner {
  margin-right: 12rpx;
}

.ready-box {
  background: #f0fdf4;
  color: #166534;
}

.error-box {
  background: #fef2f2;
  color: #991b1b;
}

.retry-btn {
  margin-top: 16rpx;
  height: 64rpx;
  background: #dc2626;
  color: #ffffff;
  font-size: 24rpx;
  border-radius: 8rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 知识树展示区 */
.knowledge-tree-section {
  margin-top: 16rpx;
}

.section-title-row {
  margin-bottom: 20rpx;
  padding: 0 4rpx;
}

.section-title {
  display: block;
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1917;
}

.section-subtitle {
  display: block;
  font-size: 22rpx;
  color: #78716c;
  margin-top: 4rpx;
}

.tree-node-card {
  padding: 24rpx 28rpx;
  margin-bottom: 16rpx;
  transition: all 0.2s;
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8rpx;
}

.node-title-group {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex: 1;
}

.level-tag {
  font-size: 20rpx;
  font-weight: 700;
  padding: 2rpx 8rpx;
  border-radius: 4rpx;
  background: #e0f2fe;
  color: #0284c7;
}

.level-1 { background: #fef3c7; color: #b45309; }
.level-2 { background: #e0f2fe; color: #0284c7; }
.level-3 { background: #f3e8ff; color: #7e22ce; }

.node-name {
  font-size: 28rpx;
  font-weight: 600;
  color: #1c1917;
}

.node-arrow {
  font-size: 26rpx;
  color: #a8a29e;
}

.node-desc {
  display: block;
  font-size: 24rpx;
  color: #57534e;
  line-height: 1.5;
  margin-top: 8rpx;
}

.phrases-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  margin-top: 12rpx;
}

.phrase-tag {
  font-size: 20rpx;
  color: #1e3a8a;
  background: #eff6ff;
  padding: 2rpx 10rpx;
  border-radius: 4rpx;
}

.empty-tree {
  padding: 60rpx 0;
  text-align: center;
}

.empty-tree-text {
  font-size: 26rpx;
  color: #a8a29e;
}

/* 底部操作条 */
.bottom-action-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  gap: 20rpx;
  padding: 24rpx 32rpx;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-top: 1px solid #e7e5e4;
  box-shadow: 0 -4rpx 16rpx rgba(0, 0, 0, 0.04);
}

.action-coach-btn {
  width: 220rpx;
  height: 88rpx;
  background: #eff6ff;
  color: #1e3a8a;
  font-size: 28rpx;
  font-weight: 600;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-generate-btn {
  flex: 1;
  height: 88rpx;
  font-size: 30rpx;
}

/* 考点与切片抽屉 */
.modal-overlay {
  position: fixed;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(2px);
  z-index: 999;
  display: flex;
  justify-content: flex-end;
  flex-direction: column;
}

.point-sheet {
  height: 80vh;
  background: #ffffff;
  border-top-left-radius: 28rpx;
  border-top-right-radius: 28rpx;
  display: flex;
  flex-direction: column;
}

.sheet-header {
  padding: 28rpx 32rpx;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 1px solid #f5f5f4;
}

.sheet-tag {
  font-size: 20rpx;
  color: #1e3a8a;
  background: #eff6ff;
  padding: 2rpx 10rpx;
  border-radius: 4rpx;
  font-weight: 600;
  display: inline-block;
  margin-bottom: 6rpx;
}

.sheet-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1917;
  display: block;
}

.sheet-close {
  font-size: 32rpx;
  color: #a8a29e;
  padding: 8rpx;
}

.sheet-body {
  flex: 1;
  padding: 28rpx 32rpx;
  overflow-y: auto;
}

.point-section {
  margin-bottom: 32rpx;
}

.sec-label {
  display: block;
  font-size: 26rpx;
  font-weight: 700;
  color: #1c1917;
  margin-bottom: 12rpx;
}

.sec-content {
  display: block;
  font-size: 26rpx;
  color: #44403c;
  line-height: 1.6;
  background: #fafaf9;
  padding: 20rpx;
  border-radius: 8rpx;
  border: 1px solid #f5f5f4;
}

.loading-snippets,
.empty-snippets {
  padding: 20rpx 0;
}

.loading-text,
.empty-snippets-text {
  font-size: 24rpx;
  color: #a8a29e;
}

.snippets-list {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.snippet-item {
  background: #f8fafc;
  border-left: 4rpx solid #1e3a8a;
  padding: 16rpx 20rpx;
  border-radius: 4rpx;
}

.snip-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6rpx;
}

.snip-page {
  font-size: 20rpx;
  color: #1e3a8a;
  font-weight: 600;
}

.snip-sim {
  font-size: 20rpx;
  color: #059669;
}

.snip-content {
  font-size: 24rpx;
  color: #334155;
  line-height: 1.5;
}

.sheet-footer {
  padding: 24rpx 32rpx;
  border-top: 1px solid #f5f5f4;
}

.ask-coach-btn {
  height: 80rpx;
  font-size: 28rpx;
}
</style>

