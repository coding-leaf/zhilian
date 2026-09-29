<template>
  <view class="bank-section">
    <view class="section-title-row">
      <text class="section-title">我的题目</text>
      <text class="section-refresh" @tap="loadBatches">刷新</text>
    </view>

    <view v-if="isLoading && batches.length === 0" class="paper-card bank-state-card">
      <text class="bank-state-text">正在加载题目批次...</text>
    </view>

    <view v-else-if="loadError && batches.length === 0" class="paper-card bank-state-card">
      <text class="bank-state-text">{{ loadError }}</text>
      <button class="bank-retry-btn" @tap="loadBatches">重试</button>
    </view>

    <view v-else-if="batches.length === 0" class="paper-card bank-state-card">
      <text class="bank-state-text">
        题库还是空的。到资料详情页发起「智能出题」，生成结果会自动归入这里的批次。
      </text>
    </view>

    <template v-else>
      <view v-if="loadError" class="paper-card bank-state-card">
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
        @toggle="toggleBatch(batch.batchId)"
        @toggle-expand="toggleExpand(batch.batchId)"
        @toggle-question="(questionId) => toggleQuestion(batch.batchId, questionId)"
        @retry-questions="retryBatchQuestions(batch.batchId)"
        @toggle-wrong="handleToggleWrong"
      />

      <view v-if="hasMore" class="bank-more">
        <button class="bank-more-btn" :loading="isLoadingMore" @tap="loadMoreBatches">
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
          :disabled="selectedCount === 0"
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
  /** 页面已拉取的全量错题：本题库区块只按 question_id 建索引，不自己再拉一份。 */
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
  toggleBatch,
  toggleQuestion,
  startPractice,
} = useQuestionBank()

/**
 * 进页面即拉取批次。
 *
 * 此前本组件只把 `loadBatches` 挂在「刷新」与「重试」两个按钮上，没有任何程序化调用点，
 * 于是进入页面时一个请求都不发，「我的题目」恒显示「题库还是空的」——而接口其实有数据。
 * 空态文案还会引导用户「到资料详情页发起智能出题」，让已出过题的人**重复劳动**。
 *
 * 计划任务：ZL-144（缺陷编号 P1-8）。回归测试见 `tests/questionBankSection.spec.ts`——
 * 该用例挂载本组件并断言「挂载即请求」，是唯一能拦住这类**接线**缺陷的层次：
 * `questionBank.spec.ts` 的 16 个组合式函数用例当时全绿。
 */
onMounted(loadBatches)

/** 供父页面的下拉刷新一并刷新本区块；见 `pages/review/index.vue` 的 onPullDownRefresh。 */
defineExpose({ loadBatches })

const {
  marksById: wrongMarks,
  pendingIds: wrongPendingIds,
  toggle: toggleWrongMark,
} = useWrongMarking(() => props.wrongRecords)

/** 结果落到错题列表：由页面重新拉取，保证题库与「错题巩固」看到同一份数据。 */
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
@import '../review.scss';
</style>
