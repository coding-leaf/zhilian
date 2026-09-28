<template>
  <view class="report-container">
    <!-- 诊断总览卡片 -->
    <view v-if="report" class="paper-card score-card">
      <view class="score-header">
        <text class="score-title">学情诊断完成</text>
        <text class="score-date">{{ report.created_at?.slice(0, 10) }}</text>
      </view>

      <view class="score-stats-row">
        <view class="stat-item">
          <text class="stat-num">{{ report.score }}</text>
          <text class="stat-label">总得分 (满分 {{ report.total_score }})</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-item">
          <text class="stat-num">{{ (report.accuracy * 100).toFixed(0) }}%</text>
          <text class="stat-label">正确率</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-item">
          <text class="stat-num wrong-stat">{{ wrongCount }}</text>
          <text class="stat-label">错题数</text>
        </view>
      </view>

      <view v-if="report.next_step_suggestion" class="next-suggestion-box">
        <text class="suggestion-tag">💡 学习建议：</text>
        <text class="suggestion-text">{{ report.next_step_suggestion }}</text>
      </view>
    </view>

    <!-- 错题强化再生题行动卡片 -->
    <view v-if="wrongKnowledgePointIds.length > 0" class="paper-card adaptive-card">
      <view class="adaptive-info">
        <text class="adaptive-title">🎯 错题知识点自适应强化</text>
        <text class="adaptive-desc">
          本次练习涉及 {{ wrongKnowledgePointIds.length }} 个薄弱知识点，点击立即由 AI 举一反三生成针对性训练！
        </text>
      </view>
      <button
        class="paper-btn-primary adaptive-btn"
        :loading="isRegenerating"
        @tap="handleAdaptivePractice"
      >
        错题针对性生题
      </button>
    </view>

    <!-- 薄弱知识点清单 -->
    <view v-if="report?.weaknesses && report.weaknesses.length" class="weakness-section">
      <text class="section-title">需重点巩固的薄弱点</text>
      <view
        v-for="(w, idx) in report.weaknesses"
        :key="idx"
        class="paper-card weakness-card"
      >
        <view class="weakness-header">
          <text class="weakness-name">{{ w.knowledge_point }}</text>
          <text class="weakness-rate">掌握度 {{ (w.mastery_rate * 100).toFixed(0) }}%</text>
        </view>
        <text class="weakness-reason">{{ w.reason }}</text>
        <text class="weakness-sugg">建议：{{ w.suggestion }}</text>
      </view>
    </view>

    <!-- 逐题解析、AI 复查与助教追问 -->
    <view v-if="report?.details && report.details.length" class="details-section">
      <text class="section-title">作答明细与精准核对</text>

      <view
        v-for="(d, idx) in report.details"
        :key="idx"
        class="paper-card detail-card"
      >
        <view class="d-header">
          <text class="d-num">第 {{ idx + 1 }} 题 ({{ getTypeText(d.type) }})</text>
          <view :class="['result-tag', d.is_correct ? 'tag-correct' : 'tag-wrong']">
            {{ d.is_correct ? '正确' : '错误' }} ({{ d.score }}/{{ d.max_score }}分)
          </view>
        </view>

        <text class="d-stem">{{ d.stem }}</text>

        <view class="answer-compare-box">
          <text class="ans-line">你的作答：<text class="ans-val">{{ formatAnswer(d.user_answer) }}</text></text>
          <text class="ans-line">标准答案：<text class="ans-val ans-correct">{{ formatAnswer(d.correct_answer) }}</text></text>
        </view>

        <view v-if="d.feedback" class="feedback-box">
          <text class="fb-title">判题分析：</text>
          <text class="fb-text">{{ d.feedback }}</text>
        </view>

        <!-- 采分点展示 -->
        <view v-if="d.key_points_hit && d.key_points_hit.length" class="kp-hit-box">
          <text class="hit-title">✓ 命中的采分点：</text>
          <text v-for="(hit, hIdx) in d.key_points_hit" :key="hIdx" class="hit-item">• {{ hit }}</text>
        </view>

        <view v-if="d.key_points_missed && d.key_points_missed.length" class="kp-miss-box">
          <text class="miss-title">✕ 遗漏的要点：</text>
          <text v-for="(mis, mIdx) in d.key_points_missed" :key="mIdx" class="miss-item">• {{ mis }}</text>
        </view>

        <!-- 讲义原文对应 -->
        <view v-if="d.source_quote" class="source-quote-box">
          <text class="sq-title">📖 讲义原文对应：</text>
          <text class="sq-text">{{ d.source_quote }}</text>
        </view>

        <!-- 卡片底部操作：主观题申请 AI 复查 / 追问助教 -->
        <view class="card-actions-row">
          <button
            v-if="isSubjectiveType(d.type) && d.attempt_item_id"
            class="regrade-action-btn"
            @tap="openRegradeModal(d)"
          >
            ⚖️ 申请 AI 复查
          </button>
          <button class="coach-action-btn" @tap="openCoachForQuestion(d)">
            💡 问 AI 助教
          </button>
        </view>
      </view>
    </view>

    <!-- 底部返回按钮 -->
    <view class="bottom-bar">
      <button class="paper-btn-primary full-btn" @tap="handleBackHome">
        完成复盘，返回工作台
      </button>
    </view>

    <!-- 申请重判/复查弹窗 -->
    <view v-if="showRegradeModal" class="modal-overlay" @tap.self="closeRegradeModal">
      <view class="modal-content paper-card">
        <view class="modal-header">
          <text class="modal-title">申请主观题 AI 复查</text>
          <text class="modal-close" @tap="closeRegradeModal">✕</text>
        </view>
        <view class="modal-body">
          <text class="regrade-tips">如果系统评分遗漏了你的核心得分词或步骤，请补充说明复核理由：</text>
          <textarea
            v-model="regradeReason"
            class="regrade-textarea"
            placeholder="例如：我在第二句中提到了关键概念，但在判题时被归为遗漏..."
            :maxlength="300"
          />
        </view>
        <view class="modal-footer">
          <button class="modal-cancel-btn" @tap="closeRegradeModal">取消</button>
          <button
            class="paper-btn-primary modal-confirm-btn"
            :loading="isSubmittingRegrade"
            @tap="handleSubmitRegrade"
          >
            提交复核
          </button>
        </view>
      </view>
    </view>

    <!-- AI 助教抽屉 -->
    <AiCoachDrawer
      v-model:visible="showCoach"
      :title="coachTitle"
      :question-id="coachQuestionId"
      :context-text="coachContext"
      :user-answer="coachUserAnswer"
      :grading-points="coachGradingPoints"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad, onPullDownRefresh } from '@dcloudio/uni-app'
