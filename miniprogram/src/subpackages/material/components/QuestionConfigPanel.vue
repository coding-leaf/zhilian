<template>
  <view class="config-section">
    <view class="paper-card form-card">
      <view class="card-header-row">
        <text class="card-label card-label-inline">
          1. 考点范围 ({{ selectedKpIds.length }}/{{ availableKpList.length }})
        </text>
        <view v-if="availableKpList.length > 0" class="header-actions-row">
          <text class="select-all-btn" @tap="emit('toggle-select-all')">
            {{ isAllKpSelected ? '清空' : '全选' }}
          </text>
          <text class="picker-open-btn" @tap="emit('open-picker')">选择考点</text>
        </view>
      </view>

      <view v-if="availableKpList.length > 0" class="kp-summary-card">
        <template v-if="selectedKpIds.length > 0">
          <text class="kp-summary-meta">
            已选 {{ selectedKpIds.length }} 个考点 · 覆盖 {{ coveredGroupCount }} 个讲义/章节分组
          </text>
          <view class="kp-chips-group">
            <view
              v-for="kp in previewSelectedPoints"
              :key="kp.id"
              class="kp-chip active"
              @tap="emit('open-picker')"
            >
              <text class="kp-chip-text">{{ kp.name }}</text>
            </view>
            <view v-if="overflowCount > 0" class="kp-more-chip" @tap="emit('open-picker')">
              <text class="kp-more-text">+{{ overflowCount }} 个，点击调整</text>
            </view>
          </view>
        </template>
        <view v-else class="kp-empty-prompt" @tap="emit('open-picker')">
          <text class="notice-text">暂未选择考点，点击右上角「选择考点」勾选考察范围。</text>
        </view>
      </view>

      <view v-else class="notice-box">
        <text class="notice-text">
          {{ isLoadingKp ? '正在拉取考点列表...' : '当前范围暂无已解析考点，请先完成资料解析。' }}
        </text>
      </view>
    </view>

    <view class="paper-card form-card">
      <text class="card-label">2. 测验题型多选</text>
      <view class="type-chips-group">
        <view
          v-for="type in typeOptions"
          :key="type.value"
          :class="['type-chip', isTypeSelected(type.value) ? 'active' : '']"
          @tap="emit('toggle-type', type.value)"
        >
          <text class="type-chip-text">{{ type.label }}</text>
          <view v-if="isTypeSelected(type.value)" class="chip-check-mark" />
        </view>
      </view>
    </view>

    <view class="paper-card form-card">
      <text class="card-label">3. 题量与难度设置</text>
      <view class="mode-switch-block">
        <text class="setting-title">出题方案</text>
        <view class="mode-pills-row">
          <view
            :class="['mode-pill', composeMode === 'smart_sample' ? 'active' : '']"
            @tap="emit('update:composeMode', 'smart_sample')"
          >
            <text class="mode-pill-text">按题量智能抽考</text>
          </view>
          <view
            :class="['mode-pill', composeMode === 'full_coverage' ? 'active' : '']"
            @tap="emit('update:composeMode', 'full_coverage')"
          >
            <text class="mode-pill-text">全考点逐一覆盖</text>
          </view>
        </view>
      </view>

      <view class="setting-row">
        <text class="setting-title">题目数量：{{ questionCount }} 题</text>
        <slider
          :value="questionCount"
          :min="1"
          :max="20"
          :step="1"
          :active-color="sliderActiveColor"
          :block-size="20"
          @change="onCountChange"
        />
      </view>

      <view class="setting-row">
        <text class="setting-title">难度等级：{{ difficultyLabel }} ({{ difficulty }}/5)</text>
        <slider
          :value="difficulty"
          :min="1"
          :max="5"
          :step="1"
          :active-color="sliderActiveColor"
          :block-size="20"
          @change="onDifficultyChange"
        />
      </view>

      <view v-if="exceedsPracticeLimit" class="danger-notice-box">
        <text class="danger-notice-text">
          单次练习最多支持 50 题，当前全覆盖需 {{ selectedKpIds.length }} 题，请改用「按题量智能抽考」或缩减至 50 个考点以内。
        </text>
      </view>
      <view
        v-else-if="composeMode === 'smart_sample' && selectedKpIds.length > questionCount"
        class="notice-box"
      >
        <text class="notice-text">
          将从已选 {{ selectedKpIds.length }} 个考点中均匀抽取 {{ effectiveKpCount }} 个代表性考点，生成 {{ questionCount }} 题。
        </text>
      </view>
      <view
        v-else-if="composeMode === 'full_coverage' && plannedCount > questionCount"
        class="notice-box"
      >
        <text class="notice-text">
          已选 {{ selectedKpIds.length }} 个考点，全考点覆盖将生成 {{ plannedCount }} 题。
        </text>
      </view>
    </view>

    <view class="config-action-bar">
      <button
        class="paper-btn-primary full-btn"
        :loading="isGenerating"
        :disabled="selectedKpIds.length === 0 || exceedsPracticeLimit || isGenerating || isJobInFlight"
        @tap="emit('generate')"
      >
        {{ submitLabel }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QuestionType } from '@/types'
