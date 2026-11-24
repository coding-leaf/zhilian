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
                <text class="sec-label">核心定义与直觉</text>
                <view class="sec-card">
                  <RichContent :content="coreSummary" />
                </view>
              </view>

              <view v-if="keyTakeaways.length" class="point-section">
                <text class="sec-label">关键结论与要点</text>
                <view class="sec-card bullet-list">
                  <view v-for="(item, tIdx) in keyTakeaways" :key="tIdx" class="bullet-row">
                    <view class="bullet-dot" />
                    <view class="bullet-body">
                      <RichContent :content="item" compact />
                    </view>
                  </view>
                </view>
              </view>

              <view v-if="keyFormulas.length" class="point-section">
                <text class="sec-label">核心公式与符号</text>
                <view v-for="(formula, fIdx) in keyFormulas" :key="fIdx" class="formula-card">
                  <RichContent :content="formula" />
                </view>
              </view>

              <view v-if="derivationSteps.length" class="point-section">
                <text class="sec-label">推导 / 解题步骤</text>
                <view class="step-card">
                  <view v-for="(step, dIdx) in derivationSteps" :key="dIdx" class="step-row">
                    <text class="step-index">{{ dIdx + 1 }}</text>
                    <view class="step-body">
                      <RichContent :content="step" compact />
                    </view>
                  </view>
                </view>
              </view>

              <view v-if="boundaryNotes.length" class="point-section">
                <text class="sec-label">适用条件与易错边界</text>
                <view class="boundary-card bullet-list">
                  <view v-for="(note, bIdx) in boundaryNotes" :key="bIdx" class="bullet-row">
                    <view class="bullet-dot bullet-dot-amber" />
                    <view class="bullet-body">
                      <RichContent :content="note" compact />
                    </view>
                  </view>
                </view>
              </view>

              <view v-if="commonMistakes.length" class="point-section">
                <view class="mistake-head">
                  <text class="sec-label mistake-title">高频易错点</text>
                  <text class="mistake-tag">易错辨析</text>
                </view>
                <view class="mistake-card bullet-list">
                  <view v-for="(mistake, mIdx) in commonMistakes" :key="mIdx" class="bullet-row">
                    <view class="bullet-dot bullet-dot-danger" />
                    <view class="bullet-body">
                      <RichContent :content="mistake" compact />
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

            <KnowledgeEvidenceList
              :snippets="snippets"
              :loading="loadingSnippets"
              :load-failed="snippetLoadFailed"
              :reset-key="evidenceResetKey"
            />
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
import { computed } from 'vue'
import RichContent from '@/components/RichContent.vue'
import type { KnowledgePointDetail, KnowledgeSnippet, KnowledgeTreeNode } from '@/types'
import { hasStructuredContent, resolveMasteryBadge, type MasteryEntry } from '../utils/courseStudy'
import KnowledgeEvidenceList from './KnowledgeEvidenceList.vue'

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
const keyTakeaways = computed(() => structured.value?.key_takeaways ?? [])
const keyFormulas = computed(() => structured.value?.key_formulas ?? [])
const derivationSteps = computed(() => structured.value?.derivation_steps ?? [])
const boundaryNotes = computed(() => structured.value?.boundary_notes ?? [])
const commonMistakes = computed(() => structured.value?.common_mistakes ?? [])
const fallbackDescription = computed(
  () => activePoint.value?.description || props.point?.description || '该知识点暂无定义说明。',
)
const masteryBadge = computed(() => resolveMasteryBadge(props.masteryEntry))
const evidenceResetKey = computed(() => `${props.visible ? '1' : '0'}-${props.point?.id ?? ''}`)

const close = () => {
  emit('update:visible', false)
}
</script>

<style lang="scss" scoped>
@import '../../../styles/modal.scss';
@import '../course.scss';

.step-card {
  background: var(--color-teal-bg);
  border: 1px solid var(--color-paper-border);
  border-radius: 12rpx;
  padding: 18rpx 22rpx;
  display: flex;
  flex-direction: column;
  gap: 14rpx;
}

.step-row {
  display: flex;
  align-items: flex-start;
  gap: 14rpx;
}

.step-index {
  width: 36rpx;
  height: 36rpx;
  border-radius: 999rpx;
  background: var(--color-academic-teal);
  color: var(--color-ink-on-primary);
  font-size: 21rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 4rpx;
  flex-shrink: 0;
}

.step-body {
  flex: 1;
  min-width: 0;
}

.mistake-head {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 12rpx;
}

.mistake-title {
  margin-bottom: 0;
  color: var(--color-danger-strong);
}

.mistake-tag {
  font-size: 20rpx;
  font-weight: 600;
  color: var(--color-wrong);
  background: var(--color-danger-bg-soft);
  border: 1px solid var(--color-danger-border);
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
}

.mistake-card {
  background: var(--color-danger-bg);
  border: 1px solid var(--color-danger-border);
  border-radius: 12rpx;
  padding: 18rpx 22rpx;
}

.bullet-dot-danger {
  background: var(--color-wrong);
}
</style>
