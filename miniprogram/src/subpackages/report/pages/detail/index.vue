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
      </view>

      <view v-if="report.next_step_suggestion" class="next-suggestion-box">
        <text class="suggestion-tag">💡 下一步建议：</text>
        <text class="suggestion-text">{{ report.next_step_suggestion }}</text>
      </view>
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

    <!-- 逐题解析与依据 -->
    <view v-if="report?.details && report.details.length" class="details-section">
      <text class="section-title">作答明细与原文核对</text>

      <view
        v-for="(d, idx) in report.details"
        :key="idx"
        class="paper-card detail-card"
      >
        <view class="d-header">
          <text class="d-num">第 {{ idx + 1 }} 题</text>
          <view :class="['result-tag', d.is_correct ? 'tag-correct' : 'tag-wrong']">
            {{ d.is_correct ? '正确' : '错误' }} ({{ d.score }}分)
          </view>
        </view>

        <text class="d-stem">{{ d.stem }}</text>

        <view class="answer-compare-box">
          <text class="ans-line">你的作答：<text class="ans-val">{{ d.user_answer || '(未作答)' }}</text></text>
          <text class="ans-line">标准答案：<text class="ans-val ans-correct">{{ d.correct_answer }}</text></text>
        </view>

        <view v-if="d.feedback" class="feedback-box">
          <text class="fb-title">判题分析：</text>
          <text class="fb-text">{{ d.feedback }}</text>
        </view>

        <view v-if="d.source_quote" class="source-quote-box">
          <text class="sq-title">📖 讲义原文对应：</text>
          <text class="sq-text">{{ d.source_quote }}</text>
        </view>
      </view>
    </view>

    <!-- 底部返回/再练按钮 -->
    <view class="bottom-bar">
      <button class="paper-btn-primary full-btn" @tap="handleBackHome">
        完成复盘，返回工作台
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad, onPullDownRefresh } from '@dcloudio/uni-app'
import { useDiagnosisStore } from '@/stores/diagnosis'
import type { DiagnosisReport } from '@/types'

const diagnosisStore = useDiagnosisStore()
const practiceId = ref<string>('')
const report = ref<DiagnosisReport | null>(null)

const loadDiagnosis = async () => {
  if (!practiceId.value) return
  uni.showLoading({ title: '加载学情中...' })
  try {
    report.value = await diagnosisStore.loadReport(practiceId.value)
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

const handleBackHome = () => {
  uni.switchTab({
    url: '/pages/index/index',
  })
}
</script>

<style scoped>
.report-container {
  padding: 32rpx;
  padding-bottom: 160rpx;
  min-height: 100vh;
}

.score-card {
  padding: 36rpx 32rpx;
  margin-bottom: 32rpx;
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
.source-quote-box {
  margin-top: 12rpx;
  font-size: 24rpx;
  line-height: 1.5;
}

.fb-title,
.sq-title {
  font-weight: 600;
  color: #44403c;
  display: block;
  margin-bottom: 4rpx;
}

.fb-text {
  color: #57534e;
}

.sq-text {
  color: #78716c;
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
</style>
