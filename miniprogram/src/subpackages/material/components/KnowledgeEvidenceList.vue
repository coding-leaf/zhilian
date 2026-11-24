<template>
  <view class="point-section">
    <view class="snippet-toggle-row" @tap="expanded = !expanded">
      <text class="snippet-toggle-title">
        {{ loading ? '正在检索教材原文依据...' : `查看教材原文依据 (${snippets.length}处)` }}
      </text>
      <text class="snippet-toggle-action">
        {{ expanded ? '收起' : '展开' }}
      </text>
    </view>

    <view v-if="expanded" class="snippets-list">
      <view v-if="loading" class="empty-snippets">
        <text class="empty-snippets-text">正在检索教材溯源切片...</text>
      </view>
      <template v-else-if="items.length > 0">
        <view
          v-for="item in items"
          :key="item.key"
          class="snippet-item"
        >
          <view class="snip-meta">
            <text class="snip-page">{{ item.pageLabel }}</text>
            <text v-if="item.chapterTitle" class="snip-chapter">{{ item.chapterTitle }}</text>
          </view>
          <view v-if="item.garbled" class="garbled-hint-box">
            <text class="garbled-hint-text">
              检测到旧版讲义公式编码异常，点击讲义页「重新解析」即可修复
            </text>
          </view>
          <template v-else>
            <RichContent :content="item.displayText" compact muted />
            <view
              v-if="item.truncated"
              class="snip-expand-row"
              @tap="toggleItem(item.key)"
            >
              <text class="snip-expand-btn">{{ item.itemExpanded ? '收起' : '展开全文' }}</text>
            </view>
          </template>
        </view>
      </template>
      <view v-else class="empty-snippets">
        <text class="empty-snippets-text">
          {{
            loadFailed
              ? '原文切片加载失败，请稍后重试。'
              : '当前暂无高质量教材原文依据，建议点击讲义页「重新解析」升级'
          }}
        </text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import RichContent from '@/components/RichContent.vue'
import { isGarbledSnippetText } from '@/utils/richText'
import type { KnowledgeSnippet } from '@/types'
import { formatSnippetPageRange, trimSnippetExcerpt } from '../utils/courseStudy'

defineOptions({
  options: {
    virtualHost: true,
    styleIsolation: 'apply-shared',
  },
})

const props = defineProps<{
  snippets: KnowledgeSnippet[]
  loading: boolean
  loadFailed: boolean
  resetKey: string
}>()

const expanded = ref(false)
const expandedItemKeys = ref<Record<string, boolean>>({})

watch(
  () => props.resetKey,
  () => {
    expanded.value = false
    expandedItemKeys.value = {}
  },
)

const items = computed(() =>
  props.snippets.map((snip, idx) => {
    const key = snip.id || `snip-${idx}`
    const garbled = isGarbledSnippetText(snip.content)
    const itemExpanded = Boolean(expandedItemKeys.value[key])
    const excerpt = trimSnippetExcerpt(snip.content, 240)
    return {
      key,
      pageLabel: formatSnippetPageRange(snip.page_index, snip.pageEnd),
      chapterTitle: snip.chapter_title || null,
      garbled,
      truncated: excerpt.truncated,
      itemExpanded,
      displayText: itemExpanded ? snip.content : excerpt.text,
    }
  }),
)

const toggleItem = (key: string) => {
  expandedItemKeys.value = {
    ...expandedItemKeys.value,
    [key]: !expandedItemKeys.value[key],
  }
}
</script>

<style lang="scss" scoped>
@import '../course.scss';

.empty-snippets {
  padding: 12rpx 4rpx;
}

.empty-snippets-text {
  font-size: 24rpx;
  color: var(--color-ink-muted);
  line-height: 1.5;
}

.snip-expand-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 8rpx;
}

.snip-expand-btn {
  font-size: 22rpx;
  font-weight: 600;
  color: var(--color-academic-blue);
  padding: 4rpx 8rpx;
}
</style>
