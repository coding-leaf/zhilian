<template>
  <view v-if="visible" class="coach-drawer-overlay" @tap.self="closeDrawer">
    <view class="coach-drawer-sheet">
      <!-- 头部 -->
      <view class="drawer-header">
        <view class="header-left">
          <text class="coach-avatar">🤖</text>
          <view class="coach-titles">
            <text class="coach-name">AI 智能助教</text>
            <text class="coach-desc">{{ title || '深度解析与启发式答疑' }}</text>
          </view>
        </view>
        <view class="close-btn" @tap="closeDrawer">
          <text class="close-icon">✕</text>
        </view>
      </view>

      <!-- 消息与启发式内容区 -->
      <scroll-view scroll-y class="chat-body">
        <!-- 题目或知识点背景卡片 -->
        <view v-if="contextText" class="context-card">
          <text class="context-tag">📌 答疑上下文</text>
          <text class="context-content">{{ contextText }}</text>
        </view>

        <!-- 对话流 -->
        <view v-for="(msg, idx) in messageList" :key="idx" :class="['msg-row', `msg-${msg.role}`]">
          <view class="msg-bubble">
            <text class="msg-text">{{ msg.content }}</text>
            <view v-if="msg.prompt" class="next-prompt-box">
              <text class="next-prompt-label">💡 启发延伸：</text>
              <text class="next-prompt-text">{{ msg.prompt }}</text>
            </view>
            <view v-if="msg.suggestions?.length" class="suggestions-list">
              <text
                v-for="suggestion in msg.suggestions"
                :key="suggestion"
                class="suggestion-item"
                @tap="inputQuery = suggestion"
              >
                {{ suggestion }}
              </text>
            </view>
            <view v-if="msg.sources?.length" class="sources-list">
              <text class="sources-title">参考资料</text>
              <view v-for="source in msg.sources" :key="source.snippet_id" class="source-item">
                <text class="source-link" @tap="openSource(source.material_id)">
                  {{ source.chapter_title || '打开来源讲义' }} ↗
                </text>
                <text class="source-excerpt">{{ source.excerpt }}</text>
              </view>
            </view>
          </view>
        </view>

        <view v-if="isThinking" class="thinking-row">
          <text class="thinking-text">助教正在组织思路...</text>
        </view>
      </scroll-view>

      <!-- 底部输入框 -->
      <view class="drawer-footer">
        <input
          v-model="inputQuery"
          class="chat-input"
          placeholder="向助教追问（如：为何这道题考点是...）"
          :disabled="isThinking"
          confirm-type="send"
          @confirm="handleSend"
        />
        <button
          class="paper-btn-primary send-btn"
          :loading="isThinking"
          :disabled="!inputQuery.trim() || isThinking"
          @tap="handleSend"
        >
          发送
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { apiAskQuestionCoach, apiAskScopedCoach } from '@/api'
import type { CoachSource } from '@/types'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  prompt?: string
  suggestions?: string[]
  sources?: CoachSource[]
}

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

const inputQuery = ref('')
const isThinking = ref(false)
const messageList = ref<ChatMessage[]>([])

const closeDrawer = () => {
  emit('update:visible', false)
}

const handleSend = async () => {
  const q = inputQuery.value.trim()
  if (!q || isThinking.value) return

  messageList.value.push({
    role: 'user',
    content: q,
  })
  inputQuery.value = ''
  isThinking.value = true

  try {
    if (props.questionId) {
      const res = await apiAskQuestionCoach(
        props.questionId,
        q,
        props.userAnswer,
        props.gradingPoints
      )
      messageList.value.push({ role: 'assistant', content: res.reply, suggestions: res.suggestions })
    } else {
      if (!props.folderId && !props.materialId && !props.knowledgePointId) {
        messageList.value.push({ role: 'assistant', content: '请先选择一门课程或打开一份讲义，再向助教提问。' })
        return
      }
      const response = await apiAskScopedCoach({
        ...(props.folderId ? { folder_id: props.folderId } : {}),
        ...(props.materialId ? { material_id: props.materialId } : {}),
        ...(props.knowledgePointId ? { knowledge_point_id: props.knowledgePointId } : {}),
        user_prompt: q,
      })
      messageList.value.push({
        role: 'assistant',
        content: response.reply,
        suggestions: response.suggestions,
        sources: response.sources,
      })
    }
  } catch (err: any) {
    messageList.value.push({
      role: 'assistant',
      content: '助教网络开小差了，请稍后再试。',
    })
  } finally {
    isThinking.value = false
  }
}

