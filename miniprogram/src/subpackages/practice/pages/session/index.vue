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
          :style="{
            width: `${((practiceStore.currentIndex + 1) / (practiceStore.questions.length || 1)) * 100}%`,
          }"
        />
      </view>
      <view class="card-drawer-trigger" @tap="showCardDrawer = !showCardDrawer">
        <text class="drawer-trigger-text">答题卡 ({{ practiceStore.answeredCount }}/{{ practiceStore.questions.length }})</text>
      </view>
    </view>

    <!-- 题目卡片 -->
    <view v-if="currentQuestion" class="paper-card question-box">
      <view class="q-meta-row">
        <view class="q-type-badge">
          {{ getTypeText(currentQuestion.type) }}
        </view>
        <text v-if="currentQuestion.knowledge_point" class="kp-badge">
          考点：{{ currentQuestion.knowledge_point }}
        </text>
      </view>

      <text class="q-stem">{{ currentQuestion.stem }}</text>

      <!-- 1. 单选与判断题 (Radio 交互) -->
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

      <!-- 2. 多选题 (Checkbox 交互) -->
      <view v-else-if="currentQuestion.type === 'multiple_choice'" class="options-group">
        <view
          v-for="(opt, idx) in (currentQuestion.options || [])"
          :key="idx"
          :class="['option-btn', isMultipleSelected(currentQuestion.id, getOptionVal(idx)) ? 'selected' : '']"
          @tap="toggleMultipleOption(currentQuestion.id, getOptionVal(idx))"
        >
          <text class="opt-checkbox">{{ isMultipleSelected(currentQuestion.id, getOptionVal(idx)) ? '☑' : '☐' }}</text>
          <text class="opt-label">{{ String.fromCharCode(65 + idx) }}</text>
          <text class="opt-content">{{ opt }}</text>
        </view>
      </view>

      <!-- 3. 填空题 (Input 单行输入) -->
      <view v-else-if="currentQuestion.type === 'fill_in_blank'" class="fill-blank-box">
        <text class="input-hint">请在下方输入作答内容：</text>
        <input
          class="fill-blank-input"
          placeholder="请输入你的填空答案..."
          :value="practiceStore.userAnswers[currentQuestion.id] || ''"
          @input="handleFillBlankInput"
        />
      </view>

      <!-- 4. 简答题 / 名词解释 / 案例分析 (Textarea 多行主观输入) -->
      <view v-else class="essay-box">
        <text class="input-hint">请输入你的要点与分析：</text>
        <textarea
          class="essay-input"
          placeholder="结合考点，详细阐述你的解答步骤、核心定义或案例见解..."
          :value="practiceStore.userAnswers[currentQuestion.id] || ''"
          :maxlength="1000"
          @input="handleEssayInput"
        />
      </view>
    </view>

    <!-- 答题卡浮层 -->
    <view v-if="showCardDrawer" class="card-drawer-overlay" @tap.self="showCardDrawer = false">
      <view class="card-drawer-sheet paper-card">
        <view class="drawer-title-row">
          <text class="drawer-title">答题卡索引</text>
          <text class="drawer-close" @tap="showCardDrawer = false">✕</text>
        </view>
        <view class="grid-numbers">
          <view
            v-for="(q, idx) in practiceStore.questions"
            :key="q.id"
            :class="[
              'num-item',
              practiceStore.currentIndex === idx ? 'current' : '',
              isQuestionAnswered(q.id) ? 'answered' : '',
            ]"
            @tap="jumpToIndex(idx)"
          >
            {{ idx + 1 }}
          </view>
        </view>
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
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { usePracticeStore } from '@/stores/practice'

const practiceStore = usePracticeStore()
const showCardDrawer = ref(false)

onLoad(async (options) => {
  if (options && options.practice_id) {
    await practiceStore.initPractice(options.practice_id)
  }
})

const currentQuestion = computed(() => practiceStore.currentQuestion)

const getTypeText = (type: string) => {
  switch (type) {
    case 'single_choice': return '单项选择'
    case 'multiple_choice': return '多项选择'
    case 'true_false': return '是非判断'
    case 'fill_in_blank': return '精准填空'
    case 'term_explanation': return '名词解释'
    case 'short_answer': return '简答论述'
    case 'case_analysis': return '案例分析'
    default: return '测验题'
  }
}

const getOptionVal = (idx: number) => {
  return String.fromCharCode(65 + idx)
}

const isSelected = (qId: string, val: string) => {
  return practiceStore.userAnswers[qId] === val
}

const isMultipleSelected = (qId: string, val: string) => {
  const current = practiceStore.userAnswers[qId]
  if (Array.isArray(current)) {
    return current.includes(val)
  }
  return false
}

const isQuestionAnswered = (qId: string) => {
  const ans = practiceStore.userAnswers[qId]
  if (ans === undefined || ans === null || ans === '') return false
  if (Array.isArray(ans) && ans.length === 0) return false
  return true
}

