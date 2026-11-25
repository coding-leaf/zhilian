<template>
  <view class="report-container">
    <BackgroundTaskBar auto-refresh />

    <view v-if="detail.loadError.value" class="paper-card error-card">
      <text class="error-text">{{ detail.loadError.value }}</text>
      <button class="paper-btn-primary retry-btn" @tap="detail.bootstrap">重新加载</button>
    </view>

    <template v-else>
      <ReportSummaryCard
        :report="detail.report.value"
        :total-score="detail.totalScore.value"
        :max-score="detail.maxScore.value"
        :wrong-count="detail.wrongCount.value"
        :unanswered-count="detail.unansweredCount.value"
        :pending-count="detail.pendingCount.value"
        :is-fully-graded="detail.fullyGraded.value"
        :weak-points="detail.weakPoints.value"
      />

      <AdaptivePracticeCard
        :wrong-point-count="detail.wrongKnowledgePointIds.value.length"
        :can-regenerate="detail.canRegenerate.value"
        :regenerating="detail.isRegenerating.value"
        :needs-retry="detail.needsRetry.value"
        :fully-graded="detail.fullyGraded.value"
        :graded-count="detail.gradedCount.value"
        :total-count="detail.progress.value.total"
        :pending-regrade-count="detail.progress.value.pendingRegrade"
        :retrying-grading="detail.isRetryingGrading.value"
        :polling="detail.isPolling.value"
        @start="detail.startAdaptivePractice"
        @retry-grading="detail.retryGrading"
        @poll-grading="detail.pollGrading"
      />

      <view v-if="detail.results.value.length" class="details-section">
        <text class="section-title">作答明细与精准核对</text>
        <AttemptResultCard
          v-for="result in detail.results.value"
          :key="result.attemptItemId"
          :result="result"
          @regrade="detail.openGrading('regrade', $event)"
          @self-evaluate="detail.openGrading('self-evaluate', $event)"
          @coach="openCoach"
          @collect="openCollect"
        />
      </view>
    </template>

    <view class="bottom-bar">
      <button class="secondary-bar-btn" @tap="handleBackHome">返回工作台</button>
      <button
        v-if="detail.wrongKnowledgePointIds.value.length > 0 && detail.canRegenerate.value"
        class="reinforce-bar-btn"
        :loading="detail.isRegenerating.value"
        :disabled="detail.isRegenerating.value"
        @tap="detail.startAdaptivePractice"
      >
        {{ detail.isRegenerating.value ? '后台生题中...' : '错题靶向强化' }}
      </button>
      <button class="paper-btn-primary primary-bar-btn" @tap="handleGoReview">
        查看学情总览
      </button>
    </view>

    <GradingActionModal
      v-model:visible="detail.showModal.value"
      :mode="detail.modalMode.value"
      :result="detail.activeResult.value"
      :submitting="detail.isSubmittingGrading.value"
      @submit="detail.submitGrading"
    />

    <AiCoachDrawer
      v-model:visible="showCoach"
      :title="coachTitle"
      :question-id="coachQuestionId"
      :knowledge-point-id="coachKnowledgePointId"
      :context-text="coachContext"
      :user-answer="coachUserAnswer"
      :grading-points="coachGradingPoints"
    />

    <CollectionPickerDrawer
      v-model:visible="showCollectDrawer"
      :question-id="collectQuestionId"
    />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad, onPullDownRefresh, onUnload } from '@dcloudio/uni-app'
import type { AttemptResult } from '@/types'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import BackgroundTaskBar from '@/components/BackgroundTaskBar.vue'
import CollectionPickerDrawer from '@/components/CollectionPickerDrawer.vue'
import { safeShowToast } from '@/utils/loadingGuard'
import ReportSummaryCard from '../../components/ReportSummaryCard.vue'
import AttemptResultCard from '../../components/AttemptResultCard.vue'
import GradingActionModal from '../../components/GradingActionModal.vue'
import AdaptivePracticeCard from '../../components/AdaptivePracticeCard.vue'
import { useReportDetail } from '../../composables/useReportDetail'
import { formatAttemptAnswer } from '../../utils/reportView'

const detail = useReportDetail()

const showCoach = ref(false)
const coachTitle = ref('针对本题答疑')
const coachQuestionId = ref('')
const coachKnowledgePointId = ref<string | undefined>()
const coachContext = ref('')
const coachUserAnswer = ref('')
const coachGradingPoints = ref<string[]>([])
const showCollectDrawer = ref(false)
const collectQuestionId = ref('')

onLoad((options) => {
  const id = options?.practice_id
  if (!id) {
    detail.loadError.value = '缺少练习标识，无法加载结果'
    return
  }
  detail.practiceId.value = id
  detail.bootstrap().then(() => {
    if (!detail.fullyGraded.value) detail.pollGrading()
  })
})

onPullDownRefresh(async () => {
  await detail.bootstrap()
  uni.stopPullDownRefresh()
})

onUnload(() => {
  detail.dispose()
})

const openCoach = (result: AttemptResult) => {
  coachQuestionId.value = result.questionId
  coachKnowledgePointId.value = result.knowledgePointId
  coachTitle.value = result.knowledgePointName ? `考点答疑 · ${result.knowledgePointName}` : '针对本题答疑'
  coachContext.value = result.knowledgePointName
    ? `考点：${result.knowledgePointName}。题干：${result.stem}`
    : result.stem
  coachUserAnswer.value = formatAttemptAnswer(result.userAnswer, result.type)
  coachGradingPoints.value = result.missingKeywords.length
    ? result.missingKeywords
    : result.gradingPoints
  showCoach.value = true
}

const openCollect = (result: AttemptResult) => {
  if (!result.questionId) return
  collectQuestionId.value = result.questionId
  showCollectDrawer.value = true
}

const handleBackHome = () => {
  uni.switchTab({
    url: '/pages/index/index',
    fail: () => safeShowToast('返回工作台失败'),
  })
}

const handleGoReview = () => {
  uni.switchTab({
    url: '/pages/review/index',
    fail: () => safeShowToast('打开学情总览失败'),
  })
}
</script>

<style lang="scss" scoped>
@import '../../report.scss';

.error-card {
  padding: 40rpx 32rpx;
  text-align: center;
}

.error-text {
  display: block;
  font-size: 26rpx;
  color: var(--color-wrong);
  margin-bottom: 24rpx;
}

.retry-btn {
  height: 80rpx;
  font-size: 28rpx;
}
</style>
