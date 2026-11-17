<template>
  <view class="paper-card practice-card" @tap="emit('open', practice)">
    <view class="practice-row">
      <view class="practice-info">
        <view class="practice-title-row">
          <text class="practice-title">{{ practice.title || '未命名练习' }}</text>
          <view :class="['practice-status', statusToneClass]">
            {{ statusText }}
          </view>
        </view>
        <view class="practice-meta-row">
          <text class="practice-meta">{{ questionLabel }} · {{ timeText }}</text>
          <text v-if="sourceLabel" class="practice-source">{{ sourceLabel }}</text>
          <text v-if="accuracyText" class="practice-accuracy-pill">{{ accuracyText }}</text>
        </view>
      </view>
      <text class="practice-action">{{ actionText }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PracticeSummary } from '@/types'
import {
  formatShortDateTime,
  isResumeable,
  practiceAccuracyBadge,
  practiceActionButtonText,
  practiceQuestionLabel,
  practiceStatusText,
} from '../reviewView'

const props = defineProps<{ practice: PracticeSummary }>()

const emit = defineEmits<{
  (e: 'open', practice: PracticeSummary): void
}>()

const statusText = computed(() => practiceStatusText(props.practice))
const actionText = computed(() => practiceActionButtonText(props.practice))
const questionLabel = computed(() => practiceQuestionLabel(props.practice))
const accuracyText = computed(() => practiceAccuracyBadge(props.practice))
const sourceLabel = computed(
  () => props.practice.folder_name || props.practice.material_title || '',
)
const timeText = computed(() =>
  formatShortDateTime(
    props.practice.completed_at || props.practice.submitted_at || props.practice.created_at,
  ),
)
const statusToneClass = computed(() => {
  if (props.practice.status === 'completed') return 'done'
  if (isResumeable(props.practice)) return 'active'
  return ''
})
</script>

<style lang="scss" scoped>
@import '../review.scss';
</style>