import { useDiagnosisStore } from '@/stores/diagnosis'
import { usePracticeStore } from '@/stores/practice'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import type { DiagnosisReport, QuestionGradingResult } from '@/types'

const diagnosisStore = useDiagnosisStore()
const practiceStore = usePracticeStore()

const practiceId = ref<string>('')
const report = ref<DiagnosisReport | null>(null)
const isRegenerating = ref<boolean>(false)

// 复查弹窗相关
const showRegradeModal = ref<boolean>(false)
const currentRegradeDetail = ref<QuestionGradingResult | null>(null)
const regradeReason = ref<string>('')
const isSubmittingRegrade = ref<boolean>(false)

// 助教相关
const showCoach = ref<boolean>(false)
const coachTitle = ref<string>('')
const coachQuestionId = ref<string>('')
const coachContext = ref<string>('')
const coachUserAnswer = ref<string>('')
const coachGradingPoints = ref<string[]>([])

const wrongCount = computed(() => {
  return report.value?.details.filter((d) => !d.is_correct).length || 0
})

const wrongKnowledgePointIds = computed(() => {
  if (!report.value?.details) return []
  const ids = new Set<string>()
  for (const d of report.value.details) {
    if (!d.is_correct && d.knowledge_point_id) {
      ids.add(d.knowledge_point_id)
    }
  }
  return Array.from(ids)
})

const loadDiagnosis = async () => {
  if (!practiceId.value) return
  uni.showLoading({ title: '加载学情中...' })
  try {
    report.value = await diagnosisStore.loadReport(practiceId.value)
    practiceStore.latestDiagnosis = report.value
  } catch (err) {
    console.error(err)
  } finally {
    uni.hideLoading()
  }
}

onLoad((options) => {
  if (options && options.practice_id) {
    practiceId.value = options.practice_id
    loadDiagnosis()
  }
})

onPullDownRefresh(async () => {
  await loadDiagnosis()
  uni.stopPullDownRefresh()
})

const isSubjectiveType = (type: string) => {
  return (
    type === 'short_answer' ||
    type === 'term_explanation' ||
    type === 'case_analysis' ||
    type === 'fill_in_blank'
  )
}

