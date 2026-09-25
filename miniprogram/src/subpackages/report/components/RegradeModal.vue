<template>
  <view v-if="visible" class="regrade-modal-mask" @tap.self="handleClose">
    <view class="modal-card">
      <!-- 头部：标题与关闭按钮 -->
      <view class="modal-header">
        <text class="modal-title">申请重新判题</text>
        <view class="close-btn" @tap="handleClose">
          <text>关闭</text>
        </view>
      </view>

      <!-- 可滚动主体内容 -->
      <scroll-view scroll-y class="modal-scroll-content">
        <!-- 申请重判说明提示 -->
        <view class="instruction-box">
          <text class="instruction-text">
            若您对当前题目的判定结果存有异议（如大模型判分不准、要点漏判等），可提交重判申请。系统将安排重新审核判定。
          </text>
        </view>

        <!-- 关联题干预览 -->
        <view v-if="stem" class="stem-preview">
          <text class="preview-label">关联试题</text>
          <text class="stem-text">{{ stem }}</text>
        </view>

        <!-- 重判申请理由输入区 -->
        <view class="reason-section">
          <view class="reason-label-row">
            <text class="reason-label">申请理由（必填）</text>
            <text class="required-mark">至少 2 个字符</text>
          </view>
          <textarea
            v-model="localReason"
            class="reason-textarea"
            placeholder="请详细说明您申请重判的理由（例如：答案中已包含关键步骤...）"
            :maxlength="200"
          />
          <view
            class="char-count"
            :class="{ invalid: localReason.trim().length > 0 && localReason.trim().length < 2 }"
          >
            {{ localReason.length }} / 200
          </view>
        </view>
      </scroll-view>

      <!-- 底部操作按钮 -->
      <view class="modal-actions">
        <view class="action-btn btn-secondary" @tap="handleClose">
          <text>取消</text>
        </view>
        <view
          class="action-btn btn-primary"
          :class="{ disabled: !canSubmit || isBusy }"
          @tap="handleSubmit"
        >
          <text>{{ isBusy ? '提交中...' : '提交重判申请' }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * RegradeModal.vue
 * Modal for submitting question regrading requests with validation and API call.
 * Complies with docs/DESIGN.md & spec ZL-135.
 * Zero-Emoji Policy: No emoji allowed.
 */

import { computed, ref, watch } from 'vue';
import { requestRegrade } from '@/api/diagnosis';

interface Props {
  visible?: boolean;
  attemptItemId: string;
  stem?: string;
  submitting?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  stem: '',
  submitting: false,
});

const emit = defineEmits<{
  (e: 'update:visible', visible: boolean): void;
  (e: 'submit', payload: { attempt_item_id: string; reason: string }): void;
  (e: 'success', payload: { attempt_item_id: string; reason: string }): void;
}>();

const localReason = ref('');
const localSubmitting = ref(false);

const isBusy = computed(() => props.submitting || localSubmitting.value);
const canSubmit = computed(() => localReason.value.trim().length >= 2);

watch(
  () => props.visible,
  (val) => {
    if (val) {
      localReason.value = '';
      localSubmitting.value = false;
    }
  },
  { immediate: true },
);

function handleClose(): void {
  emit('update:visible', false);
}

async function handleSubmit(): Promise<void> {
  const reasonText = localReason.value.trim();
  if (reasonText.length < 2) {
    uni.showToast({ title: '重判理由至少需2个字符', icon: 'none' });
    return;
  }
  if (isBusy.value) return;

  const payload = {
    attempt_item_id: props.attemptItemId,
    reason: reasonText,
  };

  emit('submit', payload);

  localSubmitting.value = true;
  try {
    const res = await requestRegrade(payload);
    if (res && (res.code === 0 || res.data)) {
      uni.showToast({ title: '重判申请已提交', icon: 'success' });
      emit('success', payload);
      emit('update:visible', false);
    } else {
      uni.showToast({ title: res?.message || '提交失败', icon: 'none' });
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : '提交异常';
    uni.showToast({ title: msg, icon: 'none' });
  } finally {
    localSubmitting.value = false;
  }
}
</script>

<style lang="scss" scoped>
@import './RegradeModal.scss';
</style>
