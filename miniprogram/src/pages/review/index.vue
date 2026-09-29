<template>
  <view class="review-container">
    <view class="paper-card summary-card">
      <text class="title">学情全景与错题巩固</text>
      <text class="subtitle">按课程归类错题 · 举一反三巩固闭环</text>

      <view class="stats-row">
        <view class="stat-col">
          <text class="stat-num">{{ pendingCount }}</text>
          <text class="stat-lbl">待攻克错题</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-col">
          <text class="stat-num mastered-num">{{ masteredCount }}</text>
          <text class="stat-lbl">已消灭错题</text>
        </view>
        <view class="stat-divider" />
        <view class="stat-col">
          <text class="stat-num material-num">{{ groupOptions.length }}</text>
          <text class="stat-lbl">归属范围</text>
        </view>
      </view>
    </view>

    <QuestionBankSection />

    <template v-if="practices.length">
      <view class="section-title-row">
        <text class="section-title">我的练习</text>
        <text class="section-refresh" @tap="loadPractices">刷新</text>
      </view>
      <PracticeEntryCard
        v-for="practice in practices"
        :key="practice.id"
        :practice="practice"
        @open="openPractice"
      />
    </template>

    <view class="section-title-row">
      <text class="section-title">错题巩固</text>
      <text class="section-refresh" @tap="loadWrongs">刷新</text>
    </view>

    <view v-if="groupOptions.length" class="group-scroll">
      <scroll-view scroll-x class="group-scroll" :show-scrollbar="false">
        <view class="group-tabs">
          <view
            v-for="option in groupOptions"
            :key="option.key"
            :class="['group-chip', selectedGroupKey === option.key ? 'active' : '']"
            @tap="selectGroup(option.key)"
          >
            <text class="group-chip-text">{{ option.label }}</text>
            <text class="group-chip-count">{{ option.count }}</text>
          </view>
        </view>
      </scroll-view>
    </view>

    <view v-if="needsGroupChoice" class="paper-card">
      <text class="action-desc">错题涉及多个课程，请先选择要巩固的课程或资料范围。</text>
    </view>

    <view v-if="activeGroup && activeKpIds.length > 0 && activeScopeReady" class="paper-card action-card">
      <view class="action-info">
        <text class="action-title">错题薄弱点举一反三</text>
        <text class="action-desc">
          汇总「{{ activeGroup.label }}」下 {{ activeKpIds.length }} 个薄弱考点，可一键再生题目巩固。
        </text>
      </view>
      <button class="paper-btn-primary quick-gen-btn" :loading="isGenerating" @tap="handleBatchRegenerate">
        立即巩固
      </button>
    </view>

    <view v-if="activeGroup && !activeScopeReady" class="paper-card">
      <text class="action-desc">该范围内的资料尚未归属课程，暂时无法再生题，请先将资料归入课程。</text>
    </view>

    <view class="wrong-list">
      <WrongRecordCard
        v-for="record in visibleRecords"
        :key="record.id"
        :record="record"
        @practice="handleSingleKpPractice"
      />
      <view v-if="visibleRecords.length === 0" class="empty-state">
        <text class="empty-text">
          {{ isLoadingWrongs ? '正在加载错题...' : '太棒了！当前范围内没有待巩固的错题。' }}
        </text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { onPullDownRefresh } from '@dcloudio/uni-app'
import { apiListWrongRecords } from '@/api'
import {
  buildWrongGroupOptions,
  recordsInGroup,
  resolveRegenerateScope,
  type WrongGroupOption,
} from '@/api/adapters/wrong'
import { usePracticeStore } from '@/stores/practice'
import type { PracticeSummary, WrongRecordItem } from '@/types'
import WrongRecordCard from './components/WrongRecordCard.vue'
import PracticeEntryCard from './components/PracticeEntryCard.vue'
import QuestionBankSection from './components/QuestionBankSection.vue'
import {
  groupKnowledgePointIds,
  hasScope,
  isResumeable,
  recordRegenerateScope,
} from './reviewView'

const practiceStore = usePracticeStore()

const wrongRecords = ref<WrongRecordItem[]>([])
const groupOptions = ref<WrongGroupOption[]>([])
const selectedGroupKey = ref('')
const practices = ref<PracticeSummary[]>([])
const isLoadingWrongs = ref(false)
const isGenerating = ref(false)

