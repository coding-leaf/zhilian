<template>
  <view class="paper-card practice-card">
    <view class="practice-row">
      <view class="practice-info">
        <text class="practice-title">{{ practice.title || '未命名练习' }}</text>
        <text class="practice-meta">
          {{ questionLabel }} · {{ createdAtText }}
        </text>
      </view>
      <view :class="['practice-status', isResumeable(practice) ? '' : 'done']">
        {{ statusText }}
      </view>
      <text class="practice-action" @tap="emit('open', practice)">{{ actionText }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PracticeSummary } from '@/types'
import { isResumeable, practiceActionText, practiceQuestionLabel, practiceStatusText } from '../reviewView'

const props = defineProps<{ practice: PracticeSummary }>()

const emit = defineEmits<{
  (e: 'open', practice: PracticeSummary): void
}>()

const statusText = computed(() => practiceStatusText(props.practice))
const actionText = computed(() => practiceActionText(props.practice))
const questionLabel = computed(() => practiceQuestionLabel(props.practice))
const createdAtText = computed(() => props.practice.created_at?.slice(0, 10) || '近期')
</script>

<style lang="scss" scoped>
@import '../review.scss';
</style>
