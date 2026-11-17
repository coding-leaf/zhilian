<template>
  <view v-if="visible" class="sheet-overlay">
    <!-- 关闭热区独立成元素：@tap.self 在小程序端被编译器丢弃，绑在容器上会导致点内容（含输入框）即关闭 -->
    <view class="modal-backdrop" @tap="closeDrawer" />
    <view class="sheet-panel coach-drawer-sheet">
      <view class="drawer-header">
        <view class="header-left">
          <view class="coach-avatar">
            <text class="coach-avatar-text">AI</text>
          </view>
          <view class="coach-titles">
            <text class="coach-name">AI 智能助教</text>
            <text class="coach-desc">{{ title || '深度解析与启发式答疑' }}</text>
          </view>
        </view>
        <view class="close-btn" @tap="closeDrawer">
          <text class="close-icon">关闭</text>
        </view>
      </view>

      <CoachMessageList
        :context-text="contextText"
        :messages="messageList"
        :is-thinking="isThinking"
        @select-suggestion="setInputQuery"
        @open-source="openSource"
      />

      <view class="drawer-footer">
        <input
          v-model="inputQuery"
          class="chat-input"
          placeholder="向助教追问（如：为何这道题考点是...）"
          :disabled="isThinking"
          confirm-type="send"
          @confirm="sendMessage"
        />
        <button
          class="paper-btn-primary send-btn"
          :loading="isThinking"
          :disabled="!inputQuery.trim() || isThinking"
          @tap="sendMessage"
        >
          发送
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import CoachMessageList from './CoachMessageList.vue'
import { useCoachChat } from '@/composables/useCoachChat'

const props = defineProps<{
  visible: boolean
  title?: string
  questionId?: string
  contextText?: string
  userAnswer?: string
  gradingPoints?: string[]
  folderId?: string
  materialId?: string
  knowledgePointId?: string
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
}>()

const {
  inputQuery,
  isThinking,
  messageList,
  setInputQuery,
  sendMessage,
} = useCoachChat(() => ({
  questionId: props.questionId,
  userAnswer: props.userAnswer,
  gradingPoints: props.gradingPoints,
  folderId: props.folderId,
  materialId: props.materialId,
  knowledgePointId: props.knowledgePointId,
}))

const closeDrawer = () => {
  emit('update:visible', false)
}

const openSource = (id: string) => {
  uni.navigateTo({
    url: `/subpackages/material/pages/course/index?id=${id}`,
    fail: () => uni.showToast({ title: '打开来源讲义失败', icon: 'none' }),
  })
}
</script>

<style lang="scss" scoped>
@import '../styles/modal.scss';

.coach-drawer-sheet {
  height: 75vh;
  box-shadow: 0 -8rpx 32rpx rgba(0, 0, 0, 0.08);
}

.drawer-header {
  padding: 28rpx 32rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--color-surface-muted);
}

.header-left {
  display: flex;
  align-items: center;
}

.coach-avatar {
  width: 56rpx;
  height: 56rpx;
  border-radius: 28rpx;
  background: var(--color-blue-bg);
  border: 1px solid var(--color-blue-border);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 16rpx;
}

.coach-avatar-text {
  font-size: 22rpx;
  font-weight: 700;
  color: var(--color-academic-blue);
}

.coach-name {
  font-size: 30rpx;
  font-weight: 700;
  color: var(--color-ink-primary);
  display: block;
}

.coach-desc {
  font-size: 22rpx;
  color: var(--color-ink-subtle);
}

.close-btn {
  padding: 6rpx 18rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 24rpx;
  background: var(--color-surface-muted);
}

.close-icon {
  font-size: 22rpx;
  color: var(--color-ink-subtle);
}

.drawer-footer {
  padding: 20rpx 32rpx calc(20rpx + env(safe-area-inset-bottom));
  display: flex;
  gap: 16rpx;
  border-top: 1px solid var(--color-surface-muted);
  background: var(--color-paper-card);
}

.chat-input {
  flex: 1;
  height: 80rpx;
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-paper-border);
  border-radius: 12rpx;
  padding: 0 20rpx;
  font-size: 26rpx;
}

.send-btn {
  width: 140rpx;
  height: 80rpx;
  font-size: 26rpx;
}
</style>
