<template>
  <view :class="['rich-content', { compact, muted }]">
    <rich-text :nodes="nodes" user-select />
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { parseRichContent } from '@/utils/richText'

defineOptions({
  options: {
    virtualHost: true,
  },
})

const props = defineProps<{
  content?: string | null
  compact?: boolean
  muted?: boolean
}>()

const nodes = computed(() => parseRichContent(props.content))
</script>

<style scoped>
.rich-content {
  width: 100%;
  font-size: 28rpx;
  line-height: 1.65;
  color: var(--color-ink-primary);
  word-break: break-word;
  overflow-wrap: anywhere;
}

.rich-content.compact {
  font-size: 24rpx;
  line-height: 1.55;
}

.rich-content.muted {
  color: var(--color-ink-secondary);
}
</style>
