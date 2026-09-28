<template>
  <view v-if="visible" class="modal-overlay">
    <!-- 关闭热区独立成元素：@tap.self 在小程序端被编译器丢弃，绑在容器上会导致点内容（含输入框）即关闭 -->
    <view class="modal-backdrop" @tap="close" />
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

/* 关闭热区：由独立元素承载「点外部关闭」，容器不再绑 tap（见模板注释）。
   内容必须显式提升 z-index，否则会被绝对定位的 backdrop 盖住。

   `inset: 0` 已覆盖到浮层内边距的外沿，**不要**改用负偏移去「补」内边距：
   绝对定位的包含块是定位祖先的 padding box，它**包含**内边距区域；report.scss 的
   `.modal-overlay` 是 fixed + inset:0 且无边框，其 padding box 即整个视口，
   那 32rpx 内边距本就在 backdrop 之下。实测（Chrome 真实布局，视口最外缘逐点
   elementFromPoint）：`inset: 0` 与 `-32rpx` 在视口内每个测点命中完全相同，
   后者只是把热区推出视口。 */
.modal-backdrop {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 0;
}

.modal-content {
  position: relative;
  z-index: 1;
}
</style>