const getTypeText = (type: string) => {
  switch (type) {
    case 'single_choice': return '单选题'
    case 'multiple_choice': return '多选题'
    case 'true_false': return '判断题'
    case 'fill_in_blank': return '填空题'
    case 'term_explanation': return '名词解释'
    case 'short_answer': return '简答题'
    case 'case_analysis': return '案例分析'
    default: return '题目'
  }
}

const formatAnswer = (val: any) => {
  if (val === undefined || val === null || val === '') return '(未作答)'
  if (Array.isArray(val)) return val.join('、')
  return String(val)
}

// 错题自适应针对性再生题
const handleAdaptivePractice = async () => {
  const kpIds = wrongKnowledgePointIds.value
  if (kpIds.length === 0) {
    uni.showToast({ title: '当前无错题需要强化', icon: 'none' })
    return
  }
  isRegenerating.value = true
  uni.showLoading({ title: 'AI 举一反三生成中...' })
  try {
    const session = await practiceStore.regenerateFromWrongPoints(kpIds)
    uni.hideLoading()
    uni.redirectTo({
      url: `/subpackages/practice/pages/session/index?practice_id=${session.id}`,
    })
  } catch (err: any) {
    uni.hideLoading()
    uni.showToast({ title: err?.message || '生成失败', icon: 'none' })
  } finally {
    isRegenerating.value = false
  }
}

// 申请 AI 复查
const openRegradeModal = (d: QuestionGradingResult) => {
  currentRegradeDetail.value = d
  regradeReason.value = ''
  showRegradeModal.value = true
}

const closeRegradeModal = () => {
  showRegradeModal.value = false
}

const handleSubmitRegrade = async () => {
  if (!currentRegradeDetail.value?.attempt_item_id) return
  if (!regradeReason.value.trim()) {
    uni.showToast({ title: '请输入复核理由', icon: 'none' })
    return
  }
  isSubmittingRegrade.value = true
  try {
    const res = await practiceStore.requestRegrade(
      currentRegradeDetail.value.attempt_item_id,
      regradeReason.value.trim()
    )
    uni.showToast({ title: res.message || '复查已完成', icon: 'success' })
    closeRegradeModal()
    // 重新拉取报告
    await loadDiagnosis()
  } catch (err: any) {
    uni.showToast({ title: err?.message || '复查申请失败', icon: 'none' })
  } finally {
    isSubmittingRegrade.value = false
  }
}

// 题目级 AI 助教
const openCoachForQuestion = (d: QuestionGradingResult) => {
  coachTitle.value = `针对本题答疑`
  coachQuestionId.value = d.question_id
  coachContext.value = d.stem
  coachUserAnswer.value = formatAnswer(d.user_answer)
  coachGradingPoints.value = d.key_points_missed || []
  showCoach.value = true
}

const handleBackHome = () => {
  uni.switchTab({
    url: '/pages/index/index',
  })
}
</script>

<style scoped>
.report-container {
  padding: 32rpx;
  padding-bottom: 180rpx;
  min-height: 100vh;
}

.score-card {
  padding: 36rpx 32rpx;
  margin-bottom: 28rpx;
}

.score-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
}

.score-title {
  font-size: 34rpx;
  font-weight: 700;
  color: #1c1917;
}

.score-date {
  font-size: 24rpx;
  color: #a8a29e;
}

.score-stats-row {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 24rpx 0;
  border-top: 1px solid #f5f5f4;
  border-bottom: 1px solid #f5f5f4;
}

.stat-item {
  text-align: center;
}

.stat-num {
  font-size: 44rpx;
  font-weight: 700;
  color: #1e3a8a;
  display: block;
}

.wrong-stat {
  color: #b91c1c;
}

.stat-label {
  font-size: 24rpx;
  color: #78716c;
}

.stat-divider {
  width: 1px;
  height: 48rpx;
  background: #e7e5e4;
}

.next-suggestion-box {
  margin-top: 24rpx;
  padding: 16rpx 20rpx;
  background: #f0fdf4;
  border-radius: 8rpx;
}

.suggestion-tag {
  font-size: 24rpx;
  font-weight: 600;
  color: #166534;
  display: block;
  margin-bottom: 6rpx;
}

.suggestion-text {
  font-size: 26rpx;
  color: #15803d;
  line-height: 1.5;
}

/* 错题自适应卡片 */
.adaptive-card {
  padding: 28rpx 32rpx;
  background: linear-gradient(135deg, #fff7ed 0%, #ffffff 100%);
  border: 1px solid #fed7aa;
  margin-bottom: 28rpx;
}

.adaptive-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #c2410c;
  display: block;
  margin-bottom: 8rpx;
}

