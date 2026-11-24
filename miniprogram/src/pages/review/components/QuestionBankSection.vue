<template>
  <view class="bank-section">
    <view class="section-title-row">
      <text class="section-title">我的题库</text>
      <text class="section-refresh" @tap="refresh">刷新</text>
    </view>

    <view class="bank-view-tabs">
      <view
        v-for="tab in viewTabs"
        :key="tab.key"
        :class="['bank-view-tab', activeView === tab.key ? 'active' : '']"
        @tap="switchView(tab.key)"
      >
        <text class="bank-view-tab-text">{{ tab.label }}</text>
      </view>
    </view>

    <view v-if="hasVisitedCollections" v-show="activeView === 'collections'">
      <QuestionCollectionView
        ref="collectionRef"
        :folder-id="folderId"
        @collect="emit('collect', $event)"
      />
    </view>

    <view v-if="hasVisitedGrouped" v-show="activeView === 'grouped'">
      <QuestionGroupedView
        ref="groupedRef"
        :folder-id="folderId"
        :wrong-marks="wrongMarks"
        :wrong-pending-ids="wrongPendingIds"
        @toggle-wrong="handleToggleWrong"
        @collect="emit('collect', $event)"
      />
    </view>

    <view v-show="activeView === 'batches'">
      <view v-if="isLoading && batches.length === 0" class="paper-card bank-state-card">
        <text class="bank-state-text">正在加载题目批次...</text>
      </view>

      <view v-else-if="loadError && batches.length === 0" class="paper-card bank-state-card bank-error-card">
        <text class="bank-state-text">{{ loadError }}</text>
        <button class="bank-retry-btn" @tap="loadBatches">重试</button>
      </view>

      <view v-else-if="batches.length === 0" class="paper-card bank-state-card">
        <text class="bank-state-text">
          题库还是空的。到资料详情页发起「智能出题」，生成结果会自动归入这里的批次。
        </text>
      </view>

      <template v-else>
        <view v-if="loadError" class="paper-card bank-state-card bank-error-card">
          <text class="bank-state-text">{{ loadError }}</text>
          <button class="bank-retry-btn" @tap="loadBatches">重试</button>
        </view>

        <QuestionBatchRow
          v-for="batch in batches"
          :key="batch.batchId ?? 'unbatched-group'"
          :batch="batch"
          :check-state="checkState(batch.batchId)"
          :expanded="isExpanded(batch.batchId)"
          :questions="questionsFor(batch.batchId)"
          :selected-ids="selectedIdsFor(batch.batchId)"
          :is-loading-questions="isLoadingQuestions(batch.batchId)"
          :question-error="questionError(batch.batchId)"
          :wrong-marks="wrongMarks"
          :wrong-pending-ids="wrongPendingIds"
          :expanded-detail-ids="expandedDetailIds"
          :question-details="questionDetails"
          :loading-detail-ids="loadingDetailIds"
          :detail-errors="detailErrors"
          @toggle="toggleBatch(batch.batchId)"
          @toggle-expand="toggleExpand(batch.batchId)"
          @toggle-question="(questionId) => toggleQuestion(batch.batchId, questionId)"
          @retry-questions="retryBatchQuestions(batch.batchId)"
          @toggle-wrong="handleToggleWrong"
          @toggle-detail="toggleQuestionDetail"
          @retry-detail="retryQuestionDetail"
          @collect="emit('collect', $event)"
        />

        <view v-if="hasMore" class="bank-more">
          <button
            class="bank-more-btn"
            :loading="isLoadingMore"
            :disabled="isLoadingMore"
            @tap="loadMoreBatches"
          >
            加载更多批次
          </button>
        </view>

        <view class="paper-card action-card bank-action-card">
          <view class="action-info">
            <text class="action-title">已选 {{ selectedCount }} 题</text>
            <text class="action-desc">{{ actionHint }}</text>
          </view>
          <button
            class="paper-btn-primary quick-gen-btn"
            :loading="isStarting"
            :disabled="selectedCount === 0 || isStarting"
            @tap="startPractice"
          >
            立即开练
          </button>
        </view>
      </template>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { WrongRecordItem } from '@/types'