import type { ComposeKpGroup, ComposeMode, KnowledgePointOption } from '../utils/composeHelpers'

const props = defineProps<{
  availableKpList: KnowledgePointOption[]
  kpGroups: ComposeKpGroup[]
  selectedKpIds: string[]
  effectiveKpCount: number
  composeMode: ComposeMode
  selectedTypes: QuestionType[]
  questionCount: number
  difficulty: number
  plannedCount: number
  exceedsPracticeLimit: boolean
  isAllKpSelected: boolean
  isLoadingKp: boolean
  isGenerating: boolean
  isJobInFlight?: boolean
}>()

const emit = defineEmits<{
  (e: 'open-picker'): void
  (e: 'toggle-select-all'): void
  (e: 'toggle-type', type: QuestionType): void
  (e: 'update:composeMode', value: ComposeMode): void
  (e: 'update:questionCount', value: number): void
  (e: 'update:difficulty', value: number): void
  (e: 'generate'): void
}>()

const sliderActiveColor = 'rgb(30, 58, 138)'
const PREVIEW_LIMIT = 5
const DIFFICULTY_LABELS: Record<number, string> = {
  1: '极简入门',
  2: '基础巩固',
  3: '进阶综合',
  4: '高阶拓展',
  5: '硬核挑战',
}
const typeOptions: Array<{ label: string; value: QuestionType }> = [
  { label: '单项选择', value: 'single_choice' },
  { label: '多项选择', value: 'multiple_choice' },
  { label: '判断正误', value: 'true_false' },
  { label: '填空题', value: 'fill_in_blank' },
  { label: '名词解释', value: 'term_explanation' },
  { label: '简答/分析题', value: 'short_answer' },
  { label: '案例分析题', value: 'case_analysis' },
]

const selectedSet = computed(() => new Set(props.selectedKpIds))
const selectedPoints = computed(() =>
  props.availableKpList.filter((point) => selectedSet.value.has(point.id)),
)
const previewSelectedPoints = computed(() => selectedPoints.value.slice(0, PREVIEW_LIMIT))
const overflowCount = computed(() => Math.max(0, selectedPoints.value.length - PREVIEW_LIMIT))
const coveredGroupCount = computed(() =>
  props.kpGroups.filter((group) => group.points.some((pt) => selectedSet.value.has(pt.id))).length,
)
const isTypeSelected = (type: QuestionType) => props.selectedTypes.includes(type)
const difficultyLabel = computed(() => DIFFICULTY_LABELS[props.difficulty] || '适中')
const submitLabel = computed(() => {
  if (props.isJobInFlight) return '后台正在出题中...'
  if (props.isGenerating) return '正在创建出题任务...'
  if (props.exceedsPracticeLimit) return '考点超 50 个，请调整范围或切回抽考'
  return `一键智能出题 (${props.effectiveKpCount} 考点 · ${props.plannedCount} 题)`
})
const onCountChange = (e: { detail: { value: number } }) => emit('update:questionCount', e.detail.value)
const onDifficultyChange = (e: { detail: { value: number } }) => emit('update:difficulty', e.detail.value)
</script>

<style lang="scss" scoped>
@import '../questions.scss';
</style>
