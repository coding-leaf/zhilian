<template>
  <view class="session-container">
    <!-- 顶部进度条与卡片导航 -->
    <view class="progress-bar-row">
      <view class="progress-text-box">
        <text class="progress-num">{{ practiceStore.currentIndex + 1 }}</text>
        <text class="progress-total">/ {{ practiceStore.questions.length }}</text>
      </view>
      <view class="progress-track">
        <view
          class="progress-fill"
          :style="{ width: `${((practiceStore.currentIndex + 1) / practiceStore.questions.length) * 100}%` }"
        />
      </view>
    </view>

    <!-- 题目卡片 -->
    <view v-if="currentQuestion" class="paper-card question-box">
      <view class="q-type-badge">
        {{ getTypeText(currentQuestion.type) }}
      </view>

      <text class="q-stem">{{ currentQuestion.stem }}</text>

      <!-- 单选题/判断题选项 -->
      <view
        v-if="currentQuestion.type === 'single_choice' || currentQuestion.type === 'true_false'"
        class="options-group"
      >
        <view
          v-for="(opt, idx) in (currentQuestion.options || ['正确', '错误'])"
          :key="idx"
          :class="['option-btn', isSelected(currentQuestion.id, getOptionVal(idx)) ? 'selected' : '']"
          @tap="selectSingleOption(currentQuestion.id, getOptionVal(idx))"
        >
          <text class="opt-label">{{ String.fromCharCode(65 + idx) }}</text>
          <text class="opt-content">{{ opt }}</text>
        </view>
      </view>

      <!-- 简答题/主观题文本输入 -->
      <view v-else-if="currentQuestion.type === 'short_answer'" class="essay-box">
        <textarea
          class="essay-input"
          placeholder="请输入你的作答要点..."
          :value="practiceStore.userAnswers[currentQuestion.id] || ''"
          @input="handleEssayInput"
        />
      </view>
    </view>

    <!-- 底部控制栏 -->
    <view class="bottom-bar">
      <button
        class="nav-btn prev-btn"
        :disabled="practiceStore.currentIndex === 0"
        @tap="practiceStore.prevQuestion"
      >
        上一题
      </button>

      <button
        v-if="practiceStore.currentIndex < practiceStore.questions.length - 1"
        class="paper-btn-primary nav-btn next-btn"
        @tap="practiceStore.nextQuestion"
      >
        下一题
      </button>

      <button
        v-else
        class="paper-btn-primary submit-btn"
        :loading="practiceStore.isSubmitting"
        @tap="confirmSubmit"
      >
        交卷
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { usePracticeStore } from '@/stores/practice'

const practiceStore = usePracticeStore()

onLoad(async (options) => {
  if (options && options.practice_id) {
    await practiceStore.initPractice(options.practice_id)
  }
})

const currentQuestion = computed(() => practiceStore.currentQuestion)

const getTypeText = (type: string) => {
  switch (type) {
    case 'single_choice':
      return '单选题'
    case 'multiple_choice':
      return '多选题'
    case 'true_false':
      return '判断题'
    case 'short_answer':
      return '简答主观题'
    default:
      return '测验题'
  }
}

const getOptionVal = (idx: number) => {
  return String.fromCharCode(65 + idx)
}

const isSelected = (qId: string, val: string) => {
  return practiceStore.userAnswers[qId] === val
}

const selectSingleOption = (qId: string, val: string) => {
  practiceStore.recordAnswer(qId, val)
}

const handleEssayInput = (e: any) => {
  if (!currentQuestion.value) return
  practiceStore.recordAnswer(currentQuestion.value.id, e.detail.value)
}

const confirmSubmit = () => {
  const unanswered = practiceStore.unansweredCount
  const content = unanswered > 0
    ? `尚有 ${unanswered} 道题未作答，确认交卷并生成学情诊断？`
    : '确认提交答卷并生成诊断报告？'

  uni.showModal({
    title: '确认交卷',
    content,
    confirmText: '交卷',
    confirmColor: '#1E3A8A',
    success: async (res) => {
      if (res.confirm) {
        uni.showLoading({ title: 'AI 诊断生成中...' })
        try {
          const report = await practiceStore.submit()
          uni.hideLoading()
          const pId = practiceStore.currentSession?.id
          if (pId) {
            // 跳转到学情报告页
            uni.redirectTo({
              url: `/subpackages/report/pages/detail/index?practice_id=${pId}`,
            })
          }
        } catch {
          uni.hideLoading()
        }
      }
    },
  })
}
</script>

<style scoped>
.session-container {
  padding: 32rpx;
  padding-bottom: 160rpx;
  min-height: 100vh;
}

.progress-bar-row {
  display: flex;
  align-items: center;
  margin-bottom: 32rpx;
}

.progress-text-box {
  margin-right: 20rpx;
}

.progress-num {
  font-size: 36rpx;
  font-weight: 700;
  color: #1e3a8a;
}

.progress-total {
  font-size: 24rpx;
  color: #a8a29e;
}

.progress-track {
  flex: 1;
  height: 12rpx;
  background: #e7e5e4;
  border-radius: 6rpx;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #1e3a8a;
  border-radius: 6rpx;
  transition: width 0.3s ease;
}

.question-box {
  padding: 36rpx 32rpx;
  margin-bottom: 32rpx;
}

.q-type-badge {
  display: inline-block;
  font-size: 22rpx;
  color: #1e3a8a;
  background: rgba(30, 58, 138, 0.08);
  padding: 4rpx 14rpx;
  border-radius: 6rpx;
  margin-bottom: 20rpx;
}

.q-stem {
  display: block;
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1917;
  line-height: 1.6;
  margin-bottom: 36rpx;
}

.options-group {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.option-btn {
  display: flex;
  align-items: center;
  padding: 24rpx 28rpx;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
  border-radius: 12rpx;
  transition: all 0.2s;
}

.option-btn.selected {
  background: #eff6ff;
  border-color: #1e3a8a;
}

.opt-label {
  font-size: 28rpx;
  font-weight: 700;
  color: #78716c;
  margin-right: 20rpx;
}

.option-btn.selected .opt-label {
  color: #1e3a8a;
}

.opt-content {
  font-size: 28rpx;
  color: #1c1917;
  flex: 1;
}

.essay-box {
  margin-top: 20rpx;
}

.essay-input {
  width: 100%;
  height: 240rpx;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
  border-radius: 12rpx;
  padding: 20rpx;
  font-size: 28rpx;
  box-sizing: border-box;
}

.bottom-bar {
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
}

.nav-btn {
  flex: 1;
  height: 84rpx;
  font-size: 28rpx;
}

.prev-btn {
  background: #f5f5f4;
  color: #44403c;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.submit-btn {
  flex: 1;
  height: 84rpx;
  background: #059669;
}
</style>