const openSource = (id: string) => {
  uni.navigateTo({
    url: `/subpackages/material/pages/course/index?id=${id}`,
    fail: () => uni.showToast({ title: '打开来源讲义失败', icon: 'none' }),
  })
}
</script>

<style scoped>
.coach-drawer-overlay {
  position: fixed;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(2px);
  z-index: 999;
  display: flex;
  justify-content: flex-end;
  flex-direction: column;
}

.coach-drawer-sheet {
  background: #ffffff;
  border-top-left-radius: 28rpx;
  border-top-right-radius: 28rpx;
  height: 75vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 -8rpx 32rpx rgba(0, 0, 0, 0.08);
}

.drawer-header {
  padding: 28rpx 32rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f5f5f4;
}

.header-left {
  display: flex;
  align-items: center;
}

.coach-avatar {
  font-size: 40rpx;
  margin-right: 16rpx;
}

.coach-name {
  font-size: 30rpx;
  font-weight: 700;
  color: #1c1917;
  display: block;
}

.coach-desc {
  font-size: 22rpx;
  color: #78716c;
}

.close-btn {
  width: 48rpx;
  height: 48rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 24rpx;
  background: #f5f5f4;
}

.close-icon {
  font-size: 24rpx;
  color: #78716c;
}

.chat-body {
  flex: 1;
  padding: 24rpx 32rpx;
  overflow-y: auto;
}

.context-card {
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
  margin-bottom: 24rpx;
}

.context-tag {
  font-size: 20rpx;
  color: #0284c7;
  font-weight: 600;
  display: block;
  margin-bottom: 4rpx;
}

.context-content {
  font-size: 24rpx;
  color: #475569;
  line-height: 1.5;
}

.msg-row {
  display: flex;
  margin-bottom: 20rpx;
}

.msg-user {
  justify-content: flex-end;
}

.msg-assistant {
  justify-content: flex-start;
}

.msg-bubble {
  max-width: 82%;
  padding: 20rpx 24rpx;
  border-radius: 16rpx;
  line-height: 1.5;
}

.msg-user .msg-bubble {
  background: #1e3a8a;
  color: #ffffff;
  border-bottom-right-radius: 4rpx;
}

.msg-assistant .msg-bubble {
  background: #f5f5f4;
  color: #1c1917;
  border-bottom-left-radius: 4rpx;
}

.msg-text {
  font-size: 28rpx;
}

.next-prompt-box {
  margin-top: 14rpx;
  padding-top: 12rpx;
  border-top: 1px dashed #d6d3d1;
}

.next-prompt-label {
  font-size: 22rpx;
  font-weight: 600;
  color: #b45309;
  display: block;
}

.next-prompt-text {
  font-size: 24rpx;
  color: #78350f;
}

.thinking-row {
  padding: 12rpx 0;
}

.thinking-text {
  font-size: 24rpx;
  color: #a8a29e;
  font-style: italic;
}

.suggestions-list,
.sources-list {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
  margin-top: 16rpx;
}

.suggestion-item {
  color: #176b62;
  font-size: 23rpx;
  padding: 10rpx 12rpx;
  background: #eef7f4;
  border-radius: 8rpx;
}

.sources-title,
.source-link {
  color: #245c51;
  font-size: 22rpx;
  font-weight: 600;
}

.source-excerpt {
  display: block;
  color: #57534e;
  font-size: 22rpx;
  margin-top: 6rpx;
}

.drawer-footer {
  padding: 20rpx 32rpx;
  display: flex;
  gap: 16rpx;
  border-top: 1px solid #f5f5f4;
  background: #ffffff;
}

.chat-input {
  flex: 1;
  height: 80rpx;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
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
