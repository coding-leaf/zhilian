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
        <view class="progress-fill" :style="{ width: progressWidth }" />
      </view>
      <view class="card-drawer-trigger" @tap="showCardDrawer = !showCardDrawer">
        <text class="drawer-trigger-text">
          答题卡 ({{ practiceStore.answeredCount }}/{{ practiceStore.questions.length }})
        </text>
      </view>
    </view>

    <PracticeQuestionBody
      v-if="currentQuestion"
      :question="currentQuestion"
      :user-answer="currentUserAnswer"
      :save-status-text="saveStatusText"
      :overlay-open="showCardDrawer || showCoachDrawer"
      @select-single="selectSingleOption"
      @toggle-multiple="toggleMultipleOption"
      @input-answer="handleTextInput"
      @ask-coach="openQuestionCoach"
    />

    <AnswerCardDrawer
      v-model:visible="showCardDrawer"
      :questions="practiceStore.questions"
      :current-index="practiceStore.currentIndex"
      :user-answers="practiceStore.userAnswers"
      @jump="jumpToIndex"
    />

    <AiCoachDrawer
      v-model:visible="showCoachDrawer"
      :title="coachTitle"
      :question-id="currentQuestion?.id"
      :knowledge-point-id="currentQuestion?.knowledge_point_id"
      :material-id="currentQuestion?.material_id || practiceStore.currentSession?.material_id || undefined"
      :folder-id="practiceStore.currentSession?.folder_id || undefined"
      :context-text="coachContext"
      :user-answer="coachUserAnswer"
      :grading-points="currentQuestion?.grading_points"
    />

    <view class="bottom-bar">
      <button
        class="nav-btn prev-btn"
        :disabled="practiceStore.currentIndex === 0"
        @tap="handlePrevQuestion"
      >
        上一题
      </button>

      <button
        v-if="practiceStore.currentIndex < practiceStore.questions.length - 1"
        class="paper-btn-primary nav-btn"
        @tap="handleNextQuestion"
      >
        下一题
      </button>

      <button
        v-else
        class="paper-btn-primary submit-btn"
        :loading="practiceStore.isSubmitting"
        :disabled="practiceStore.isSubmitting"
        @tap="confirmSubmit"
      >
        交卷
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { onLoad, onUnload } from '@dcloudio/uni-app'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import { usePracticeStore } from '@/stores/practice'
import { safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import AnswerCardDrawer from '../../components/AnswerCardDrawer.vue'
import PracticeQuestionBody from '../../components/PracticeQuestionBody.vue'
import {
  collectLegacyTrueFalseUpgrades,
  toggleMultipleSelection,
} from '../../utils/practiceSession'

const TEXT_DRAFT_DEBOUNCE_MS = 500

interface PendingTextDraft {
  timer: ReturnType<typeof setTimeout>
  answer: string
  practiceId?: string
}

const practiceStore = usePracticeStore()
const showCardDrawer = ref(false)
const showCoachDrawer = ref(false)
const pendingDebounceCount = ref(0)
const pendingTextDrafts = new Map<string, PendingTextDraft>()

const syncPendingCount = () => {
  pendingDebounceCount.value = pendingTextDrafts.size
}

const flushPendingTextDrafts = (questionId?: string) => {
  const ids = questionId ? [questionId] : Array.from(pendingTextDrafts.keys())
  for (const id of ids) {
    const entry = pendingTextDrafts.get(id)
    if (!entry) continue
    clearTimeout(entry.timer)
    pendingTextDrafts.delete(id)
    practiceStore.persistDraftAnswer(id, entry.answer, entry.practiceId)
  }
  syncPendingCount()
}

const clearPendingTextDrafts = () => {
  for (const entry of pendingTextDrafts.values()) {
    clearTimeout(entry.timer)
  }
  pendingTextDrafts.clear()
  syncPendingCount()
}

const currentQuestion = computed(() => practiceStore.currentQuestion)
const currentUserAnswer = computed(() =>
  currentQuestion.value ? practiceStore.userAnswers[currentQuestion.value.id] : undefined,
)
const progressWidth = computed(() => {
  const total = practiceStore.questions.length || 1
  return `${((practiceStore.currentIndex + 1) / total) * 100}%`
})
const saveStatusText = computed(() => {
  if (practiceStore.draftFailures.length > 0) return '存在未保存作答'
  return practiceStore.isSavingDrafts || pendingDebounceCount.value > 0 ? '保存中...' : '已保存'
})

const coachTitle = computed(() => {
  const kpName = currentQuestion.value?.knowledge_point_name || currentQuestion.value?.knowledge_point
  return kpName ? `考点答疑 · ${kpName}` : '本题实时答疑'
})

const coachContext = computed(() => {
  const q = currentQuestion.value
  if (!q) return ''
  const kpName = q.knowledge_point_name || q.knowledge_point
  return kpName ? `考点：${kpName}。题干：${q.stem}` : q.stem
})

const coachUserAnswer = computed(() => {
  const val = currentUserAnswer.value
  if (val === undefined || val === null || val === '') return undefined
  if (Array.isArray(val)) return val.join('、')
  return String(val)
})

const RESUMABLE_STATUSES = new Set(['not_started', 'in_progress', 'paused'])

onLoad(async (options) => {
  clearPendingTextDrafts()
  if (!options?.practice_id) {
    safeShowToast('缺少练习标识')
    return
  }
  try {
    const session = await practiceStore.initPractice(options.practice_id)
    if (session && RESUMABLE_STATUSES.has(session.status)) {
      const upgrades = collectLegacyTrueFalseUpgrades(session.questions, practiceStore.userAnswers)
      for (const item of upgrades) {
        practiceStore.recordAnswer(item.questionId, item.answer)
      }
    }
  } catch (error: any) {
    safeShowToast(error?.message || '加载练习失败')
  }
})

onUnload(() => {
  flushPendingTextDrafts()
})

onBeforeUnmount(() => {
  flushPendingTextDrafts()
})

const selectSingleOption = (value: string) => {
  if (!currentQuestion.value) return
  practiceStore.recordAnswer(currentQuestion.value.id, value)
}

const toggleMultipleOption = (value: string) => {
  if (!currentQuestion.value) return
  const next = toggleMultipleSelection(
    practiceStore.userAnswers[currentQuestion.value.id],
    value,
  )
  practiceStore.recordAnswer(currentQuestion.value.id, next)
}

const handleTextInput = (value: string) => {
  if (!currentQuestion.value) return
  const questionId = currentQuestion.value.id
  const practiceId = practiceStore.currentSession?.id
  practiceStore.setLocalAnswer(questionId, value)
  const existing = pendingTextDrafts.get(questionId)
  if (existing) clearTimeout(existing.timer)
  const timer = setTimeout(() => {
    pendingTextDrafts.delete(questionId)
    syncPendingCount()
    practiceStore.persistDraftAnswer(questionId, value, practiceId)
  }, TEXT_DRAFT_DEBOUNCE_MS)
  pendingTextDrafts.set(questionId, { timer, answer: value, practiceId })
  syncPendingCount()
}

const openQuestionCoach = () => {
  if (!currentQuestion.value) return
  showCoachDrawer.value = true
}

const handlePrevQuestion = () => {
  flushPendingTextDrafts()
  practiceStore.prevQuestion()
}

const handleNextQuestion = () => {
  flushPendingTextDrafts()
  practiceStore.nextQuestion()
}

const jumpToIndex = (idx: number) => {
  flushPendingTextDrafts()
  practiceStore.jumpTo(idx)
  showCardDrawer.value = false
}

const confirmSubmit = () => {
  flushPendingTextDrafts()
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
      flushPendingTextDrafts()
      try {
        await withBlockingLoading('正在提交交卷...', () => practiceStore.submit())
        const practiceId = practiceStore.currentSession?.id
        if (practiceId) {
          uni.redirectTo({
            url: `/subpackages/report/pages/detail/index?practice_id=${practiceId}`,
            fail: () => safeShowToast('打开结果页失败'),
          })
        }
      } catch (error: any) {
        safeShowToast(error?.message || '交卷失败，请重试')
      }
    },
  })
}
</script>

<style lang="scss" scoped>
@import '../../session.scss';
</style>
