<template>
  <view class="review-container">
    <!-- 头部掌握度与学情统计 -->
    <view class="paper-card summary-card">
      <view class="summary-header">
        <text class="title">学情全景与错题巩固</text>
        <text class="subtitle">艾宾浩斯抗遗忘追踪 · 错题举一反三闭环</text>
      </view>

      <view class="stats-row">
        <view class="stat-col">
          <text class="stat-num">{{ wrongRecords.length }}</text>
          <text class="stat-lbl">待攻克错题</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-col">
          <text class="stat-num mastered-num">{{ masteredCount }}</text>
          <text class="stat-lbl">已消灭错题</text>
        </view>
      </view>
    </view>

    <!-- 一键针对性组卷行动卡 -->
    <view v-if="unmasteredKpIds.length > 0" class="paper-card action-card">
      <view class="action-info">
        <text class="action-title">🚀 错题薄弱点举一反三</text>
        <text class="action-desc">聚合了 {{ unmasteredKpIds.length }} 个薄弱知识点，点击一键由 AI 再生题目巩固测验</text>
      </view>
      <button
        class="paper-btn-primary quick-gen-btn"
        :loading="isGenerating"
        @tap="handleBatchRegenerate"
      >
        立即巩固
      </button>
    </view>

    <!-- 错题本列表 -->
    <view class="section-title-row">
      <text class="section-title">错题记录本</text>
      <text class="section-refresh" @tap="loadWrongs">刷新</text>
    </view>

    <view class="wrong-list">
      <view
        v-for="item in wrongRecords"
        :key="item.id"
        class="paper-card wrong-item-card"
      >
        <view class="item-header">
          <view class="kp-tag">
            <text class="kp-text">{{ item.knowledge_point_name || '核心考点' }}</text>
          </view>
          <view :class="['mastered-badge', item.is_mastered ? 'is-mastered' : 'unmastered']">
            {{ item.is_mastered ? '已攻克' : '待巩固' }}
          </view>
        </view>

        <text class="item-stem">{{ item.question?.stem || '错题题目快照' }}</text>

        <view class="item-footer">
          <text class="item-date">记录于：{{ item.created_at?.slice(0, 10) || '近期' }}</text>
          <button
            class="single-gen-btn"
            @tap="handleSingleKpPractice(item.knowledge_point_id)"
          >
            针对本考点出题 →
          </button>
        </view>
      </view>

      <view v-if="wrongRecords.length === 0" class="empty-state">
        <text class="empty-text">太棒了！当前没有错题记录，继续保持！</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { onPullDownRefresh } from '@dcloudio/uni-app'
import { apiListWrongRecords } from '@/api'
import { usePracticeStore } from '@/stores/practice'
import type { WrongRecordItem } from '@/types'

const practiceStore = usePracticeStore()
const wrongRecords = ref<WrongRecordItem[]>([])
const isGenerating = ref(false)

const masteredCount = computed(() => {
  return wrongRecords.value.filter((r) => r.is_mastered).length
})

const unmasteredKpIds = computed(() => {
  const ids = new Set<string>()
  for (const r of wrongRecords.value) {
    if (!r.is_mastered && r.knowledge_point_id) {
      ids.add(r.knowledge_point_id)
    }
  }
  return Array.from(ids)
})

const loadWrongs = async () => {
  try {
    const res = await apiListWrongRecords({ page_size: 50 })
    wrongRecords.value = res.items || []
  } catch (err) {
    console.error('Failed to load wrong records', err)
  }
}

onMounted(() => {
  loadWrongs()
})

onPullDownRefresh(async () => {
  await loadWrongs()
  uni.stopPullDownRefresh()
})

