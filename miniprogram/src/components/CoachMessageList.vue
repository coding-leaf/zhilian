<template>
  <scroll-view scroll-y class="chat-body">
    <view v-if="contextText" class="context-card">
      <text class="context-tag">答疑上下文</text>
      <text class="context-content">{{ contextText }}</text>
    </view>

    <view v-for="(msg, idx) in messages" :key="idx" :class="['msg-row', `msg-${msg.role}`]">
      <view class="msg-bubble">
        <text class="msg-text">{{ msg.content }}</text>
        <view v-if="msg.prompt" class="next-prompt-box">
          <text class="next-prompt-label">启发延伸：</text>
          <text class="next-prompt-text">{{ msg.prompt }}</text>
        </view>
        <view v-if="msg.suggestions?.length" class="suggestions-list">
          <text
            v-for="suggestion in msg.suggestions"
            :key="suggestion"
            class="suggestion-item"
            @tap="emit('select-suggestion', suggestion)"
          >
            {{ suggestion }}
          </text>
        </view>
        <view v-if="msg.sources?.length" class="sources-list">
          <text class="sources-title">参考资料</text>
          <view v-for="source in msg.sources" :key="source.snippet_id" class="source-item">
            <text class="source-link" @tap="emit('open-source', source.material_id)">
              {{ source.chapter_title || '打开来源讲义' }} →
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
</template>

<script setup lang="ts">
import type { ChatMessage } from '@/composables/useCoachChat'

defineProps<{
  contextText?: string
  messages: ChatMessage[]
  isThinking: boolean
}>()

const emit = defineEmits<{
  (e: 'select-suggestion', text: string): void
  (e: 'open-source', materialId: string): void
}>()
</script>

<style lang="scss" scoped>
.chat-body {
  flex: 1;
  padding: 24rpx 32rpx;
  overflow-y: auto;
}

.context-card {
  background: var(--color-surface-slate);
  border: 1px dashed var(--color-border-slate);
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
  margin-bottom: 24rpx;
}

.context-tag {
  font-size: 20rpx;
  color: var(--color-sky);
  font-weight: 600;
  display: block;
  margin-bottom: 4rpx;
}

.context-content {
  font-size: 24rpx;
  color: var(--color-ink-slate-muted);
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
  background: var(--color-academic-blue);
  color: var(--color-ink-on-primary);
  border-bottom-right-radius: 4rpx;
}

.msg-assistant .msg-bubble {
  background: var(--color-surface-muted);
  color: var(--color-ink-primary);
  border-bottom-left-radius: 4rpx;
}

.msg-text {
  font-size: 28rpx;
}

.next-prompt-box {
  margin-top: 14rpx;
  padding-top: 12rpx;
  border-top: 1px dashed var(--color-border-strong);
}

.next-prompt-label {
  font-size: 22rpx;
  font-weight: 600;
  color: var(--color-warning-strong);
  display: block;
}

.next-prompt-text {
  font-size: 24rpx;
  color: var(--color-warning-dark);
}

.thinking-row {
  padding: 12rpx 0;
}

.thinking-text {
  font-size: 24rpx;
  color: var(--color-ink-muted);
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
  color: var(--color-teal-accent);
  font-size: 23rpx;
  padding: 10rpx 12rpx;
  background: var(--color-teal-bg);
  border-radius: 8rpx;
}

.sources-title,
.source-link {
  color: var(--color-teal-dark);
  font-size: 22rpx;
  font-weight: 600;
}

.source-excerpt {
  display: block;
  color: var(--color-ink-secondary);
  font-size: 22rpx;
  margin-top: 6rpx;
}
</style>
