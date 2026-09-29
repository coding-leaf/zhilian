<template>
  <view class="paper-card bank-batch-card">
    <view class="bank-batch-header">
      <view :class="['bank-checkbox', checkboxClass]" @tap="emit('toggle')">
        <text v-if="checkState === 'all'" class="bank-checkmark">✓</text>
        <text v-else-if="checkState === 'partial'" class="bank-partial-mark">－</text>
      </view>

      <view class="bank-batch-info" @tap="emit('toggle')">
        <text class="bank-batch-label">{{ label }}</text>
        <text class="bank-batch-meta">共 {{ batch.questionCount }} 题</text>
      </view>

      <text class="bank-expand-btn" @tap="emit('toggle-expand')">
        {{ expanded ? '收起' : '展开' }}
      </text>
    </view>

    <view v-if="expanded" class="bank-question-list">
      <view v-if="isLoadingQuestions" class="bank-state-line">
        <text class="bank-state-text">正在加载题目...</text>
      </view>

      <view v-else-if="questionError" class="bank-state-line">
        <text class="bank-state-text">{{ questionError }}</text>
        <text class="bank-retry-text" @tap="emit('retry-questions')">重试</text>
      </view>

      <view v-else-if="questions.length === 0" class="bank-state-line">
        <text class="bank-state-text">该批次暂无可见题目。</text>
      </view>

      <template v-else>
        <QuestionBankQuestionRow
          v-for="question in questions"
          :key="question.id"
          :question="question"
          :selected="selectedIds.includes(question.id)"
          @toggle="emit('toggle-question', question.id)"
        >
          <!-- 动作位（由 09-29-question-bank-page 预留）：记入错题 / 取消标记 -->
          <template #action>
            <view
              :class="[
                'bank-wrong-btn',
                wrongMarkClass(question.id),
                { pending: wrongPendingIds.includes(question.id) },
              ]"
              @tap="emit('toggle-wrong', question.id)"
            >
              <text class="bank-wrong-text">
                {{ wrongMarkLabel(wrongMarks.get(question.id) ?? null) }}
              </text>
            </view>
          </template>
        </QuestionBankQuestionRow>
        <text v-if="batch.pendingReviewCount > 0" class="bank-pending-hint">
          待审核题目需先通过质检才能加入练习。
        </text>
      </template>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QuestionBankItem, QuestionBatchSummary, WrongRecordItem } from '@/types'
import { describeBatchLabel, type BatchCheckState } from '@/utils/questionBatch'
import { wrongMarkLabel } from '../reviewView'
import QuestionBankQuestionRow from './QuestionBankQuestionRow.vue'

const props = defineProps<{
  batch: QuestionBatchSummary
  checkState: BatchCheckState
  expanded: boolean
  questions: QuestionBankItem[]
  selectedIds: string[]
  isLoadingQuestions: boolean
  questionError: string
  /** question_id → 错题记录；缺键即未标记。 */
  wrongMarks: Map<string, WrongRecordItem>
  /** 正在标记/取消中的题目 ID（请求在途禁用，避免双击打出两次往返）。 */
  wrongPendingIds: string[]
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
  (e: 'toggle-expand'): void
  (e: 'toggle-question', questionId: string): void
  (e: 'retry-questions'): void
  (e: 'toggle-wrong', questionId: string): void
}>()

/** 与核对出题页共用同一标签推导，禁止第二份实现。 */
const label = computed(() => describeBatchLabel(props.batch))

/** 已标记（判题来源，点按走「已掌握」）与已掌握用不同色，未标记无态。 */
const wrongMarkClass = (questionId: string): string => {
  const record = props.wrongMarks.get(questionId)
  if (!record) return ''
  return record.is_mastered ? 'mastered' : 'marked'
}

const checkboxClass = computed(() => {
  if (props.checkState === 'all') return 'checked'
  if (props.checkState === 'partial') return 'partial'
  return ''
})
</script>

<style lang="scss" scoped>
@import '../review.scss';
</style>
