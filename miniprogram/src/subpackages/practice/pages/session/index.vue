<template>
  <view class="session-container">
    <view v-if="practiceStore.draftFailures.length > 0" class="draft-banner">
      <text class="draft-banner-text">
        有 {{ practiceStore.draftFailures.length }} 道题的作答未保存成功，请联网后重试。
      </text>
      <button class="draft-retry-btn" @tap="practiceStore.retryAllDrafts">重试</button>
    </view>

    <view class="progress-bar-row">
      <view class="progress-text-box">
        <text class="progress-num">{{ practiceStore.currentIndex + 1 }}</text>
        <text class="progress-total">/ {{ practiceStore.questions.length }}</text>
      </view>
      <view class="progress-track">
        <view
          class="progress-fill"
          :style="{ width: progressWidth }"
        />
      </view>
      <view class="card-drawer-trigger" @tap="showCardDrawer = !showCardDrawer">
        <text class="drawer-trigger-text">
          答题卡 ({{ practiceStore.answeredCount }}/{{ practiceStore.questions.length }})
        </text>
      </view>
    </view>

    <view v-if="currentQuestion" class="paper-card question-box">
      <view class="q-meta-row">
        <view class="q-type-badge">{{ typeLabel(currentQuestion.type) }}</view>
        <text v-if="currentQuestion.knowledge_point" class="kp-badge">
          考点：{{ currentQuestion.knowledge_point }}
        </text>
        <text class="progress-total">{{ saveStatusText }}</text>
      </view>

      <text class="q-stem">{{ currentQuestion.stem }}</text>

      <view
        v-if="currentQuestion.type === 'single_choice' || currentQuestion.type === 'true_false'"
        class="options-group"
      >
        <view
          v-for="(option, idx) in scopeOptions(currentQuestion)"
          :key="option.key || idx"
          :class="['option-btn', isSelected(currentQuestion.id, optionKey(option, idx)) ? 'selected' : '']"
          @tap="selectSingleOption(currentQuestion.id, optionKey(option, idx))"
        >
          <text class="opt-label">{{ optionKey(option, idx) }}</text>
          <text class="opt-content">{{ option.content }}</text>
        </view>
      </view>

      <view v-else-if="currentQuestion.type === 'multiple_choice'" class="options-group">
        <view
          v-for="(option, idx) in currentQuestion.options || []"
          :key="option.key || idx"
          :class="['option-btn', isMultipleSelected(currentQuestion.id, optionKey(option, idx)) ? 'selected' : '']"
          @tap="toggleMultipleOption(currentQuestion.id, optionKey(option, idx))"
        >
          <text class="opt-checkbox">
            {{ isMultipleSelected(currentQuestion.id, optionKey(option, idx)) ? '☑' : '☐' }}
          </text>
          <text class="opt-label">{{ optionKey(option, idx) }}</text>
          <text class="opt-content">{{ option.content }}</text>
        </view>
      </view>

      <view v-else-if="currentQuestion.type === 'fill_in_blank'" class="fill-blank-box">
        <text class="input-hint">请在下方输入作答内容：</text>
        <input
          class="fill-blank-input"
          placeholder="请输入你的填空答案..."
          :value="answerText(currentQuestion.id)"
          @input="handleTextInput"
        />
      </view>

      <view v-else class="essay-box">
        <text class="input-hint">请输入你的要点与分析：</text>
        <textarea
          class="essay-input"
          placeholder="结合考点，详细阐述你的解答步骤、核心定义或案例见解..."
          :value="answerText(currentQuestion.id)"
          :maxlength="1000"
          @input="handleTextInput"
        />
      </view>
    </view>

    <view v-if="showCardDrawer" class="card-drawer-overlay" @tap.self="showCardDrawer = false">
      <view class="card-drawer-sheet paper-card">
        <view class="drawer-title-row">
          <text class="drawer-title">答题卡索引</text>
          <text class="drawer-close" @tap="showCardDrawer = false">×</text>
        </view>
        <view class="grid-numbers">
          <view
            v-for="(question, idx) in practiceStore.questions"
            :key="question.id"
            :class="[
              'num-item',
              practiceStore.currentIndex === idx ? 'current' : '',
              isQuestionAnswered(question.id) ? 'answered' : '',
            ]"
            @tap="jumpToIndex(idx)"
          >
            {{ idx + 1 }}
          </view>
        </view>
      </view>
    </view>

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
        class="paper-btn-primary nav-btn"
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
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { usePracticeStore } from '@/stores/practice'
import { questionTypeLabel } from '@/api'
import type { QuestionItem, QuestionOption } from '@/types'

