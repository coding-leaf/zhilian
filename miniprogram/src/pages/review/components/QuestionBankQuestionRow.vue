<template>
  <view class="bank-question-wrap">
    <view class="bank-question-row">
      <view class="bank-question-main" @tap="emit('toggle')">
        <view :class="['bank-checkbox', selected ? 'checked' : '']">
          <view v-if="selected" class="bank-check-mark" />
        </view>

        <view class="bank-question-body">
          <text class="bank-question-type">{{ typeLabel }}</text>
          <RichContent :content="question.stem" compact />
        </view>
      </view>

      <view class="bank-question-actions">
        <view class="bank-detail-btn" @tap="emit('toggle-detail')">
          <text class="bank-detail-text">{{ detailExpanded ? '收起解析' : '查看解析' }}</text>
        </view>
        <!-- 动作位：由 QuestionBatchRow 填充「记入错题 / 取消标记」（09-29-manual-wrong-mark） -->
        <slot name="action" />
      </view>
    </view>

    <view v-if="detailExpanded" class="bank-detail-drawer">
      <text v-if="loadingDetail" class="bank-state-text">正在加载答案与解析...</text>
      <view v-else-if="detailError" class="bank-detail-error">
        <text class="bank-state-text">{{ detailError }}</text>
        <text class="bank-retry-text" @tap="emit('retry-detail')">重试</text>
      </view>
      <template v-else-if="detail">
        <view v-if="detail.options?.length" class="bank-detail-options">
          <view v-for="(opt, idx) in detail.options" :key="opt.key || idx" class="bank-detail-opt">
            <text class="bank-detail-opt-key">{{ optionKey(opt, idx) }}.</text>
            <view class="bank-detail-opt-body">
              <RichContent :content="opt.content || optionDisplayText(opt, idx)" compact />
            </view>
          </view>
        </view>
        <view v-if="answerText" class="bank-detail-block">
          <text class="bank-detail-label">参考答案：</text>
          <RichContent :content="answerText" compact />
        </view>
        <view v-if="detail.analysis || detail.explanation" class="bank-detail-block">
          <text class="bank-detail-label">深度解析：</text>
          <RichContent :content="detail.analysis || detail.explanation" compact muted />
        </view>
        <view v-if="detail.grading_points?.length" class="bank-detail-block">
          <text class="bank-detail-label">采分要点：</text>
          <view v-for="(pt, idx) in detail.grading_points" :key="idx" class="bank-detail-pt">
            <RichContent :content="`${idx + 1}. ${pt}`" compact muted />
          </view>
        </view>
      </template>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RichContent from '@/components/RichContent.vue'
import type { QuestionBankItem, QuestionItem } from '@/types'
import { optionDisplayText, optionKey, questionTypeLabel } from '@/api'

const props = defineProps<{
  question: QuestionBankItem
  selected: boolean
  detailExpanded?: boolean
  detail?: QuestionItem
  loadingDetail?: boolean
  detailError?: string
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
  (e: 'toggle-detail'): void
  (e: 'retry-detail'): void
}>()

const typeLabel = computed(() => questionTypeLabel(props.question.type))
const answerText = computed(() => {
  const raw = props.detail?.answer
  if (raw === undefined || raw === null || raw === '') return ''
  if (Array.isArray(raw)) return raw.join('、')
  return String(raw)
})
</script>

<style lang="scss" scoped>
@import '../questionBank.scss';
</style>