.adaptive-desc {
  font-size: 24rpx;
  color: #9a3412;
  line-height: 1.5;
  display: block;
  margin-bottom: 16rpx;
}

.adaptive-btn {
  height: 76rpx;
  font-size: 26rpx;
  background: #ea580c;
}

.section-title {
  display: block;
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1917;
  margin: 32rpx 0 20rpx 4rpx;
}

.weakness-card {
  padding: 24rpx 28rpx;
  margin-bottom: 16rpx;
}

.weakness-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12rpx;
}

.weakness-name {
  font-size: 28rpx;
  font-weight: 600;
  color: #b91c1c;
}

.weakness-rate {
  font-size: 24rpx;
  color: #78716c;
}

.weakness-reason,
.weakness-sugg {
  display: block;
  font-size: 24rpx;
  color: #57534e;
  line-height: 1.5;
}

.detail-card {
  padding: 30rpx;
  margin-bottom: 24rpx;
}

.d-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.d-num {
  font-size: 26rpx;
  font-weight: 600;
  color: #1e3a8a;
}

.result-tag {
  font-size: 22rpx;
  padding: 4rpx 14rpx;
  border-radius: 6rpx;
}

.tag-correct {
  background: #ecfdf5;
  color: #059669;
}

.tag-wrong {
  background: #fef2f2;
  color: #dc2626;
}

.d-stem {
  display: block;
  font-size: 28rpx;
  color: #1c1917;
  line-height: 1.6;
  margin-bottom: 20rpx;
}

.answer-compare-box {
  background: #fafaf9;
  padding: 16rpx 20rpx;
  border-radius: 8rpx;
  margin-bottom: 16rpx;
}

.ans-line {
  display: block;
  font-size: 24rpx;
  color: #78716c;
  margin-bottom: 6rpx;
}

.ans-val {
  color: #1c1917;
  font-weight: 500;
}

.ans-correct {
  color: #059669;
}

.feedback-box,
.source-quote-box,
.kp-hit-box,
.kp-miss-box {
  margin-top: 12rpx;
  font-size: 24rpx;
  line-height: 1.5;
}

.fb-title,
.sq-title,
.hit-title,
.miss-title {
  font-weight: 600;
  color: #44403c;
  display: block;
  margin-bottom: 4rpx;
}

.hit-title { color: #15803d; }
.miss-title { color: #b91c1c; }

.hit-item {
  color: #166534;
  display: block;
}

.miss-item {
  color: #991b1b;
  display: block;
}

.fb-text { color: #57534e; }
.sq-text { color: #78716c; }

.card-actions-row {
  display: flex;
  gap: 16rpx;
  margin-top: 20rpx;
  padding-top: 16rpx;
  border-top: 1px dashed #e7e5e4;
}

.regrade-action-btn,
.coach-action-btn {
  height: 64rpx;
  font-size: 24rpx;
  border-radius: 8rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.regrade-action-btn {
  flex: 1;
  background: #fef3c7;
  color: #92400e;
}

.coach-action-btn {
  flex: 1;
  background: #eff6ff;
  color: #1e3a8a;
}

.bottom-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 24rpx 32rpx;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-top: 1px solid #e7e5e4;
}

.full-btn {
  height: 88rpx;
  font-size: 30rpx;
}

/* 弹窗 */
.modal-overlay {
  position: fixed;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(2px);
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32rpx;
}

.modal-content {
  width: 100%;
  max-width: 600rpx;
  padding: 36rpx 32rpx;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20rpx;
}

.modal-title {
  font-size: 30rpx;
  font-weight: 700;
  color: #1c1917;
}

.modal-close {
  font-size: 32rpx;
  color: #a8a29e;
  padding: 8rpx;
}

.regrade-tips {
  display: block;
  font-size: 24rpx;
  color: #78716c;
  line-height: 1.5;
  margin-bottom: 16rpx;
}

.regrade-textarea {
  width: 100%;
  height: 180rpx;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
  border-radius: 8rpx;
  padding: 16rpx;
  font-size: 26rpx;
  box-sizing: border-box;
}

.modal-footer {
  display: flex;
  gap: 16rpx;
  margin-top: 24rpx;
}

.modal-cancel-btn {
  flex: 1;
  height: 76rpx;
  font-size: 26rpx;
  background: #f5f5f4;
  color: #57534e;
  border-radius: 8rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-confirm-btn {
  flex: 1;
  height: 76rpx;
  font-size: 26rpx;
}
</style>

