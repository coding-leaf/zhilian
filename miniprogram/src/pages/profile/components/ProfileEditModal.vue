<template>
  <view v-if="visible" class="modal-overlay">
    <!-- 关闭热区独立成元素：@tap.self 在小程序端被编译器丢弃，绑在容器上会导致点内容（含输入框）即关闭 -->
    <view class="modal-backdrop" @tap="close" />
    <view class="modal-content paper-card">
      <view class="modal-header">
        <text class="modal-title">编辑个人资料</text>
        <text class="modal-close" @tap="close">关闭</text>
      </view>
      <view class="modal-body">
        <view class="form-item">
          <text class="form-label">昵称</text>
          <input
            v-model="draftNickname"
            class="form-input"
            :maxlength="20"
            :cursor-spacing="24"
            placeholder="请输入新昵称"
          />
        </view>
        <view class="form-item">
          <text class="form-label">头像</text>
          <button
            class="avatar-select-btn"
            :loading="uploadingAvatar"
            :disabled="uploadingAvatar"
            @tap="emit('choose-avatar')"
          >
            选择图片
          </button>
        </view>
      </view>
      <view class="modal-footer">
        <button class="modal-cancel-btn" @tap="close">取消</button>
        <button
          class="paper-btn-primary modal-confirm-btn"
          :loading="saving"
          :disabled="saving"
          @tap="handleSave"
        >
          保存修改
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  initialNickname: string
  uploadingAvatar: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'choose-avatar'): void
  (e: 'save', nickname: string): void
}>()

const draftNickname = ref('')

watch(
  () => [props.visible, props.initialNickname],
  () => {
    draftNickname.value = props.initialNickname
  },
)

const close = () => {
  emit('update:visible', false)
}

const handleSave = () => {
  const trimmed = draftNickname.value.trim()
  if (!trimmed) {
    uni.showToast({ title: '昵称不能为空', icon: 'none' })
    return
  }
  emit('save', trimmed)
}
</script>

<style lang="scss" scoped>
@import '../../../styles/modal.scss';

.form-item {
  margin-bottom: 24rpx;
}

.form-label {
  display: block;
  font-size: 26rpx;
  color: var(--color-ink-secondary);
  font-weight: 500;
  margin-bottom: 12rpx;
}

.avatar-select-btn {
  height: 68rpx;
  line-height: 68rpx;
  margin: 0;
  padding: 0 20rpx;
  font-size: 24rpx;
  color: var(--color-teal-dark);
  background: var(--color-teal-bg);
  border-radius: 8rpx;

  &::after {
    border: none;
  }
}

.modal-cancel-btn,
.modal-confirm-btn {
  margin: 0;
  line-height: 1.4;

  &::after {
    border: none;
  }
}
</style>
