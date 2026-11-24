<template>
  <view class="review-container">
    <BackgroundTaskBar auto-refresh />

    <view v-if="review.topErrorBanner.value" class="paper-card top-error-banner">
      <text class="top-error-text">{{ review.topErrorBanner.value }}</text>
      <button class="inline-retry-btn" @tap="handleRefreshAll">重试</button>
    </view>

    <scroll-view scroll-x class="folder-filter-scroll" :show-scrollbar="false">
      <view class="folder-filter-tabs">
        <view
          :class="['folder-pill', review.selectedFolderId.value === 'all' ? 'active' : '']"
          @tap="review.selectFolderFilter('all')"
        >
          <text class="folder-pill-text">全部课程</text>
        </view>
        <view
          v-for="folder in folderStore.folders"
          :key="folder.id"
          :class="['folder-pill', review.selectedFolderId.value === folder.id ? 'active' : '']"
          @tap="review.selectFolderFilter(folder.id)"
        >
          <text class="folder-pill-text">{{ folder.name }}</text>
        </view>
        <view
          :class="['folder-pill', review.selectedFolderId.value === '__none__' ? 'active' : '']"
          @tap="review.selectFolderFilter('__none__')"
        >
          <text class="folder-pill-text">未分类</text>
        </view>
      </view>
    </scroll-view>

    <MasteryOverviewCard
      :overview="review.masteryOverview.value"
      :loading="review.masteryLoading.value"
      :error="review.masteryError.value"
      @retry="review.loadMastery"
      @reinforce-weak="review.handleReinforceWeak"
    />

    <view :class="['segment-bar', { 'sticky-surface': taskStore.visibleTasks.length === 0 }]">
      <view
        v-for="tab in segmentTabs"
        :key="tab.key"
        :class="['segment-item', review.activeTab.value === tab.key ? 'active' : '']"
        @tap="handleSwitchTab(tab.key)"
      >
        <text class="segment-label">{{ tab.label }}</text>
        <text v-if="tab.count > 0" class="segment-count">{{ tab.count }}</text>
      </view>
    </view>

    <MasteryPointList
      v-if="review.activeTab.value === 'mastery'"
      :points="review.sortedMasteryPoints.value"
      :overview="review.masteryOverview.value"
      :loading="review.masteryLoading.value"
      :error="review.masteryError.value"
      @retry="review.loadMastery"
      @breakthrough="review.handleBreakthroughPoint"
    />

    <WrongBookSection
      v-if="review.activeTab.value === 'wrong'"
      :records="review.visibleRecords.value"
      :group-options="review.groupOptions.value"
      :selected-group-key="review.selectedGroupKey.value"
      :active-group="review.activeGroup.value"
      :active-kp-ids="review.activeKpIds.value"
      :active-scope-ready="review.activeScopeReady.value"
      :needs-group-choice="review.needsGroupChoice.value"
      :selected-ids="review.selectedWrongIds.value"
      :marking-ids="review.markingWrongIds.value"
      :loading="review.isLoadingWrongs.value"
      :error="review.wrongError.value"
      :is-generating="review.isGenerating.value"
      @retry="review.loadWrongs"
      @select-group="review.selectedGroupKey.value = $event"
      @toggle-select="review.toggleWrongSelect"
      @toggle-select-all="review.toggleSelectAllUnmastered"
      @mark-mastered="review.handleMarkWrongMastered"
      @restart-selected="review.handleRestartSelectedWrongs"
      @batch-regenerate="review.handleBatchRegenerate"
      @practice="review.handleSingleKpPractice"
    />

    <view v-if="review.activeTab.value === 'practices'" class="practice-list-section">
      <view v-if="review.practiceError.value" class="paper-card inline-error-box">
        <text class="inline-error-text">{{ review.practiceError.value }}</text>
        <button class="inline-retry-btn" @tap="review.loadPractices">重试</button>
      </view>
      <view
        v-else-if="review.isLoadingPractices.value && review.practices.value.length === 0"
        class="empty-state"
      >
        <text class="empty-text">正在加载练习记录...</text>
      </view>
      <view v-else-if="review.practices.value.length === 0" class="empty-state">
        <text class="empty-text">暂无练习记录，从资料详情或我的题库发起练习吧。</text>
      </view>
      <template v-else>
        <PracticeEntryCard
          v-for="practice in review.practices.value"
          :key="practice.id"
          :practice="practice"
          @open="review.openPractice"
        />
      </template>
    </view>

    <view v-if="hasVisitedBank" v-show="review.activeTab.value === 'bank'">
      <QuestionBankSection
        ref="bankSection"
        :wrong-records="review.wrongRecords.value"
        @wrong-changed="handleWrongChanged"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { onPullDownRefresh, onShow } from '@dcloudio/uni-app'
import BackgroundTaskBar from '@/components/BackgroundTaskBar.vue'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useFolderStore } from '@/stores/folder'
import MasteryOverviewCard from './components/MasteryOverviewCard.vue'
import MasteryPointList from './components/MasteryPointList.vue'
import PracticeEntryCard from './components/PracticeEntryCard.vue'
import QuestionBankSection from './components/QuestionBankSection.vue'
import WrongBookSection from './components/WrongBookSection.vue'
import { useReviewCenter } from './composables/useReviewCenter'
import type { ReviewSegment } from './reviewView'

const folderStore = useFolderStore()
const taskStore = useBackgroundTaskStore()
const review = useReviewCenter()
const bankSection = ref<InstanceType<typeof QuestionBankSection> | null>(null)
const hasVisitedBank = ref(false)
let hasCompletedInitialLoad = false

const segmentTabs = computed<Array<{ key: ReviewSegment; label: string; count: number }>>(() => [
  { key: 'mastery', label: '考点掌握', count: review.masteryOverview.value?.total_knowledge_points ?? 0 },
  { key: 'wrong', label: '错题本', count: review.pendingCount.value },
  { key: 'practices', label: '练习记录', count: review.practices.value.length },
  { key: 'bank', label: '我的题库', count: 0 },
])

const refreshBank = async () => {
  await bankSection.value?.refresh()
}

const handleRefreshAll = () => review.refreshAll({ refreshBank })
const handleSwitchTab = async (tab: ReviewSegment) => {
  const firstVisit = tab === 'bank' && !hasVisitedBank.value
  if (tab === 'bank') hasVisitedBank.value = true
  await review.switchTab(tab, firstVisit ? undefined : refreshBank)
}
const handleWrongChanged = async () => {
  await Promise.all([review.loadWrongs(), review.loadMastery()])
}

onMounted(async () => {
  await review.refreshAll({ refreshBank })
  hasCompletedInitialLoad = true
})

onShow(async () => {
  // 微信冷启时 onShow 先于 onMounted 触发，跳过首帧重复拉取
  if (!hasCompletedInitialLoad) return
  await review.refreshAll({ fromShow: true, refreshBank })
})

onPullDownRefresh(async () => {
  await review.refreshAll({ refreshBank })
  uni.stopPullDownRefresh()
})
</script>

<style lang="scss" scoped>
@import './review.scss';
</style>
