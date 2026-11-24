<template>
  <view class="bank-section">
    <view class="section-title-row">
      <text class="section-title">我的题库</text>
      <text class="section-refresh" @tap="loadBatches">刷新</text>
    </view>

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
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import type { WrongRecordItem } from '@/types'
import QuestionBatchRow from './QuestionBatchRow.vue'
import { useQuestionBank } from '../composables/useQuestionBank'
import { useWrongMarking } from '../composables/useWrongMarking'

const props = defineProps<{
  wrongRecords: WrongRecordItem[]
}>()

const emit = defineEmits<{
  (e: 'wrong-changed'): void
}>()

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
} = useQuestionBank()

onMounted(loadBatches)

const refresh = () => loadBatches()

/** 供父页面的 onShow 与下拉刷新一并刷新本区块。 */
defineExpose({ refresh, loadBatches })

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
