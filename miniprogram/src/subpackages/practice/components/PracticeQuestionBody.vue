<template>
  <view class="paper-card question-box">
    <view class="q-meta-row">
      <view class="q-meta-left">
        <view class="q-type-badge">{{ typeLabel }}</view>
        <text v-if="knowledgePointLabel" class="kp-badge">
          考点：{{ knowledgePointLabel }}
        </text>
        <text v-if="question.type === 'multiple_choice'" class="multi-hint-badge">
          多选题 · 可选多项
        </text>
      </view>
      <view class="q-meta-right">
        <text class="progress-total">{{ saveStatusText }}</text>
        <view class="coach-trigger-pill" @tap="emit('ask-coach')">
          <text class="coach-trigger-text">问助教</text>
        </view>
      </view>
    </view>

    <view class="q-stem-wrap">
      <RichContent :content="question.stem" />
    </view>

    <view v-if="question.type === 'true_false'" class="options-group">
      <view
        v-for="(option, idx) in trueFalseOptions"
        :key="option.key"
        :class="['option-btn', isOptionSelected(option.key) ? 'selected' : '']"
        @tap="emit('select-single', option.key)"
      >
        <view :class="['opt-key-badge', isOptionSelected(option.key) ? 'selected' : '']">
          <text class="opt-key-text">{{ trueFalseBadge(option, idx) }}</text>
        </view>
        <view class="opt-content">
          <RichContent :content="option.content" compact />
        </view>
      </view>
    </view>

    <view v-else-if="question.type === 'single_choice'" class="options-group">
      <view
        v-for="(option, idx) in question.options || []"
        :key="option.key || idx"
        :class="['option-btn', isOptionSelected(optionKey(option, idx)) ? 'selected' : '']"
        @tap="emit('select-single', optionKey(option, idx))"
      >
        <view :class="['opt-key-badge', isOptionSelected(optionKey(option, idx)) ? 'selected' : '']">
          <text class="opt-key-text">{{ optionKey(option, idx) }}</text>
        </view>
        <view class="opt-content">
          <RichContent :content="optionBody(option, idx)" compact />
        </view>
      </view>
    </view>

    <view v-else-if="question.type === 'multiple_choice'" class="options-group">
      <text class="multi-sub-tip">
        [多选题 · 可选多项] {{ selectedList.length > 0 ? `当前已选 ${selectedList.length} 项` : '点击选项勾选或取消' }}
      </text>
      <view
        v-for="(option, idx) in question.options || []"
        :key="option.key || idx"
        :class="['option-btn', isMultiOptionSelected(optionKey(option, idx)) ? 'selected' : '']"
        @tap="emit('toggle-multiple', optionKey(option, idx))"
      >
        <view
          :class="[
            'opt-checkbox-box',
            isMultiOptionSelected(optionKey(option, idx)) ? 'checked' : '',
          ]"
        >
          <view
            v-if="isMultiOptionSelected(optionKey(option, idx))"
            class="opt-checkbox-mark"
          />
        </view>
        <view :class="['opt-key-badge', isMultiOptionSelected(optionKey(option, idx)) ? 'selected' : '']">
          <text class="opt-key-text">{{ optionKey(option, idx) }}</text>
        </view>
        <view class="opt-content">
          <RichContent :content="optionBody(option, idx)" compact />
        </view>
      </view>
    </view>

    <view v-else-if="question.type === 'fill_in_blank'" class="fill-blank-box">
      <template v-if="blankCount >= 2">
        <text class="input-hint">
          检测到 {{ blankCount }} 个空格，请按顺序作答（系统将自动用分号分隔保存）：
        </text>
        <view v-for="(val, idx) in localBlankDrafts" :key="idx" class="fill-blank-row">
          <text class="fill-blank-index">第 {{ idx + 1 }} 空</text>
          <input
            v-if="!overlayOpen"
            class="fill-blank-input"
            :placeholder="`请输入第 ${idx + 1} 空答案...`"
            :value="val"
            :cursor-spacing="24"
            :show-confirm-bar="false"
            @input="handleMultiBlankInput(idx, $event)"
          />
          <view v-else class="fill-blank-input input-overlay-preview">
            <text :class="['overlay-preview-text', { placeholder: !val }]">
              {{ val || `请输入第 ${idx + 1} 空答案...` }}
            </text>
          </view>
        </view>
      </template>
      <template v-else>
        <text class="input-hint">请在下方输入作答内容（若含多个空格请用分号 ; 分隔）：</text>
        <input
          v-if="!overlayOpen"
          class="fill-blank-input"
          placeholder="请输入你的填空答案..."
          :value="localSingleDraft"
          :cursor-spacing="24"
          :show-confirm-bar="false"
          @input="handleSingleTextInput"
        />
        <view v-else class="fill-blank-input input-overlay-preview">
          <text :class="['overlay-preview-text', { placeholder: !localSingleDraft }]">
            {{ localSingleDraft || '请输入你的填空答案...' }}
          </text>
        </view>
      </template>
    </view>

    <view v-else class="essay-box">
      <view class="essay-hint-row">
        <text class="input-hint">请输入你的要点与分析：</text>
        <text v-if="question.max_score" class="score-hint-pill">满分 {{ question.max_score }} 分</text>
      </view>
      <textarea
        v-if="!overlayOpen"
        class="essay-input"
        placeholder="结合考点，详细阐述你的解答步骤、核心定义或案例见解..."
        :value="localSingleDraft"
        :maxlength="1000"
        :cursor-spacing="24"
        :show-confirm-bar="false"
        @input="handleSingleTextInput"
      />
      <view v-else class="essay-input essay-overlay-preview">
        <text :class="['overlay-preview-text', { placeholder: !localSingleDraft }]">
          {{ localSingleDraft || '结合考点，详细阐述你的解答步骤、核心定义或案例见解...' }}
        </text>
      </view>
      <text class="essay-count">{{ localSingleDraft.length }}/1000</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import RichContent from '@/components/RichContent.vue'
