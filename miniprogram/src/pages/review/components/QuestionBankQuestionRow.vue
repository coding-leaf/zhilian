<template>
  <view class="bank-question-row">
    <view class="bank-question-main" @tap="emit('toggle')">
      <view v-if="question.selectable" :class="['bank-checkbox', selected ? 'checked' : '']">
        <text v-if="selected" class="bank-checkmark">✓</text>
      </view>
      <view v-else class="bank-pending-badge">
        <text class="bank-pending-text">待审核</text>
      </view>

      <view class="bank-question-body">
        <text class="bank-question-type">{{ typeLabel }}</text>
        <text class="bank-question-stem">{{ question.stem }}</text>
      </view>
    </view>

    <!-- 动作位：由 QuestionBatchRow 填充「记入错题 / 取消标记」（09-29-manual-wrong-mark） -->
    <slot name="action" />
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QuestionBankItem } from '@/types'
import { questionTypeLabel } from '@/api'

const props = defineProps<{
  question: QuestionBankItem
  selected: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
}>()

const typeLabel = computed(() => questionTypeLabel(props.question.type))
</script>

<style lang="scss" scoped>
@import '../review.scss';
</style>
