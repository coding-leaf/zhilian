<template>
  <view class="paper-card question-card">
    <view class="q-header">
      <view class="q-header-left">
        <text class="q-num">第 {{ index + 1 }} 题</text>
        <text v-if="knowledgePointLabel" class="q-kp-tag">{{ knowledgePointLabel }}</text>
      </view>
      <view class="q-meta-badges">
        <text class="q-type">{{ typeLabel }}</text>
        <text v-if="question.difficulty" class="q-diff">难度 {{ question.difficulty }}</text>
      </view>
    </view>

    <view class="q-stem-wrap">
      <RichContent :content="question.stem" />
    </view>

    <view v-if="question.options && question.options.length" class="q-options">
      <view
        v-for="(option, optIdx) in question.options"
        :key="option.key || optIdx"
        class="option-item"
      >
        <text class="option-key">{{ optionKey(option, optIdx) }}.</text>
        <view class="option-content">
          <RichContent :content="cleanOptionContent(option.content)" compact />
        </view>
      </view>
    </view>

    <view class="answer-toggle-bar" @tap="showAnswer = !showAnswer">
      <text class="answer-toggle-text">
        {{ showAnswer ? '收起参考答案与解析' : '查看参考答案与解析' }}
      </text>
    </view>

    <view v-if="showAnswer" class="answer-panel">
      <view class="answer-row">
        <text class="answer-label">参考答案</text>
        <RichContent :content="formattedAnswer" compact />
      </view>

      <view v-if="explanationText" class="answer-row">
        <text class="answer-label">解析说明</text>
        <RichContent :content="explanationText" compact muted />
      </view>

      <view v-if="question.grading_points?.length" class="answer-row">
        <text class="answer-label">采分点</text>
        <view class="grading-list">
          <view v-for="(pt, pIdx) in question.grading_points" :key="pIdx" class="grading-item">
            <text class="grading-index">{{ pIdx + 1 }}.</text>
            <view class="grading-text">
              <RichContent :content="pt" compact muted />
            </view>
          </view>
        </view>
      </view>
    </view>

    <view v-if="question.source_quote" class="source-box">
      <text class="source-tag">讲义依据切片</text>
      <text v-if="isSourceGarbled" class="source-garbled-hint">
        检测到旧版讲义公式编码异常，重新解析讲义后可恢复原文依据
      </text>
      <RichContent v-else :content="question.source_quote" compact muted />
    </view>

    <view class="card-actions">
      <button class="remove-btn" @tap="emit('remove', question)">剔除本题</button>
      <button class="regen-btn" :disabled="disabled" @tap="emit('regenerate', question)">
        重新生成
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import RichContent from '@/components/RichContent.vue'
import { optionKey, questionTypeLabel } from '@/api'
import { isGarbledSnippetText } from '@/utils/richText'
import type { QuestionItem } from '@/types'
import { formatQuestionAnswer } from '../utils/composeHelpers'

const props = defineProps<{
  question: QuestionItem
  index: number
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'remove', question: QuestionItem): void
  (e: 'regenerate', question: QuestionItem): void
}>()

const showAnswer = ref(false)

watch(
  () => props.question.id,
  () => {
    showAnswer.value = false
  },
)

const typeLabel = computed(() => questionTypeLabel(props.question.type))
const knowledgePointLabel = computed(
  () => props.question.knowledge_point_name || props.question.knowledge_point || '',
)
const formattedAnswer = computed(() => formatQuestionAnswer(props.question))
const explanationText = computed(() => props.question.analysis || props.question.explanation || '')
const isSourceGarbled = computed(() => isGarbledSnippetText(props.question.source_quote))

const cleanOptionContent = (raw: string) =>
  String(raw ?? '')
    .trim()
    .replace(/^(?:(?:[(（][A-Z][)）]|[A-Z][.。、:：)）])\s*)+/i, '')
</script>

<style lang="scss" scoped>
@import '../questions.scss';
</style>
