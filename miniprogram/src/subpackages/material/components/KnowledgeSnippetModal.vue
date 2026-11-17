<template>
  <view v-if="visible" class="sheet-overlay">
    <!-- 关闭热区独立成元素：@tap.self 在小程序端被编译器丢弃，绑在容器上会导致点内容即关闭 -->
    <view class="modal-backdrop" @tap="close" />
    <view class="sheet-panel study-sheet-panel paper-card">
      <view class="sheet-grabber" />
      <view class="study-sheet-header">
        <view class="sheet-title-box">
          <view class="sheet-title-row">
            <text class="sheet-title">{{ activePoint?.name || '考点详情' }}</text>
            <text :class="['mastery-pill', `mastery-${masteryBadge.tone}`]">
              {{ masteryBadge.text }}
            </text>
          </view>
          <text v-if="pointHierarchy" class="hierarchy-text">{{ pointHierarchy }}</text>
        </view>
        <text class="modal-close" @tap="close">关闭</text>
      </view>

      <view class="sheet-scroll-wrap">
        <scroll-view scroll-y class="sheet-body">
          <view class="sheet-inner">
            <template v-if="showStructured">
              <view v-if="coreSummary" class="point-section">
                <text class="sec-label">核心定义</text>
                <view class="sec-card">
                  <RichContent :content="coreSummary" />
                </view>
              </view>

              <view v-if="structured?.key_takeaways.length" class="point-section">
                <text class="sec-label">关键结论</text>
                <view class="sec-card bullet-list">
                  <view
                    v-for="(item, tIdx) in structured.key_takeaways"
                    :key="tIdx"
                    class="bullet-row"
                  >
                    <view class="bullet-dot" />
                    <view class="bullet-body">
                      <RichContent :content="item" compact />
                    </view>
                  </view>
                </view>
              </view>

              <view v-if="structured?.key_formulas.length" class="point-section">
                <text class="sec-label">核心公式与符号</text>
                <view
                  v-for="(formula, fIdx) in structured.key_formulas"
                  :key="fIdx"
                  class="formula-card"
                >
                  <RichContent :content="formula" />
                </view>
              </view>

              <view v-if="structured?.boundary_notes.length" class="point-section">
                <text class="sec-label">适用条件与易错边界</text>
                <view class="boundary-card bullet-list">
                  <view
                    v-for="(note, bIdx) in structured.boundary_notes"
                    :key="bIdx"
                    class="bullet-row"
                  >
                    <view class="bullet-dot bullet-dot-amber" />
                    <view class="bullet-body">
                      <RichContent :content="note" compact />
                    </view>
                  </view>
                </view>
              </view>
            </template>

            <view v-else class="point-section">
              <text class="sec-label">知识点定义与解析</text>
              <view class="sec-card">
                <RichContent :content="fallbackDescription" />
              </view>
            </view>

            <view class="point-section">
              <view class="snippet-toggle-row" @tap="snippetsExpanded = !snippetsExpanded">
                <text class="snippet-toggle-title">
                  {{ loadingSnippets ? '正在检索教材原文依据...' : `查看教材原文依据 (${snippets.length}处)` }}
                </text>
                <text class="snippet-toggle-action">
                  {{ snippetsExpanded ? '收起' : '展开' }}
                </text>
              </view>

              <view v-if="snippetsExpanded" class="snippets-list">
                <view v-if="loadingSnippets" class="empty-snippets">
                  <text class="empty-snippets-text">正在检索教材溯源切片...</text>
                </view>
                <template v-else-if="snippets.length > 0">
                  <view
                    v-for="(snip, sIdx) in snippets"
                    :key="snip.id || sIdx"
                    class="snippet-item"
                  >
                    <view class="snip-meta">
                      <text class="snip-page">第 {{ snip.page_index || 1 }} 页</text>
                      <text v-if="snip.chapter_title" class="snip-chapter">{{ snip.chapter_title }}</text>
                    </view>
                    <view v-if="isGarbled(snip.content)" class="garbled-hint-box">
                      <text class="garbled-hint-text">
                        检测到旧版讲义公式编码异常，点击右上角「重新解析」即可修复
                      </text>
                    </view>
                    <RichContent v-else :content="snip.content" compact muted />
                  </view>
                </template>
                <view v-else class="empty-snippets">
                  <text class="empty-snippets-text">
                    {{ snippetLoadFailed ? '原文切片加载失败，请稍后重试。' : '此知识点暂无可展示的原文切片。' }}
                  </text>
                </view>
              </view>
            </view>
          </view>
        </scroll-view>
      </view>

      <view class="sheet-footer">
        <button class="sheet-practice-btn" @tap="emit('practice')">
          针对此考点出题
        </button>
        <button class="paper-btn-primary ask-coach-btn" @tap="emit('ask-coach')">
          向 AI 助教追问
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import RichContent from '@/components/RichContent.vue'
import { isGarbledSnippetText } from '@/utils/richText'
import type { KnowledgePointDetail, KnowledgeSnippet, KnowledgeTreeNode } from '@/types'
import { hasStructuredContent, resolveMasteryBadge, type MasteryEntry } from '../utils/courseStudy'

const props = defineProps<{
  visible: boolean
  point: KnowledgeTreeNode | null
  pointDetail: KnowledgePointDetail | null
  pointHierarchy: string
  masteryEntry?: MasteryEntry | null
  snippets: KnowledgeSnippet[]
  loadingSnippets: boolean
  snippetLoadFailed: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'ask-coach'): void
  (e: 'practice'): void
}>()

const snippetsExpanded = ref(false)

watch(
  () => [props.visible, props.point?.id],
  () => {
    snippetsExpanded.value = false
  },
)

const activePoint = computed(() => {
  if (props.pointDetail && props.point && props.pointDetail.id === props.point.id) {
    return props.pointDetail
  }
  return props.point
})

const structured = computed(
  () => activePoint.value?.structured_content || props.point?.structured_content || null,
)
const showStructured = computed(() => hasStructuredContent(structured.value))
const coreSummary = computed(
  () =>
    structured.value?.core_summary?.trim()
    || activePoint.value?.description
    || props.point?.description
    || '',
)
const fallbackDescription = computed(
  () => activePoint.value?.description || props.point?.description || '该知识点暂无定义说明。',
)
const masteryBadge = computed(() => resolveMasteryBadge(props.masteryEntry))
const isGarbled = (content: string) => isGarbledSnippetText(content)

const close = () => {
  emit('update:visible', false)
}
</script>

<style lang="scss" scoped>
@import '../../../styles/modal.scss';
@import '../course.scss';

.empty-snippets { padding: 12rpx 4rpx; }
.empty-snippets-text { font-size: 24rpx; color: var(--color-ink-muted); }
</style>
