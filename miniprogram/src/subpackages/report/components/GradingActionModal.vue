<template>
  <view v-if="visible" class="modal-overlay grading-modal-overlay">
    <!-- 关闭热区独立成元素：@tap.self 在小程序端被编译器丢弃，绑在容器上会导致点内容（含输入框）即关闭 -->
    <view class="modal-backdrop" @tap="close" />
    <view class="modal-content paper-card">
      <view class="modal-header">
        <text class="modal-title">{{ isRegrade ? '申请主观题 AI 复查' : '主观题自行评分' }}</text>
        <text class="modal-close" @tap="close">关闭</text>
      </view>

      <view class="modal-body">
        <view v-if="result?.gradingPoints?.length" class="modal-rubric-box">
          <text class="modal-rubric-title">参考采分点：</text>
          <view v-for="(pt, idx) in result.gradingPoints" :key="idx" class="modal-rubric-item">
            <RichContent :content="`${idx + 1}. ${pt}`" compact muted />
          </view>
        </view>

        <template v-if="isRegrade">
          <text class="form-tips">
            如果系统评分遗漏了你的核心得分词或步骤，请补充说明复核理由：
          </text>
          <textarea
            v-model="reason"
            class="form-textarea"
            placeholder="例如：我在第二句中提到了关键概念，但判题时被归为遗漏"
            :fixed="true"
            :cursor-spacing="24"
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
            :cursor-spacing="24"
            :placeholder="`0 - ${result?.maxScore ?? 0}`"
          />
          <text class="form-tips">可补充自评说明（可选）：</text>
          <textarea
            v-model="reason"
            class="form-textarea"
            placeholder="说明你自评的依据"
            :fixed="true"
            :cursor-spacing="24"
            :maxlength="300"
          />
        </template>
      </view>

      <view class="modal-footer">
        <button class="modal-cancel-btn" @tap="close">取消</button>
        <button
          class="paper-btn-primary modal-confirm-btn"
          :loading="submitting"
          :disabled="submitting"
          @tap="handleSubmit"
        >
          {{ isRegrade ? '提交复核' : '提交自评' }}
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import RichContent from '@/components/RichContent.vue'
import { safeShowToast } from '@/utils/loadingGuard'
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
      safeShowToast(`请输入 0 - ${max} 之间的分数`)
      return
    }
    emit('submit', { reason: trimmed, score })
    return
  }
  if (!trimmed) {
    safeShowToast('请输入复核理由')
    return
  }
  emit('submit', { reason: trimmed, score: 0 })
}
</script>

<style lang="scss" scoped>
@import '../../../styles/modal.scss';
@import '../report.scss';

.grading-modal-overlay {
  z-index: var(--z-modal);
}

.modal-content {
  max-width: 620rpx;
  background: var(--color-bg-card);
}

.modal-rubric-box {
  margin-bottom: 16rpx;
  padding: 14rpx 18rpx;
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-paper-border);
  border-radius: 10rpx;
}

.modal-rubric-title {
  display: block;
  font-size: 22rpx;
  font-weight: 600;
  color: var(--color-ink-body);
  margin-bottom: 6rpx;
}

.modal-rubric-item {
  margin-bottom: 4rpx;
}
</style>
