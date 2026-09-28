<template>
  <view class="report-container">
    <view v-if="loadError" class="paper-card error-card">
      <text class="error-text">{{ loadError }}</text>
      <button class="paper-btn-primary retry-btn" @tap="bootstrap">重新加载</button>
    </view>

    <template v-else>
      <ReportSummaryCard
        :report="report"
        :total-score="totalScore"
        :max-score="maxScore"
        :wrong-count="wrongCount"
        :unanswered-count="unansweredCount"
        :pending-count="pendingCount"
        :is-fully-graded="fullyGraded"
        :weak-points="weakPoints"
      />

      <view v-if="wrongKnowledgePointIds.length > 0 && canRegenerate" class="paper-card adaptive-card">
        <text class="adaptive-title">错题知识点自适应强化</text>
        <text class="adaptive-desc">
          本次练习涉及 {{ wrongKnowledgePointIds.length }} 个薄弱知识点，可针对当前课程范围再生题目继续巩固。
        </text>
        <button
          class="paper-btn-primary adaptive-btn"
          :loading="isRegenerating"
          @tap="handleAdaptivePractice"
        >
          错题针对性生题
        </button>
      </view>

      <view v-else-if="wrongKnowledgePointIds.length > 0" class="paper-card adaptive-card">
        <text class="adaptive-title">暂无可用再生范围</text>
        <text class="adaptive-desc">
          本次练习未归属课程或资料，暂时无法再生题，请先将资料归入课程后重试。
        </text>
      </view>

      <view v-if="needsRetry" class="paper-card refresh-card">
        <text class="adaptive-title">判题未完成（待重判）</text>
        <text class="adaptive-desc">
          已判 {{ gradedCount }}/{{ progress.total }} 题，仍有 {{ progress.pendingRegrade }} 题未判定，
          未判定题目不计零分也不计答错。可重试判题继续完成本轮判分。
        </text>
        <button
          class="paper-btn-primary retry-grading-btn"
          :loading="isRetryingGrading"
          @tap="handleRetryGrading"
        >
          重试判题
        </button>
      </view>

      <view v-else-if="!fullyGraded" class="paper-card refresh-card">
        <text class="adaptive-desc">判题进度：已判 {{ gradedCount }}/{{ progress.total }} 题。</text>
        <button class="refresh-btn" :loading="isPolling" @tap="pollGrading">刷新判题进度</button>
      </view>

      <view v-if="results.length" class="details-section">
        <text class="section-title">作答明细与精准核对</text>
        <AttemptResultCard
          v-for="result in results"
          :key="result.attemptItemId"
          :result="result"
          @regrade="openGrading('regrade', $event)"
          @self-evaluate="openGrading('self-evaluate', $event)"
          @coach="openCoach"
        />
      </view>
    </template>

    <view class="bottom-bar">
      <button class="paper-btn-primary full-btn" @tap="handleBackHome">返回工作台</button>
    </view>

    <GradingActionModal
      v-model:visible="showModal"
      :mode="modalMode"
      :result="activeResult"
      :submitting="isSubmittingGrading"
      @submit="handleGradingSubmit"
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
import { computed, ref } from 'vue'
import { onLoad, onPullDownRefresh, onUnload } from '@dcloudio/uni-app'
import { useDiagnosisStore } from '@/stores/diagnosis'
import { usePracticeStore } from '@/stores/practice'
import type { AttemptResult, DiagnosisReport } from '@/types'
import { summarizeProgress, needsGradingRetry } from '@/api/adapters/practice'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import ReportSummaryCard from '../../components/ReportSummaryCard.vue'
import AttemptResultCard from '../../components/AttemptResultCard.vue'
import GradingActionModal from '../../components/GradingActionModal.vue'
import {
  buildWeakPointViews,
  collectWrongKnowledgePointIds,
  formatAnswer,
  resolveSessionScope,
  type GradingMode,
} from '../../utils/reportView'

const diagnosisStore = useDiagnosisStore()
const practiceStore = usePracticeStore()

const practiceId = ref('')
const report = ref<DiagnosisReport | null>(null)
const loadError = ref('')
const isPolling = ref(false)
const isRegenerating = ref(false)
const isRetryingGrading = ref(false)
const pollTimer = ref<ReturnType<typeof setTimeout> | null>(null)

const showModal = ref(false)
const modalMode = ref<GradingMode>('regrade')
const activeResult = ref<AttemptResult | null>(null)
const isSubmittingGrading = ref(false)

const showCoach = ref(false)
const coachQuestionId = ref('')
const coachContext = ref('')
const coachUserAnswer = ref('')
const coachGradingPoints = ref<string[]>([])

const session = computed(() => practiceStore.currentSession)
const results = computed(() => practiceStore.attemptResults)
const progress = computed(() => summarizeProgress(session.value))
const fullyGraded = computed(() => progress.value.fullyGraded)
const gradedCount = computed(() => progress.value.graded)
// 待重判：判题已结束但仍有未判定题目（LLM 待重判或判题任务终态失败），提供恢复入口
const needsRetry = computed(() => needsGradingRetry(session.value) && !fullyGraded.value)
const totalScore = computed(() => session.value?.total_score ?? null)
const maxScore = computed(() => session.value?.max_score ?? null)
const pendingCount = computed(() => report.value?.pending_regrade_count ?? progress.value.pendingRegrade)
const unansweredCount = computed(() => report.value?.unanswered_count ?? progress.value.unanswered)
const wrongCount = computed(() => {
  if (report.value && fullyGraded.value) return report.value.wrong_count
  return results.value.filter((item) => item.isCorrect === false).length
})
const weakPoints = computed(() => buildWeakPointViews(report.value))
const wrongKnowledgePointIds = computed(() => collectWrongKnowledgePointIds(report.value, results.value))
const regenerateScope = computed(() => resolveSessionScope(session.value))
const canRegenerate = computed(
  () => Boolean(regenerateScope.value.folderId || regenerateScope.value.materialId),
)

