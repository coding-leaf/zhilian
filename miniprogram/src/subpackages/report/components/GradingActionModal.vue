<template>
  <view v-if="visible" class="modal-overlay" @tap.self="close">
    <view class="modal-content paper-card">
      <view class="modal-header">
        <text class="modal-title">{{ isRegrade ? '申请主观题 AI 复查' : '主观题自行评分' }}</text>
        <text class="modal-close" @tap="close">×</text>
      </view>

      <view class="modal-body">
        <template v-if="isRegrade">
          <text class="form-tips">
            如果系统评分遗漏了你的核心得分词或步骤，请补充说明复核理由：
          </text>
          <textarea
            v-model="reason"
            class="form-textarea"
            placeholder="例如：我在第二句中提到了关键概念，但判题时被归为遗漏"
            :maxlength="300"
          />
        </template>

        <template v-else>
          <text class="form-tips">
            请依据采分点给出你的自评分（满分 {{ result?.maxScore ?? 0 }} 分）：
          </text>
          <input
            v-model="scoreInput"
            class="form-input"
            type="digit"
            :placeholder="`0 - ${result?.maxScore ?? 0}`"
          />
          <text class="form-tips">可补充自评说明（可选）：</text>
          <textarea
            v-model="reason"
            class="form-textarea"
            placeholder="说明你自评的依据"
            :maxlength="300"
          />
        </template>
      </view>

      <view class="modal-footer">
        <button class="modal-cancel-btn" @tap="close">取消</button>
        <button class="paper-btn-primary modal-confirm-btn" :loading="submitting" @tap="handleSubmit">
          {{ isRegrade ? '提交复核' : '提交自评' }}
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AttemptResult } from '@/types'
import type { GradingMode } from '../utils/reportView'

const props = defineProps<{
  visible: boolean
  mode: GradingMode
  result: AttemptResult | null
  submitting: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'submit', payload: { reason: string; score: number }): void
}>()

const reason = ref('')
const scoreInput = ref('')
const isRegrade = computed(() => props.mode === 'regrade')

watch(
  () => [props.visible, props.result?.attemptItemId],
  () => {
    reason.value = ''
    scoreInput.value = ''
  },
)

const close = () => emit('update:visible', false)

const handleSubmit = () => {
  const trimmed = reason.value.trim()
  if (!isRegrade.value) {
    const score = Number(scoreInput.value)
    const max = props.result?.maxScore ?? 1
    if (!Number.isFinite(score) || score < 0 || score > max) {
      uni.showToast({ title: `请输入 0 - ${max} 之间的分数`, icon: 'none' })
      return
    }
    emit('submit', { reason: trimmed, score })
    return
  }
  if (!trimmed) {
    uni.showToast({ title: '请输入复核理由', icon: 'none' })
    return
  }
  emit('submit', { reason: trimmed, score: 0 })
}
</script>

<style lang="scss" scoped>
@import '../report.scss';
</style>