import QuestionBatchRow from './QuestionBatchRow.vue'
import QuestionCollectionView from './QuestionCollectionView.vue'
import QuestionGroupedView from './QuestionGroupedView.vue'
import { useQuestionBank } from '../composables/useQuestionBank'
import { useWrongMarking } from '../composables/useWrongMarking'

type BankView = 'collections' | 'grouped' | 'batches'

const props = withDefaults(defineProps<{
  wrongRecords: WrongRecordItem[]
  folderId?: string
  isActive?: boolean
}>(), {
  folderId: 'all',
  isActive: true,
})

const emit = defineEmits<{
  (e: 'wrong-changed'): void
  (e: 'collect', questionId: string): void
}>()

const viewTabs: Array<{ key: BankView; label: string }> = [
  { key: 'collections', label: '题单收纳' },
  { key: 'grouped', label: '讲义考点' },
  { key: 'batches', label: '生成批次' },
]

const activeView = ref<BankView>('batches')
const hasVisitedCollections = ref(false)
const hasVisitedGrouped = ref(false)
const loadedViews = new Set<BankView>()
const collectionRef = ref<InstanceType<typeof QuestionCollectionView> | null>(null)
const groupedRef = ref<InstanceType<typeof QuestionGroupedView> | null>(null)

const {
  batches,
  isLoading,
  isLoadingMore,
  loadError,
  hasMore,
  selectedCount,
  isStarting,
  expandedDetailIds,
  questionDetails,
  loadingDetailIds,
  detailErrors,
  isExpanded,
  isLoadingQuestions,
  questionError,
  questionsFor,
  checkState,
  selectedIdsFor,
  loadBatches,
  loadMoreBatches,
  toggleExpand,
  retryBatchQuestions,
  toggleQuestionDetail,
  retryQuestionDetail,
  toggleBatch,
  toggleQuestion,
  startPractice,
  resetBankState,
} = useQuestionBank(() => props.folderId)

const loadView = async (view: BankView) => {
  loadedViews.add(view)
  if (view === 'collections') {
    await collectionRef.value?.refresh()
    return
  }
  if (view === 'grouped') {
    await groupedRef.value?.refresh()
    return
  }
  await loadBatches()
}

const switchView = async (view: BankView) => {
  activeView.value = view
  if (view === 'collections') hasVisitedCollections.value = true
  if (view === 'grouped') hasVisitedGrouped.value = true
  await nextTick()
  if (!loadedViews.has(view)) {
    await loadView(view)
  }
}

const refresh = () => loadView(activeView.value)
const refreshCollections = async () => {
  if (hasVisitedCollections.value) {
    await collectionRef.value?.refresh()
  }
}

watch(
  () => props.folderId,
  () => {
    loadedViews.clear()
    resetBankState()
    collectionRef.value?.resetState()
    groupedRef.value?.resetState()
    if (props.isActive) {
      void loadView(activeView.value)
    }
  },
)

onMounted(() => {
  void loadView(activeView.value)
})

/** 供父页面的 onShow 与下拉刷新一并刷新本区块。 */
defineExpose({ refresh, loadBatches, refreshCollections })

const {
  marksById: wrongMarks,
  pendingIds: wrongPendingIds,
  toggle: toggleWrongMark,
} = useWrongMarking(() => props.wrongRecords)

const handleToggleWrong = async (questionId: string) => {
  if (await toggleWrongMark(questionId)) emit('wrong-changed')
}

const actionHint = computed(() => {
  if (selectedCount.value === 0) {
    return '勾选批次或展开逐题勾选，合成为一次练习再次作答'
  }
  return '只统计可用题目：开练题数与这里显示的题数一致'
})
</script>

<style lang="scss" scoped>
@import '../questionBank.scss';

.bank-retry-btn,
.bank-more-btn {
  margin: 0;
  line-height: 1.4;

  &::after {
    border: none;
  }
}
</style>