import { optionDisplayText, optionKey, questionTypeLabel } from '@/api'
import type { QuestionItem, QuestionOption } from '@/types'
import {
  isSingleOrTrueFalseSelected,
  joinFillBlankAnswers,
  normalizeMultipleSelection,
  resolveFillBlankCount,
  resolveTrueFalseOptions,
  splitFillBlankAnswers,
  trueFalseBadgeText,
} from '../utils/practiceSession'

const props = defineProps<{
  question: QuestionItem
  userAnswer: unknown
  saveStatusText: string
  overlayOpen?: boolean
}>()

const emit = defineEmits<{
  (e: 'select-single', value: string): void
  (e: 'toggle-multiple', value: string): void
  (e: 'input-answer', value: string): void
  (e: 'ask-coach'): void
}>()

const typeLabel = computed(() => questionTypeLabel(props.question.type))
const knowledgePointLabel = computed(
  () => props.question.knowledge_point_name || props.question.knowledge_point || '',
)
const trueFalseOptions = computed(() => resolveTrueFalseOptions(props.question.options))
const trueFalseBadge = (option: QuestionOption, idx: number) => trueFalseBadgeText(option, idx)
const optionBody = (option: QuestionOption, idx: number) =>
  option.content?.trim() ? option.content : optionDisplayText(option, idx)

const isOptionSelected = (value: string) =>
  isSingleOrTrueFalseSelected(props.question.type, props.userAnswer, value)

const selectedList = computed(() => normalizeMultipleSelection(props.userAnswer))
const isMultiOptionSelected = (value: string) => selectedList.value.includes(value)

const blankCount = computed(() => resolveFillBlankCount(props.question.stem, props.question.answer))
const localBlankDrafts = ref<string[]>([])
const localSingleDraft = ref('')
let lastEmittedAnswer: string | undefined

const syncDraftsFromProps = () => {
  localSingleDraft.value = typeof props.userAnswer === 'string' ? props.userAnswer : ''
  localBlankDrafts.value = splitFillBlankAnswers(props.userAnswer, blankCount.value)
}

watch(
  () => [props.question.id, blankCount.value] as const,
  () => {
    lastEmittedAnswer = undefined
    syncDraftsFromProps()
  },
  { immediate: true },
)

watch(
  () => props.userAnswer,
  (nextVal) => {
    if (nextVal === lastEmittedAnswer) return
    syncDraftsFromProps()
  },
)

const handleMultiBlankInput = (index: number, event: { detail: { value: string } }) => {
  const nextParts = [...localBlankDrafts.value]
  while (nextParts.length < blankCount.value) nextParts.push('')
  nextParts[index] = event.detail.value
  localBlankDrafts.value = nextParts
  const joined = joinFillBlankAnswers(nextParts)
  lastEmittedAnswer = joined
  emit('input-answer', joined)
}

const handleSingleTextInput = (event: { detail: { value: string } }) => {
  const val = event.detail.value
  localSingleDraft.value = val
  lastEmittedAnswer = val
  emit('input-answer', val)
}
</script>

<style lang="scss" scoped>
@import '../session.scss';
</style>
