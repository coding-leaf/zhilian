<template>
  <view class="course-container">
    <view v-if="material" class="paper-card detail-card">
      <view class="detail-header">
        <text class="title">{{ material.title }}</text>
        <view :class="['badge', `badge-${material.status.toLowerCase()}`]">
          {{ getStatusText(material.status) }}
        </view>
      </view>

      <view class="meta-section">
        <text class="meta-item">上传时间：{{ material.created_at }}</text>
        <text v-if="material.page_count" class="meta-item">解析页数：{{ material.page_count }} 页</text>
      </view>

      <view v-if="material.status === 'PROCESSING'" class="loading-box">
        <text class="loading-spinner">⌛</text>
        <text class="loading-tips">智能解析中，正在提取关键知识点...</text>
      </view>

      <view v-else-if="material.status === 'FAILED'" class="error-box">
        <text class="error-tips">解析失败：{{ material.error_message || '文档格式或内容异常' }}</text>
      </view>

      <view v-else-if="material.status === 'PARSED'" class="ready-box">
        <text class="ready-tips">✓ 讲义解析已就绪，可根据核心要点智能生成测验。</text>
      </view>
    </view>

    <!-- 出题操作按钮 -->
    <view v-if="material?.status === 'PARSED'" class="action-footer">
      <button class="paper-btn-primary generate-btn" :loading="isGenerating" @tap="handleGenerate">
        {{ isGenerating ? '正在出题...' : '智能生成测验题' }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad, onPullDownRefresh } from '@dcloudio/uni-app'
import { useMaterialStore } from '@/stores/material'
import type { MaterialItem } from '@/types'

const materialStore = useMaterialStore()
const materialId = ref<string>('')
const material = ref<MaterialItem | null>(null)
const isGenerating = ref<boolean>(false)

const loadDetail = async () => {
  if (!materialId.value) return
  try {
    material.value = await materialStore.pollMaterialStatus(materialId.value, 1)
  } catch (err) {
    console.error(err)
  }
}

onLoad(async (options) => {
  if (options && options.id) {
    materialId.value = options.id
    await loadDetail()
    // 若处于 PROCESSING 则持续轮询
    if (material.value?.status === 'PROCESSING' || material.value?.status === 'WAITING') {
      try {
        material.value = await materialStore.pollMaterialStatus(materialId.value)
      } catch {
        // 超时静默
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
      return '正在解析'
    case 'FAILED':
      return '失败'
    default:
      return '排队中'
  }
}

const handleGenerate = async () => {
  if (!materialId.value) return
  isGenerating.value = true
  uni.showLoading({ title: 'AI 思考出题中...' })
  try {
    await materialStore.generateQuestions(materialId.value, 5)
    uni.hideLoading()
    uni.navigateTo({
      url: `/subpackages/material/pages/questions/index?material_id=${materialId.value}`,
    })
  } catch {
    uni.hideLoading()
  } finally {
    isGenerating.value = false
  }
}
</script>

<style scoped>
.course-container {
  padding: 32rpx;
  min-height: 100vh;
}

.detail-card {
  padding: 36rpx 32rpx;
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

.meta-section {
  border-top: 1px solid #f5f5f4;
  padding-top: 20rpx;
  margin-bottom: 32rpx;
}

.meta-item {
  display: block;
  font-size: 26rpx;
  color: #78716c;
  margin-bottom: 8rpx;
}

.loading-box,
.ready-box,
.error-box {
  padding: 24rpx;
  border-radius: 12rpx;
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

.action-footer {
  margin-top: 48rpx;
}

.generate-btn {
  height: 88rpx;
  font-size: 30rpx;
}
</style>
