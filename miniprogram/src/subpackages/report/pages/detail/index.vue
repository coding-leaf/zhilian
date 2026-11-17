<template>
  <view class="report-container">
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
        />
      </view>
    </template>

    <view class="bottom-bar">
      <button class="paper-btn-primary full-btn" @tap="handleBackHome">返回工作台</button>
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
      title="针对本题答疑"
      :question-id="coachQuestionId"
      :context-text="coachContext"
      :user-answer="coachUserAnswer"
      :grading-points="coachGradingPoints"
    />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad, onPullDownRefresh, onUnload } from '@dcloudio/uni-app'
import type { AttemptResult } from '@/types'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import ReportSummaryCard from '../../components/ReportSummaryCard.vue'
import AttemptResultCard from '../../components/AttemptResultCard.vue'
import GradingActionModal from '../../components/GradingActionModal.vue'
import AdaptivePracticeCard from '../../components/AdaptivePracticeCard.vue'
import { useReportDetail } from '../../composables/useReportDetail'
import { formatAnswer } from '../../utils/reportView'

const detail = useReportDetail()

const showCoach = ref(false)
const coachQuestionId = ref('')
const coachContext = ref('')
const coachUserAnswer = ref('')
const coachGradingPoints = ref<string[]>([])

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
  coachContext.value = result.stem
  coachUserAnswer.value = formatAnswer(result.userAnswer)
  coachGradingPoints.value = result.missingKeywords
  showCoach.value = true
}

const handleBackHome = () => {
  uni.switchTab({
    url: '/pages/index/index',
    fail: () => uni.showToast({ title: '返回工作台失败', icon: 'none' }),
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