const practiceStore = usePracticeStore()
const showCardDrawer = ref(false)

const currentQuestion = computed(() => practiceStore.currentQuestion)
const progressWidth = computed(() => {
  const total = practiceStore.questions.length || 1
  return `${((practiceStore.currentIndex + 1) / total) * 100}%`
})
const saveStatusText = computed(() => {
  if (practiceStore.draftFailures.length > 0) return '存在未保存作答'
  return practiceStore.isSavingDrafts ? '保存中...' : '已保存'
})

onLoad(async (options) => {
  if (!options?.practice_id) {
    uni.showToast({ title: '缺少练习标识', icon: 'none' })
    return
  }
  try {
    await practiceStore.initPractice(options.practice_id)
  } catch (error: any) {
    uni.showToast({ title: error?.message || '加载练习失败', icon: 'none' })
  }
})

const typeLabel = (type: string) => questionTypeLabel(type)

const optionKey = (option: QuestionOption, idx: number) =>
  option.key || String.fromCharCode(65 + idx)

const scopeOptions = (question: QuestionItem): QuestionOption[] => {
  if (question.options?.length) return question.options
  return [
    { key: 'A', content: '正确' },
    { key: 'B', content: '错误' },
  ]
}

const answerText = (questionId: string) => {
  const value = practiceStore.userAnswers[questionId]
  return typeof value === 'string' ? value : ''
}

const isSelected = (questionId: string, value: string) =>
  practiceStore.userAnswers[questionId] === value

const isMultipleSelected = (questionId: string, value: string) => {
  const current = practiceStore.userAnswers[questionId]
  return Array.isArray(current) && current.includes(value)
}

const isQuestionAnswered = (questionId: string) => {
  const answer = practiceStore.userAnswers[questionId]
  if (answer === undefined || answer === null || answer === '') return false
  if (Array.isArray(answer) && answer.length === 0) return false
  return true
}

const selectSingleOption = (questionId: string, value: string) => {
  practiceStore.recordAnswer(questionId, value)
}

const toggleMultipleOption = (questionId: string, value: string) => {
  const current: string[] = Array.isArray(practiceStore.userAnswers[questionId])
    ? [...(practiceStore.userAnswers[questionId] as string[])]
    : []
  const idx = current.indexOf(value)
  if (idx !== -1) {
    current.splice(idx, 1)
  } else {
    current.push(value)
    current.sort()
  }
  practiceStore.recordAnswer(questionId, current)
}

const handleTextInput = (event: { detail: { value: string } }) => {
  if (!currentQuestion.value) return
  practiceStore.recordAnswer(currentQuestion.value.id, event.detail.value)
}

const jumpToIndex = (idx: number) => {
  practiceStore.jumpTo(idx)
  showCardDrawer.value = false
}

const confirmSubmit = () => {
  const unanswered = practiceStore.unansweredCount
  const content = unanswered > 0
    ? `尚有 ${unanswered} 道题未作答，确认交卷？待判题目稍后可在学情页查看结果。`
    : '已全部作答完成，确认交卷？'

  uni.showModal({
    title: '确认交卷',
    content,
    confirmText: '交卷',
    confirmColor: '#1E3A8A',
    success: async ({ confirm }: { confirm: boolean }) => {
      if (!confirm) return
      uni.showLoading({ title: '正在提交交卷...' })
      try {
        await practiceStore.submit()
        uni.hideLoading()
        const practiceId = practiceStore.currentSession?.id
        if (practiceId) {
          uni.redirectTo({
            url: `/subpackages/report/pages/detail/index?practice_id=${practiceId}`,
            fail: () => uni.showToast({ title: '打开结果页失败', icon: 'none' }),
          })
        }
      } catch (error: any) {
        uni.hideLoading()
        uni.showToast({ title: error?.message || '交卷失败，请重试', icon: 'none' })
      }
    },
  })
}
</script>

<style lang="scss" scoped>
@import '../../session.scss';
</style>
