<template>
  <view v-if="visible" class="dialog-mask" @tap="handleCancel">
    <view class="dialog-body" @tap.stop>
      <text class="dialog-title">新建课程</text>
      <input
        v-model="name"
        class="dialog-input"
        placeholder="请输入课程名称"
        :maxlength="100"
        @input="handleInput"
      />
      <text v-if="errorText" class="dialog-error">{{ errorText }}</text>
      <view class="dialog-actions">
        <button class="btn-cancel" @tap="handleCancel">取消</button>
        <button class="btn-confirm" :disabled="!isValid || submitting" @tap="handleConfirm">
          {{ submitting ? '创建中...' : '创建' }}
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';

interface Props {
  visible?: boolean;
  /** 创建请求进行中：禁用提交与取消，防止重复提交与中途关闭。 */
  submitting?: boolean;
}

interface Emits {
  (e: 'update:visible', value: boolean): void;
  (e: 'confirm', name: string): void;
  (e: 'cancel'): void;
}

const props = withDefaults(defineProps<Props>(), { visible: false, submitting: false });
const emit = defineEmits<Emits>();

const name = ref('');
const errorText = ref('');

const trimmedName = computed(() => name.value.trim());
const isValid = computed(() => trimmedName.value.length > 0 && trimmedName.value.length <= 100);

watch(
  () => props.visible,
  (opened) => {
    if (opened) {
      name.value = '';
      errorText.value = '';
    }
  },
);

function handleInput(): void {
  errorText.value = '';
}

function handleConfirm(): void {
  if (props.submitting) {
    return;
  }
  if (!isValid.value) {
    errorText.value = '课程名称不能为空且不超过 100 字';
    return;
  }
  emit('confirm', trimmedName.value);
}

function handleCancel(): void {
  if (props.submitting) {
    return;
  }
  emit('update:visible', false);
  emit('cancel');
}
</script>

<style lang="scss" scoped>
.dialog-mask {
  position: fixed;
  inset: 0;
  background-color: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: $spacing-xl;
  box-sizing: border-box;
}

.dialog-body {
  width: 100%;
  max-width: 600rpx;
  background-color: #ffffff;
  border-radius: $radius-lg;
  padding: $spacing-xl;
  box-sizing: border-box;
}

.dialog-title {
  font-size: $font-size-section;
  font-weight: $font-weight-bold;
  color: $--wot-color-gray-9;
  display: block;
  margin-bottom: $spacing-lg;
}

.dialog-input {
  height: 88rpx;
  border: 1.5px solid $--wot-color-gray-4;
  border-radius: $radius-md;
  padding: 0 $spacing-lg;
  font-size: $font-size-body;
  color: $--wot-color-gray-9;
  background-color: $--wot-color-gray-1;
  box-sizing: border-box;
}

.dialog-error {
  display: block;
  margin-top: $spacing-sm;
  font-size: $font-size-caption;
  color: $--wot-color-danger-text;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: $spacing-md;
  margin-top: $spacing-xl;
}

.btn-cancel,
.btn-confirm {
  min-height: 76rpx;
  line-height: 1.5;
  padding: 0 $spacing-xl;
  border-radius: $radius-pill;
  font-size: $font-size-card;
  font-weight: $font-weight-bold;
  margin: 0;
}

.btn-cancel {
  background-color: $--wot-color-gray-2;
  color: $--wot-color-gray-7;
  border: 1px solid $--wot-color-gray-4;
}

.btn-confirm {
  background-color: $--wot-color-theme;
  color: #ffffff;
  border: none;

  &[disabled] {
    background-color: $--wot-color-gray-5;
    color: #ffffff;
  }
}
</style>