const loadReportIfGraded = async () => {
  if (!fullyGraded.value) return
  report.value = await diagnosisStore.loadReport(practiceId.value, 1, 0)
}

const bootstrap = async () => {
  if (!practiceId.value) return
  loadError.value = ''
  uni.showLoading({ title: '加载作答结果...' })
  try {
    await practiceStore.refreshSession(practiceId.value)
    await loadReportIfGraded()
  } catch (error: any) {
    loadError.value = error?.message || '加载失败，请稍后重试'
  } finally {
    uni.hideLoading()
  }
}

const pollGrading = async () => {
  if (!practiceId.value || isPolling.value) return
  isPolling.value = true
  try {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await practiceStore.refreshSession(practiceId.value)
      // 已全判完或进入待重判态即停止轮询，避免无效等待后仍无提示
      if (fullyGraded.value || needsRetry.value) break
      await new Promise((resolve) => { pollTimer.value = setTimeout(resolve, 2500) })
    }
    await loadReportIfGraded()
  } finally {
    isPolling.value = false
  }
}

const handleRetryGrading = async () => {
  if (!practiceId.value || isRetryingGrading.value) return
  isRetryingGrading.value = true
  try {
    await practiceStore.retryGrading(practiceId.value)
    uni.showToast({ title: '已重新调度判题', icon: 'none' })
    await pollGrading()
    if (!fullyGraded.value && !needsRetry.value) {
      uni.showToast({ title: '判题仍在进行，可稍后从学情页查看', icon: 'none' })
    }
  } catch (error: any) {
    uni.showToast({ title: error?.message || '重试失败，请稍后再试', icon: 'none' })
  } finally {
    isRetryingGrading.value = false
  }
}

onLoad((options) => {
  const id = options?.practice_id
  if (!id) {
    loadError.value = '缺少练习标识，无法加载结果'
    return
  }
  practiceId.value = id
  bootstrap().then(() => {
    if (!fullyGraded.value) pollGrading()
  })
})

onPullDownRefresh(async () => {
  await bootstrap()
  uni.stopPullDownRefresh()
})

onUnload(() => {
  if (pollTimer.value) clearTimeout(pollTimer.value)
})

const openGrading = (mode: GradingMode, result: AttemptResult) => {
  modalMode.value = mode
  activeResult.value = result
  showModal.value = true
}

const handleGradingSubmit = async (payload: { reason: string; score: number }) => {
  const result = activeResult.value
  if (!result) return
  isSubmittingGrading.value = true
  try {
    if (modalMode.value === 'regrade') {
      const res = await practiceStore.requestRegrade(result.attemptItemId, payload.reason)
      uni.showToast({ title: res.message || '复查已完成', icon: 'success' })
    } else {
      await practiceStore.selfEvaluate(result.attemptItemId, payload.score, payload.reason)
      uni.showToast({ title: '自评已生效', icon: 'success' })
    }
    showModal.value = false
    await loadReportIfGraded()
  } catch (error: any) {
    uni.showToast({ title: error?.message || '提交失败，请重试', icon: 'none' })
  } finally {
    isSubmittingGrading.value = false
  }
}

const handleAdaptivePractice = async () => {
  const scope = regenerateScope.value
  if (!scope || !wrongKnowledgePointIds.value.length) {
    uni.showToast({ title: '暂无可用再生范围', icon: 'none' })
    return
  }
  isRegenerating.value = true
  uni.showLoading({ title: '生成中...' })
  try {
    const { session: nextSession, coverage } = await practiceStore.regenerateFromWrongPoints(
      wrongKnowledgePointIds.value,
      scope,
    )
    uni.hideLoading()
    if (coverage.missing.length > 0) {
      uni.showToast({ title: `仍有 ${coverage.missing.length} 个考点未覆盖`, icon: 'none' })
    }
    uni.redirectTo({
      url: `/subpackages/practice/pages/session/index?practice_id=${nextSession.id}`,
      fail: () => uni.showToast({ title: '打开练习失败，请重试', icon: 'none' }),
    })
  } catch (error: any) {
    uni.hideLoading()
    uni.showToast({ title: error?.message || '生成失败', icon: 'none' })
  } finally {
    isRegenerating.value = false
  }
}

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
  color: #b91c1c;
  margin-bottom: 24rpx;
}

.retry-btn {
  height: 80rpx;
  font-size: 28rpx;
}

.refresh-card {
  padding: 24rpx 32rpx;
}

.refresh-btn {
  height: 72rpx;
  font-size: 26rpx;
  background: #eff6ff;
  color: #1e3a8a;
  border-radius: 8rpx;
  margin-top: 16rpx;
}

.retry-grading-btn {
  height: 76rpx;
  font-size: 27rpx;
  margin-top: 16rpx;
}
</style>