const PAGE_SIZE = 50
const MAX_PAGES = 6

const masteredCount = computed(() => wrongRecords.value.filter((item) => item.is_mastered).length)
const pendingCount = computed(() => wrongRecords.value.filter((item) => !item.is_mastered).length)

const activeGroup = computed<WrongGroupOption | null>(() => {
  return groupOptions.value.find((option) => option.key === selectedGroupKey.value) || null
})

const needsGroupChoice = computed(() => groupOptions.value.length > 1 && !activeGroup.value)

const visibleRecords = computed(() => {
  if (!activeGroup.value) return wrongRecords.value
  return recordsInGroup(wrongRecords.value, activeGroup.value)
})

const activeKpIds = computed(() => groupKnowledgePointIds(visibleRecords.value, activeGroup.value))

const activeScopeReady = computed(() => {
  const scope = resolveRegenerateScope(activeGroup.value)
  return Boolean(scope && hasScope(scope))
})

const loadWrongs = async () => {
  isLoadingWrongs.value = true
  try {
    const collected: WrongRecordItem[] = []
    let total = 0
    for (let page = 1; page <= MAX_PAGES; page += 1) {
      const res = await apiListWrongRecords({ page, page_size: PAGE_SIZE })
      collected.push(...(res.items || []))
      total = res.total ?? collected.length
      if (page === 1) {
        groupOptions.value = buildWrongGroupOptions(res.groups || [])
      }
      if (collected.length >= total) break
    }
    wrongRecords.value = collected
    if (groupOptions.value.length === 1) {
      selectedGroupKey.value = groupOptions.value[0].key
    } else if (!groupOptions.value.some((option) => option.key === selectedGroupKey.value)) {
      selectedGroupKey.value = ''
    }
  } catch (error) {
    console.error('Failed to load wrong records', error)
  } finally {
    isLoadingWrongs.value = false
  }
}

const loadPractices = async () => {
  try {
    practices.value = await practiceStore.loadPractices(undefined, 10)
  } catch (error) {
    console.error('Failed to load practices', error)
  }
}

onMounted(async () => {
  await Promise.all([loadWrongs(), loadPractices()])
})

onPullDownRefresh(async () => {
  await Promise.all([loadWrongs(), loadPractices()])
  uni.stopPullDownRefresh()
})

const selectGroup = (key: string) => {
  selectedGroupKey.value = key
}

const navigateToSession = (practiceId: string) => {
  uni.navigateTo({
    url: `/subpackages/practice/pages/session/index?practice_id=${practiceId}`,
    fail: () => uni.showToast({ title: '打开练习失败，请重试', icon: 'none' }),
  })
}

const openPractice = (practice: PracticeSummary) => {
  if (isResumeable(practice)) {
    navigateToSession(practice.id)
    return
  }
  uni.navigateTo({
    url: `/subpackages/report/pages/detail/index?practice_id=${practice.id}`,
    fail: () => uni.showToast({ title: '打开结果页失败，请重试', icon: 'none' }),
  })
}

const runRegenerate = async (kpIds: string[], scope: { folderId?: string; materialId?: string }) => {
  isGenerating.value = true
  uni.showLoading({ title: '生成中...' })
  try {
    const { session, coverage } = await practiceStore.regenerateFromWrongPoints(kpIds, scope)
    uni.hideLoading()
    if (coverage.missing.length > 0) {
      uni.showToast({ title: `仍有 ${coverage.missing.length} 个考点未覆盖`, icon: 'none' })
    }
    navigateToSession(session.id)
  } catch (error: any) {
    uni.hideLoading()
    uni.showToast({ title: error?.message || '生成失败', icon: 'none' })
  } finally {
    isGenerating.value = false
  }
}

const handleBatchRegenerate = async () => {
  const scope = resolveRegenerateScope(activeGroup.value)
  if (!scope || !activeKpIds.value.length) return
  await runRegenerate(activeKpIds.value, scope)
}

const handleSingleKpPractice = async (record: WrongRecordItem) => {
  if (!record.knowledge_point_id) return
  const scope = recordRegenerateScope(record)
  if (!hasScope(scope)) {
    uni.showToast({ title: '该错题所属资料未归属课程，暂时无法出题', icon: 'none' })
    return
  }
  await runRegenerate([record.knowledge_point_id], scope)
}
</script>

<style lang="scss" scoped>
@import './review.scss';
</style>
