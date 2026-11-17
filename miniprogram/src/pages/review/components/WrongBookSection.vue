<template>
  <view class="wrong-book-section">
    <view v-if="error" class="paper-card inline-error-box">
      <text class="inline-error-text">{{ error }}</text>
      <button class="inline-retry-btn" @tap="emit('retry')">重试</button>
    </view>

    <view v-if="groupOptions.length" class="group-scroll">
      <scroll-view scroll-x class="group-scroll" :show-scrollbar="false">
        <view class="group-tabs">
          <view
            v-if="groupOptions.length > 1"
            :class="['group-chip', selectedGroupKey === '' ? 'active' : '']"
            @tap="emit('select-group', '')"
          >
            <text class="group-chip-text">全部</text>
          </view>
          <view
            v-for="option in groupOptions"
            :key="option.key"
            :class="['group-chip', selectedGroupKey === option.key ? 'active' : '']"
            @tap="emit('select-group', option.key)"
          >
            <text class="group-chip-text">{{ option.label }}</text>
            <text class="group-chip-count">{{ option.count }}</text>
          </view>
        </view>
      </scroll-view>
    </view>

    <view v-if="unmasteredCount > 0" class="paper-card batch-wrong-bar">
      <view class="batch-wrong-left" @tap="emit('toggle-select-all')">
        <view :class="['wrong-checkbox', allUnmasteredSelected ? 'checked' : '']">
          <view v-if="allUnmasteredSelected" class="wrong-check-mark" />
        </view>
        <text class="batch-wrong-label">
          {{ selectedIds.length > 0 ? `已选 ${selectedIds.length} 题` : `全选待巩固 (${unmasteredCount})` }}
        </text>
      </view>
      <button class="paper-btn-primary restart-wrong-btn" @tap="emit('restart-selected')">
        发起错题重练
      </button>
    </view>

    <view v-if="needsGroupChoice" class="paper-card hint-card">
      <text class="action-desc">错题涉及多个课程，选择单个课程或资料范围可一键生成变式巩固题。</text>
    </view>

    <view v-if="activeGroup && activeKpIds.length > 0 && activeScopeReady" class="paper-card action-card">
      <view class="action-info">
        <text class="action-title">错题薄弱点举一反三</text>
        <text class="action-desc">
          汇总「{{ activeGroup.label }}」下 {{ activeKpIds.length }} 个薄弱考点，可一键再生题目巩固。
        </text>
      </view>
      <button class="paper-btn-primary quick-gen-btn" :loading="isGenerating" @tap="emit('batch-regenerate')">
        立即巩固
      </button>
    </view>

    <view v-if="activeGroup && !activeScopeReady" class="paper-card hint-card">
      <text class="action-desc">该范围内的资料尚未归属课程，暂时无法再生题，请先将资料归入课程。</text>
    </view>

    <view class="wrong-list">
      <WrongRecordCard
        v-for="record in records"
        :key="record.id"
        :record="record"
        :selected="selectedIds.includes(record.id)"
        :marking="markingIds.includes(record.id)"
        @practice="emit('practice', $event)"
        @toggle-select="emit('toggle-select', $event)"
        @mark-mastered="emit('mark-mastered', $event)"
      />
      <view v-if="records.length === 0 && !error" class="empty-state">
        <text class="empty-text">
          {{ loading ? '正在加载错题...' : '当前范围内没有待巩固的错题。' }}
        </text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WrongGroupOption } from '@/api/adapters/wrong'
import type { WrongRecordItem } from '@/types'
import WrongRecordCard from './WrongRecordCard.vue'

const props = defineProps<{
  records: WrongRecordItem[]
  groupOptions: WrongGroupOption[]
  selectedGroupKey: string
  activeGroup: WrongGroupOption | null
  activeKpIds: string[]
  activeScopeReady: boolean
  needsGroupChoice: boolean
  selectedIds: string[]
  markingIds: string[]
  loading: boolean
  error: string
  isGenerating: boolean
}>()

const emit = defineEmits<{
  (e: 'retry'): void
  (e: 'select-group', key: string): void
  (e: 'toggle-select', recordId: string): void
  (e: 'toggle-select-all'): void
  (e: 'mark-mastered', record: WrongRecordItem): void
  (e: 'restart-selected'): void
  (e: 'batch-regenerate'): void
  (e: 'practice', record: WrongRecordItem): void
}>()

const unmasteredIds = computed(() => props.records.filter((r) => !r.is_mastered).map((r) => r.id))
const unmasteredCount = computed(() => unmasteredIds.value.length)
const allUnmasteredSelected = computed(
  () =>
    unmasteredIds.value.length > 0
    && unmasteredIds.value.every((id) => props.selectedIds.includes(id)),
)
</script>

<style lang="scss" scoped>
@import '../review.scss';
</style>