const handleBatchRegenerate = async () => {
  const kpIds = unmasteredKpIds.value
  if (kpIds.length === 0) return
  isGenerating.value = true
  uni.showLoading({ title: 'AI 举一反三组卷中...' })
  try {
    const session = await practiceStore.regenerateFromWrongPoints(kpIds)
    uni.hideLoading()
    uni.navigateTo({
      url: `/subpackages/practice/pages/session/index?practice_id=${session.id}`,
    })
  } catch (err: any) {
    uni.hideLoading()
    uni.showToast({ title: err?.message || '生成失败', icon: 'none' })
  } finally {
    isGenerating.value = false
  }
}

const handleSingleKpPractice = async (kpId?: string) => {
  if (!kpId) return
  uni.showLoading({ title: 'AI 出题中...' })
  try {
    const session = await practiceStore.regenerateFromWrongPoints([kpId])
    uni.hideLoading()
    uni.navigateTo({
      url: `/subpackages/practice/pages/session/index?practice_id=${session.id}`,
    })
  } catch (err: any) {
    uni.hideLoading()
    uni.showToast({ title: err?.message || '出题失败', icon: 'none' })
  }
}
</script>

<style scoped>
.review-container {
  padding: 32rpx;
  min-height: 100vh;
}

.summary-card {
  padding: 36rpx 32rpx;
  margin-bottom: 28rpx;
}

.title {
  display: block;
  font-size: 36rpx;
  font-weight: 700;
  color: #1c1917;
  margin-bottom: 8rpx;
}

.subtitle {
  font-size: 24rpx;
  color: #78716c;
  display: block;
  margin-bottom: 24rpx;
}

.stats-row {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding-top: 20rpx;
  border-top: 1px solid #f5f5f4;
}

.stat-col {
  text-align: center;
}

.stat-num {
  font-size: 44rpx;
  font-weight: 700;
  color: #b91c1c;
  display: block;
}

.mastered-num {
  color: #059669;
}

.stat-lbl {
  font-size: 24rpx;
  color: #78716c;
  margin-top: 4rpx;
}

.stat-divider {
  width: 1px;
  height: 48rpx;
  background: #e7e5e4;
}

.action-card {
  padding: 28rpx 32rpx;
  background: linear-gradient(135deg, #eff6ff 0%, #ffffff 100%);
  border: 1px solid #bfdbfe;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 32rpx;
}

.action-info {
  flex: 1;
  margin-right: 16rpx;
}

.action-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #1e3a8a;
  display: block;
  margin-bottom: 6rpx;
}

.action-desc {
  font-size: 22rpx;
  color: #3b82f6;
  line-height: 1.4;
  display: block;
}

.quick-gen-btn {
  height: 72rpx;
  font-size: 26rpx;
  padding: 0 24rpx;
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20rpx;
  padding: 0 4rpx;
}

.section-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #1c1917;
}

.section-refresh {
  font-size: 24rpx;
  color: #78716c;
}

.wrong-item-card {
  padding: 28rpx 30rpx;
  margin-bottom: 20rpx;
}

.item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12rpx;
}

.kp-tag {
  background: rgba(30, 58, 138, 0.08);
  padding: 4rpx 14rpx;
  border-radius: 6rpx;
}

.kp-text {
  font-size: 22rpx;
  color: #1e3a8a;
  font-weight: 600;
}

.mastered-badge {
  font-size: 20rpx;
  padding: 2rpx 10rpx;
  border-radius: 4rpx;
}

.is-mastered {
  background: #ecfdf5;
  color: #059669;
}

.unmastered {
  background: #fef2f2;
  color: #dc2626;
}

.item-stem {
  display: block;
  font-size: 28rpx;
  color: #1c1917;
  line-height: 1.5;
  margin-bottom: 16rpx;
}

.item-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px dashed #f5f5f4;
  padding-top: 14rpx;
}

.item-date {
  font-size: 22rpx;
  color: #a8a29e;
}

.single-gen-btn {
  font-size: 24rpx;
  color: #1e3a8a;
  background: transparent;
  padding: 0;
  margin: 0;
  line-height: 1;
}

.empty-state {
  text-align: center;
  padding: 80rpx 0;
}

.empty-text {
  font-size: 26rpx;
  color: #a8a29e;
}
</style>

