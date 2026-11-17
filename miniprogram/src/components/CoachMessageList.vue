<template>
  <view class="chat-scroll-wrap">
    <scroll-view
      scroll-y
      :scroll-into-view="scrollTargetId"
      scroll-with-animation
      class="chat-body"
    >
      <view class="chat-inner">
        <view v-if="messages.length === 0 && !isThinking" class="empty-coach">
          <text class="empty-coach-title">可以这样向助教提问</text>
          <view v-if="quickPrompts?.length" class="quick-prompts">
            <text
              v-for="chip in quickPrompts"
              :key="chip"
              class="quick-chip"
              @tap="emit('quick-ask', chip)"
            >
              {{ chip }}
            </text>
          </view>
        </view>

        <view v-for="msg in messages" :key="msg.id" :class="['msg-row', `msg-${msg.role}`]">
          <view :class="['msg-bubble', { 'msg-bubble-error': msg.error }]">
            <text v-if="msg.role === 'user'" class="msg-text">{{ msg.content }}</text>
            <RichContent v-else :content="msg.content" compact />

            <view v-if="msg.prompt" class="next-prompt-box">
              <text class="next-prompt-label">启发延伸</text>
              <RichContent :content="msg.prompt" compact muted />
            </view>

            <view v-if="msg.role === 'assistant' && !msg.error" class="msg-actions">
              <text class="copy-btn" @tap="copyContent(msg.content)">复制</text>
            </view>
            <view v-if="msg.error" class="error-actions">
              <text class="retry-btn" @tap="emit('retry', msg)">点击重试</text>
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
              <text class="sources-title">参考讲义 ({{ msg.sources.length }})</text>
              <view v-for="source in msg.sources" :key="source.snippet_id" class="source-item">
                <text class="source-link" @tap="emit('open-source', source.material_id)">
                  {{ source.chapter_title || '打开来源讲义' }} ->
                </text>
                <text class="source-excerpt">{{ source.excerpt }}</text>
              </view>
            </view>
          </view>
        </view>

        <view v-if="isThinking" class="thinking-row">
          <text class="thinking-text">助教正在组织思路...</text>
        </view>
        <view :id="bottomAnchorId" class="bottom-anchor" />
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import RichContent from './RichContent.vue'
import type { CoachMessage } from '@/composables/useCoachChat'

defineOptions({ options: { virtualHost: true } })

const props = defineProps<{
  messages: CoachMessage[]
  isThinking: boolean
  quickPrompts?: string[]
}>()

const emit = defineEmits<{
  (e: 'select-suggestion', text: string): void
  (e: 'quick-ask', text: string): void
  (e: 'open-source', materialId: string): void
  (e: 'retry', msg: CoachMessage): void
}>()

const bottomAnchorId = 'coach-bottom-anchor'
const scrollTargetId = ref('')

watch(
  () => [props.messages.length, props.isThinking],
  async () => {
    scrollTargetId.value = ''
    await nextTick()
    scrollTargetId.value = bottomAnchorId
  },
  { immediate: true },
)

const copyContent = (content: string) => {
  if (!content) return
  uni.setClipboardData({
    data: content,
    success: () => uni.showToast({ title: '已复制解析', icon: 'success' }),
    fail: () => uni.showToast({ title: '复制失败', icon: 'none' }),
  })
}
</script>

<style lang="scss" scoped>
.chat-scroll-wrap {
  flex: 1; height: 0; min-height: 0; width: 100%; overflow: hidden; display: flex; flex-direction: column;
}
.chat-body { height: 100%; width: 100%; box-sizing: border-box; }
.chat-inner { padding: 24rpx 28rpx; width: 100%; box-sizing: border-box; }
.empty-coach { padding: 20rpx 4rpx 28rpx; }
.empty-coach-title { display: block; font-size: 24rpx; color: var(--color-ink-subtle); margin-bottom: 16rpx; }
.quick-prompts { display: flex; flex-wrap: wrap; gap: 12rpx; }
.quick-chip {
  font-size: 24rpx; color: var(--color-academic-blue); background: var(--color-blue-bg);
  border: 1px solid var(--color-blue-border); padding: 10rpx 18rpx; border-radius: 999rpx;
}
.msg-row { display: flex; width: 100%; margin-bottom: 20rpx; }
.msg-user { justify-content: flex-end; }
.msg-assistant { justify-content: flex-start; }
.msg-bubble {
  max-width: 86%; padding: 16rpx 20rpx; border-radius: 16rpx; line-height: 1.5;
  word-break: break-word; overflow-wrap: anywhere; box-sizing: border-box;
}
.msg-user .msg-bubble {
  background: var(--color-academic-blue); color: var(--color-ink-on-primary); border-bottom-right-radius: 4rpx;
}
.msg-assistant .msg-bubble {
  background: var(--color-surface-muted); color: var(--color-ink-primary); border-bottom-left-radius: 4rpx;
}
.msg-bubble-error { background: var(--color-danger-bg) !important; border: 1px solid var(--color-danger-border); }
.msg-text { font-size: 25rpx; white-space: pre-wrap; word-break: break-word; }
.next-prompt-box { margin-top: 14rpx; padding-top: 12rpx; border-top: 1px dashed var(--color-border-strong); }
.next-prompt-label { font-size: 22rpx; font-weight: 600; color: var(--color-warning-strong); display: block; margin-bottom: 4rpx; }
.msg-actions, .error-actions { display: flex; justify-content: flex-end; margin-top: 10rpx; }
.copy-btn {
  font-size: 22rpx; color: var(--color-ink-subtle); background: var(--color-bg-card);
  border: 1px solid var(--color-paper-border); padding: 4rpx 14rpx; border-radius: 999rpx;
}
.retry-btn {
  font-size: 22rpx; font-weight: 600; color: var(--color-danger); background: var(--color-bg-card);
  border: 1px solid var(--color-danger-border); padding: 6rpx 16rpx; border-radius: 999rpx;
}
.thinking-row { padding: 12rpx 0; }
.thinking-text { font-size: 24rpx; color: var(--color-ink-muted); font-style: italic; }
.suggestions-list, .sources-list { display: flex; flex-direction: column; gap: 10rpx; margin-top: 14rpx; }
.suggestion-item {
  color: var(--color-teal-accent); font-size: 23rpx; padding: 10rpx 14rpx;
  background: var(--color-teal-bg); border-radius: 8rpx;
}
.sources-title, .source-link { color: var(--color-teal-dark); font-size: 22rpx; font-weight: 600; }
.source-excerpt { display: block; color: var(--color-ink-secondary); font-size: 22rpx; margin-top: 4rpx; }
.bottom-anchor { height: 8rpx; width: 100%; }
</style>
