<template>
  <view v-if="visible" class="sheet-overlay coach-sheet-overlay">
    <!-- 关闭热区独立成元素：@tap.self 在小程序端会被编译丢弃 -->
    <view class="modal-backdrop" @tap="closeDrawer" />
    <view class="sheet-panel coach-drawer-sheet">
      <view class="sheet-grabber" />
      <view class="drawer-header">
        <view class="header-left">
          <view class="coach-avatar"><text class="coach-avatar-text">AI</text></view>
          <view class="coach-titles">
            <text class="coach-name">AI 智能助教</text>
            <text class="coach-desc">{{ title || '深度解析与启发式答疑' }}</text>
          </view>
        </view>
        <view class="header-actions">
          <view v-if="messageList.length > 0" class="header-pill" @tap="clearCurrentSession">
            <text class="header-pill-text">清空</text>
          </view>
          <view class="header-pill" @tap="closeDrawer"><text class="header-pill-text">关闭</text></view>
        </view>
      </view>

      <view v-if="contextText" class="context-bar" @tap="toggleContextExpanded">
        <text class="context-tag">当前语境</text>
        <text :class="['context-text', { expanded: contextExpanded }]">{{ contextText }}</text>
        <text class="context-toggle">{{ contextExpanded ? '收起' : '展开' }}</text>
      </view>

      <CoachMessageList
        :messages="messageList"
        :is-thinking="isThinking"
        :quick-prompts="quickPrompts"
        @select-suggestion="setInputQuery"
        @quick-ask="handleQuickAsk"
        @open-source="openSource"
        @retry="retryMessage"
      />

      <view class="drawer-footer">
        <textarea
          v-model="inputQuery"
          class="chat-textarea"
          placeholder="向助教追问，支持多行输入..."
          :disabled="isThinking"
          :fixed="true"
          confirm-type="send"
          auto-height
          :maxlength="500"
          :cursor-spacing="24"
          :adjust-position="true"
          :show-confirm-bar="false"
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
import { ref, watch } from 'vue'
import CoachMessageList from './CoachMessageList.vue'
import { useCoachChat } from '@/composables/useCoachChat'
import { safeNavigateTo } from '@/utils/navigation'

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

const emit = defineEmits<{ (e: 'update:visible', val: boolean): void }>()
const contextExpanded = ref(false)

const {
  sessionKey,
  inputQuery,
  isThinking,
  messageList,
  quickPrompts,
  setInputQuery,
  clearCurrentSession,
  sendMessage,
  retryMessage,
} = useCoachChat(() => ({
  questionId: props.questionId,
  userAnswer: props.userAnswer,
  gradingPoints: props.gradingPoints,
  folderId: props.folderId,
  materialId: props.materialId,
  knowledgePointId: props.knowledgePointId,
}))

watch(sessionKey, () => {
  contextExpanded.value = false
})

const toggleContextExpanded = () => {
  contextExpanded.value = !contextExpanded.value
}
const handleQuickAsk = (text: string) => {
  void sendMessage(text)
}
const closeDrawer = () => {
  emit('update:visible', false)
}
const openSource = (id: string) => {
  safeNavigateTo(`/subpackages/material/pages/course/index?id=${id}`, {
    failMessage: '打开来源讲义失败',
  })
}
</script>

<style lang="scss" scoped>
@import '../styles/modal.scss';

.coach-sheet-overlay { z-index: var(--z-coach); }
.coach-drawer-sheet { height: 78vh; max-height: 82vh; display: flex; flex-direction: column; }
.sheet-grabber {
  width: 68rpx; height: 8rpx; border-radius: 999rpx;
  background: var(--color-border-strong); margin: 12rpx auto 2rpx; flex-shrink: 0;
}
.drawer-header {
  padding: 16rpx 28rpx 20rpx; display: flex; justify-content: space-between;
  align-items: center; border-bottom: 1px solid var(--color-surface-muted); flex-shrink: 0;
}
.header-left { display: flex; align-items: center; flex: 1; min-width: 0; margin-right: 16rpx; }
.coach-avatar {
  width: 52rpx; height: 52rpx; border-radius: 26rpx; background: var(--color-blue-bg);
  border: 1px solid var(--color-blue-border); display: flex; align-items: center;
  justify-content: center; margin-right: 16rpx; flex-shrink: 0;
}
.coach-avatar-text { font-size: 22rpx; font-weight: 700; color: var(--color-academic-blue); }
.coach-titles { flex: 1; min-width: 0; }
.coach-name { font-size: 30rpx; font-weight: 700; color: var(--color-ink-primary); display: block; }
.coach-desc {
  font-size: 22rpx; color: var(--color-ink-subtle); display: block;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.header-actions { display: flex; align-items: center; gap: 10rpx; flex-shrink: 0; }
.header-pill { padding: 6rpx 16rpx; border-radius: 24rpx; background: var(--color-surface-muted); }
.header-pill-text { font-size: 22rpx; color: var(--color-ink-subtle); }
.context-bar {
  display: flex; align-items: flex-start; gap: 10rpx; padding: 12rpx 28rpx;
  background: var(--color-surface-slate); border-bottom: 1px solid var(--color-paper-border); flex-shrink: 0;
}
.context-tag {
  font-size: 20rpx; font-weight: 600; color: var(--color-sky); background: var(--color-sky-bg);
  padding: 2rpx 10rpx; border-radius: 6rpx; flex-shrink: 0;
}
.context-text {
  flex: 1; min-width: 0; font-size: 22rpx; color: var(--color-ink-slate-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.context-text.expanded { white-space: normal; line-height: 1.5; }
.context-toggle { font-size: 22rpx; color: var(--color-academic-blue); flex-shrink: 0; }
.drawer-footer {
  padding: 16rpx 28rpx calc(16rpx + env(safe-area-inset-bottom));
  display: flex; align-items: flex-end; gap: 16rpx;
  border-top: 1px solid var(--color-surface-muted); background: var(--color-bg-card); flex-shrink: 0;
}
.chat-textarea {
  flex: 1; min-height: 76rpx; max-height: 180rpx; background: var(--color-surface-subtle);
  border: 1px solid var(--color-paper-border); border-radius: 12rpx;
  padding: 18rpx 20rpx; font-size: 26rpx; line-height: 1.45; box-sizing: border-box;
}
.send-btn {
  width: 132rpx; height: 76rpx; font-size: 26rpx; flex-shrink: 0;
  margin: 0; line-height: 1.4;
  &::after { border: none; }
}
</style>
