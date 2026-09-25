<template>
  <view class="snippet-drawer-mask" :class="{ visible }" @tap.self="handleClose">
    <view class="snippet-drawer-sheet" :class="{ visible }">
      <!-- 头部：标题与关闭按钮 -->
      <view class="drawer-header">
        <text class="drawer-title">原文溯源依据</text>
        <view class="close-btn" @tap="handleClose">
          <text>关闭</text>
        </view>
      </view>

      <!-- 元信息栏：章节名称与页码 -->
      <view v-if="hasMeta" class="snippet-meta-bar">
        <text v-if="chapterTitle" class="meta-tag">章节：{{ chapterTitle }}</text>
        <text v-if="pageIndex" class="meta-tag">第 {{ pageIndex }} 页</text>
      </view>

      <!-- 原文内容与安全切词高亮展示 -->
      <scroll-view scroll-y class="snippet-scroll-body">
        <view v-if="highlightParts.length > 0">
          <text
            v-for="(part, index) in highlightParts"
            :key="index"
            class="snippet-text"
            :class="{ 'highlighted-keyword': part.isHighlight }"
          >
            {{ part.text }}
          </text>
        </view>
        <view v-else class="empty-content">
          <text>暂无原文切片内容</text>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * OriginalSnippetDrawer.vue
 * Bottom drawer displaying original snippet content with safe keyword highlighting.
 * Completely immune to XSS: Strictly renders split text nodes without v-html.
 * Complies with docs/DESIGN.md & spec ZL-135.
 * Zero-Emoji Policy: No emoji allowed.
 */

import { computed } from 'vue';
import type { SnippetHighlightPart } from '@/types/report';
import { splitSnippetHighlights } from '../utils/reportFormat';

interface Props {
  visible: boolean;
  snippetContent?: string;
  chapterTitle?: string;
  pageIndex?: number;
  highlightKeywords?: string[];
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  snippetContent: '',
  chapterTitle: '',
  pageIndex: 0,
  highlightKeywords: () => [],
});

const emit = defineEmits<{
  (e: 'update:visible', visible: boolean): void;
  (e: 'close'): void;
}>();

const hasMeta = computed(() => {
  return Boolean(props.chapterTitle) || Boolean(props.pageIndex > 0);
});

const highlightParts = computed<SnippetHighlightPart[]>(() => {
  return splitSnippetHighlights(props.snippetContent, props.highlightKeywords);
});

function handleClose(): void {
  emit('update:visible', false);
  emit('close');
}
</script>

<style lang="scss" scoped>
@import './OriginalSnippetDrawer.scss';
</style>