const selectSingleOption = (qId: string, val: string) => {
  practiceStore.recordAnswer(qId, val)
}

const toggleMultipleOption = (qId: string, val: string) => {
  const current: string[] = Array.isArray(practiceStore.userAnswers[qId])
    ? [...practiceStore.userAnswers[qId]]
    : []
  const idx = current.indexOf(val)
  if (idx !== -1) {
    current.splice(idx, 1)
  } else {
    current.push(val)
    current.sort()
  }
  practiceStore.recordAnswer(qId, current)
}

const handleFillBlankInput = (e: any) => {
  if (!currentQuestion.value) return
  practiceStore.recordAnswer(currentQuestion.value.id, e.detail.value)
}

const handleEssayInput = (e: any) => {
  if (!currentQuestion.value) return
  practiceStore.recordAnswer(currentQuestion.value.id, e.detail.value)
}

const jumpToIndex = (idx: number) => {
  practiceStore.jumpTo(idx)
  showCardDrawer.value = false
}

const confirmSubmit = () => {
  const unanswered = practiceStore.unansweredCount
  const content =
    unanswered > 0
      ? `尚有 ${unanswered} 道题未作答，确认交卷并生成精准学情诊断？`
      : '已全部作答完成，确认交卷并查看学情分析？'

  uni.showModal({
    title: '确认交卷',
    content,
    confirmText: '交卷',
    confirmColor: '#1E3A8A',
    success: async (res) => {
      if (res.confirm) {
        uni.showLoading({ title: '智能诊断出分中...' })
        try {
          const report = await practiceStore.submit()
          uni.hideLoading()
          const pId = practiceStore.currentSession?.id
          if (pId) {
            uni.redirectTo({
              url: `/subpackages/report/pages/detail/index?practice_id=${pId}`,
            })
          }
        } catch (err: any) {
          uni.hideLoading()
          uni.showToast({ title: err?.message || '交卷失败，请重试', icon: 'none' })
        }
      }
    },
  })
}
</script>

<style scoped>
.session-container {
  padding: 32rpx;
  padding-bottom: 180rpx;
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

.card-drawer-trigger {
  padding-left: 20rpx;
}

.drawer-trigger-text {
  font-size: 22rpx;
  color: #1e3a8a;
  background: #eff6ff;
  padding: 6rpx 14rpx;
  border-radius: 16rpx;
  font-weight: 600;
}

.question-box {
  padding: 36rpx 32rpx;
  margin-bottom: 32rpx;
}

.q-meta-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 20rpx;
}

.q-type-badge {
  display: inline-block;
  font-size: 22rpx;
  color: #1e3a8a;
  background: rgba(30, 58, 138, 0.08);
  padding: 4rpx 14rpx;
  border-radius: 6rpx;
  font-weight: 600;
}

.kp-badge {
  font-size: 20rpx;
  color: #0d9488;
  background: rgba(13, 148, 136, 0.1);
  padding: 4rpx 12rpx;
  border-radius: 6rpx;
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

.opt-checkbox {
  font-size: 32rpx;
  color: #1e3a8a;
  margin-right: 12rpx;
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

.input-hint {
  display: block;
  font-size: 24rpx;
  color: #78716c;
  margin-bottom: 12rpx;
}

.fill-blank-box {
  margin-top: 20rpx;
}

.fill-blank-input {
  width: 100%;
  height: 84rpx;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
  border-radius: 12rpx;
  padding: 0 24rpx;
  font-size: 28rpx;
}

.essay-box {
  margin-top: 20rpx;
}

.essay-input {
  width: 100%;
  height: 260rpx;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
  border-radius: 12rpx;
  padding: 20rpx;
  font-size: 28rpx;
  line-height: 1.5;
}

/* 答题卡抽屉 */
.card-drawer-overlay {
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

.card-drawer-sheet {
  background: #ffffff;
  border-top-left-radius: 28rpx;
  border-top-right-radius: 28rpx;
  padding: 32rpx;
  max-height: 60vh;
}

.drawer-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 28rpx;
}

.drawer-title {
  font-size: 30rpx;
  font-weight: 700;
  color: #1c1917;
}

.drawer-close {
  font-size: 32rpx;
  color: #a8a29e;
  padding: 8rpx;
}

.grid-numbers {
  display: flex;
  flex-wrap: wrap;
  gap: 20rpx;
}

.num-item {
  width: 80rpx;
  height: 80rpx;
  border-radius: 40rpx;
  background: #f5f5f4;
  color: #57534e;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
  font-weight: 600;
  border: 1px solid #e7e5e4;
}

.num-item.answered {
  background: #eff6ff;
  color: #1e3a8a;
  border-color: #93c5fd;
}

.num-item.current {
  border: 2px solid #1e3a8a;
  font-weight: 700;
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
  box-shadow: 0 -4rpx 16rpx rgba(0, 0, 0, 0.04);
}

.nav-btn {
  flex: 1;
  height: 88rpx;
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
  height: 88rpx;
  background: #059669;
}
</style>

