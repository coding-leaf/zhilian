<template>
  <view v-if="visible" class="modal-overlay">
    <!-- 关闭热区独立成元素：@tap.self 在小程序端被编译器丢弃，绑在容器上会导致点内容（含输入框）即关闭 -->
    <view class="modal-backdrop" @tap="close" />
    <view class="modal-content paper-card">
      <view class="modal-header">
        <text class="modal-title">{{ renaming ? '重命名课程' : '新建课程文件夹' }}</text>
        <text class="modal-close" @tap="close">关闭</text>
      </view>
      <view class="modal-body">
        <input
          v-model="draftName"
          class="form-input"
          :maxlength="30"
          :placeholder="renaming?.name || '例如：概率论与数理统计、操作系统'"
        />
      </view>
      <view class="modal-footer">
        <button class="modal-cancel-btn" @tap="close">取消</button>
        <button
          class="paper-btn-primary modal-confirm-btn"
          :loading="submitting"
          @tap="emit('submit', draftName)"
        >
          {{ renaming ? '保存' : '创建' }}
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  renaming: { id: string; name: string } | null
  initialName: string
  submitting: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'submit', name: string): void
}>()

const draftName = ref('')

watch(
  () => [props.visible, props.initialName],
  () => {
    draftName.value = props.initialName
  },
)

const close = () => {
  emit('update:visible', false)
}
</script>

<style lang="scss" scoped>
@import '../../../styles/modal.scss';
</style>
