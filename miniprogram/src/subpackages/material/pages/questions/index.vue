<template>
  <view class="questions-container">
    <view class="page-header">
      <text class="page-title">核对生成题目</text>
      <text class="page-subtitle">共生成 {{ questions.length }} 道测验题，请确认后开始作答</text>
    </view>

    <!-- 题目预览列表 -->
    <view class="questions-list">
      <view
        v-for="(q, idx) in questions"
        :key="q.id || idx"
        class="paper-card question-card"
      >
        <view class="q-header">
          <text class="q-num">第 {{ idx + 1 }} 题</text>
          <text class="q-type">{{ getTypeText(q.type) }}</text>
        </view>

        <text class="q-stem">{{ q.stem }}</text>

        <!-- 选项 -->
        <view v-if="q.options && q.options.length" class="q-options">
          <view
            v-for="(opt, optIdx) in q.options"
            :key="optIdx"
            class="option-item"
          >
            <text class="option-index">{{ String.fromCharCode(65 + optIdx) }}.</text>
            <text class="option-text">{{ opt }}</text>
          </view>
        </view>

        <!-- 来源依据锚点 -->
        <view v-if="q.source_quote" class="source-box">
          <text class="source-tag">📖 讲义依据：</text>
          <text class="source-text">{{ q.source_quote }}</text>
        </view>
      </view>
    </view>

    <!-- 底部固定行动栏 -->
    <view class="bottom-action-bar">
      <button class="paper-btn-primary start-btn" :loading="isStarting" @tap="handleStartPractice">
        开始作答 ({{ questions.length }} 题)
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useMaterialStore } from '@/stores/material'
import { usePracticeStore } from '@/stores/practice'
import type { QuestionItem } from '@/types'

const materialStore = useMaterialStore()
const practiceStore = usePracticeStore()
const materialId = ref<string>('')
const questions = ref<QuestionItem[]>([])
const isStarting = ref<boolean>(false)

onLoad(async (options) => {
  if (options && options.material_id) {
    materialId.value = options.material_id
    if (materialStore.questions.length) {
      questions.value = materialStore.questions
    } else {
      questions.value = await materialStore.loadQuestions(materialId.value)
    }
  }
})

const getTypeText = (type: string) => {
  switch (type) {
    case 'single_choice':
      return '单选题'
    case 'multiple_choice':
      return '多选题'
    case 'true_false':
      return '判断题'
    case 'short_answer':
      return '简答题'
    default:
      return '题目'
  }
}

const handleStartPractice = async () => {
  if (!materialId.value) return
  isStarting.value = true
  uni.showLoading({ title: '准备考场中...' })
  try {
    await practiceStore.initPractice(undefined, materialId.value)
    uni.hideLoading()
    uni.navigateTo({
      url: `/subpackages/practice/pages/session/index`,
    })
  } catch (err) {
    uni.hideLoading()
    console.error(err)
  } finally {
    isStarting.value = false
  }
}
</script>

<style scoped>
.questions-container {
  padding: 32rpx;
  padding-bottom: 160rpx;
  min-height: 100vh;
}

.page-header {
  margin-bottom: 32rpx;
}

.page-title {
  display: block;
  font-size: 38rpx;
  font-weight: 700;
  color: #1c1917;
  margin-bottom: 8rpx;
}

.page-subtitle {
  display: block;
  font-size: 26rpx;
  color: #78716c;
}

.question-card {
  padding: 32rpx;
  margin-bottom: 24rpx;
}

.q-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.q-num {
  font-size: 26rpx;
  font-weight: 600;
  color: #1e3a8a;
}

.q-type {
  font-size: 22rpx;
  background: #f5f5f4;
  color: #78716c;
  padding: 4rpx 12rpx;
  border-radius: 4rpx;
}

.q-stem {
  display: block;
  font-size: 30rpx;
  color: #1c1917;
  line-height: 1.6;
  font-weight: 500;
  margin-bottom: 20rpx;
}

.option-item {
  display: flex;
  padding: 12rpx 0;
  font-size: 28rpx;
  color: #44403c;
}

.option-index {
  font-weight: 600;
  margin-right: 12rpx;
  color: #78716c;
}

.option-text {
  flex: 1;
}

.source-box {
  margin-top: 20rpx;
  padding: 16rpx 20rpx;
  background: #fafaf9;
  border-left: 4rpx solid #1e3a8a;
  border-radius: 4rpx;
}

.source-tag {
  font-size: 22rpx;
  font-weight: 600;
  color: #1e3a8a;
  display: block;
  margin-bottom: 4rpx;
}

.source-text {
  font-size: 24rpx;
  color: #78716c;
  line-height: 1.5;
}

.bottom-action-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 24rpx 32rpx;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-top: 1px solid #e7e5e4;
  box-shadow: 0 -4rpx 16rpx rgba(0, 0, 0, 0.04);
}

.start-btn {
  height: 88rpx;
  font-size: 32rpx;
}
</style>
