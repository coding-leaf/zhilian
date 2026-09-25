<template>
  <view
    class="quick-upload-bar"
    :class="{ 'is-disabled': disabled }"
    role="button"
    aria-label="快捷上传学习资料"
    @tap="handleCardClick"
  >
    <view class="upload-content-wrapper">
      <view class="upload-icon-box" aria-hidden="true">
        <view class="upload-icon-arrow" />
      </view>

      <view class="upload-text-box">
        <text class="upload-title">快捷上传学习资料</text>
        <text class="upload-subtitle">支持聊天文档与拍照导入</text>
      </view>
    </view>

    <view class="upload-action-pill">
      <text class="pill-text">点击上传</text>
    </view>

    <!-- 挂载资料上传模态弹窗 -->
    <MaterialUpload
      v-model:visible="isUploadModalVisible"
      @success="handleUploadSuccess"
      @close="handleUploadClose"
    />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import MaterialUpload from '@/components/common/MaterialUpload.vue';
import type { MaterialUploadResponse } from '@/types/material';

interface Props {
  disabled?: boolean;
}

interface Emits {
  (e: 'upload-success', data: MaterialUploadResponse): void;
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
});

const emit = defineEmits<Emits>();

const isUploadModalVisible = ref(false);

function handleCardClick(): void {
  if (props.disabled) {
    return;
  }
  isUploadModalVisible.value = true;
}

function handleUploadSuccess(data: MaterialUploadResponse): void {
  isUploadModalVisible.value = false;
  emit('upload-success', data);
}

function handleUploadClose(): void {
  isUploadModalVisible.value = false;
}

defineExpose({
  open: () => {
    isUploadModalVisible.value = true;
  },
  close: () => {
    isUploadModalVisible.value = false;
  },
  isUploadModalVisible,
});
</script>

<style lang="scss" scoped>
@import './QuickUploadBar.scss';
</style>
