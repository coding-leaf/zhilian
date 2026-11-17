<template>
  <view v-if="visible" class="sheet-overlay">
    <view class="modal-backdrop" @tap="close" />
    <view class="sheet-panel picker-sheet-panel">
      <view class="sheet-grabber" />
      <view class="picker-header">
        <view class="picker-title-row">
          <text class="picker-title">选择考察知识点</text>
          <text class="picker-count-pill">已选 {{ selectedIds.length }}</text>
        </view>
        <text class="modal-close" @tap="close">关闭</text>
      </view>

      <view class="picker-toolbar">
        <view class="search-box">
          <input
            v-model="keyword"
            class="search-input"
            placeholder="搜索讲义或考点关键词..."
            confirm-type="search"
          />
          <text v-if="keyword" class="search-clear" @tap="keyword = ''">清空</text>
        </view>
        <view class="toolbar-actions">
          <text
            v-if="filteredGroups.length > 1"
            class="toolbar-link"
            @tap="toggleExpandAll"
          >
            {{ isAllExpanded ? '全部收起' : '全部展开' }}
          </text>
          <text class="toolbar-link" @tap="emit('toggle-select-all')">
            {{ isAllSelected ? '清空已选' : '全部全选' }}
          </text>
        </view>
      </view>

      <view class="sheet-scroll-wrap">
        <scroll-view scroll-y class="sheet-body">
          <view class="picker-list">
            <view v-for="group in filteredGroups" :key="group.id" class="acc-group">
              <view class="acc-header" @tap="toggleExpand(group.id)">
                <view class="acc-title-wrap">
                  <view :class="['acc-chevron', { expanded: isGroupExpanded(group.id) }]" />
                  <text class="acc-title">{{ group.title }}</text>
                  <text class="acc-ratio">
                    已选 {{ countGroupSelected(group.points) }}/{{ group.points.length }}
                  </text>
                </view>
                <text
                  class="acc-toggle-btn"
                  @tap.stop="emit('toggle-group', group.points.map((p) => p.id))"
                >
                  {{ isGroupAllSelected(group.points) ? '取消本组' : '全选本组' }}
                </text>
              </view>

              <view v-if="isGroupExpanded(group.id)" class="acc-body">
                <view
                  v-for="kp in group.points"
                  :key="kp.id"
                  :class="['kp-chip', isSelected(kp.id) ? 'active' : '']"
                  @tap="emit('toggle-kp', kp.id)"
                >
                  <text class="kp-chip-text">{{ kp.name }}</text>
                  <view v-if="isSelected(kp.id)" class="chip-check-mark" />
                </view>
              </view>
            </view>

            <view v-if="filteredGroups.length === 0" class="picker-empty">
              <text class="picker-empty-text">未找到匹配的考点，换个关键词试试</text>
            </view>
          </view>
        </scroll-view>
      </view>

      <view class="sheet-footer">
        <text class="footer-summary">已选 {{ selectedIds.length }} 个考点</text>
        <button class="paper-btn-primary footer-confirm-btn" @tap="confirmSelection">
          确认选择
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ComposeKpGroup, KnowledgePointOption } from '../utils/composeHelpers'

defineOptions({ options: { virtualHost: true } })

const props = defineProps<{
  visible: boolean
  groups: ComposeKpGroup[]
  selectedIds: string[]
  isAllSelected: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'toggle-kp', id: string): void
  (e: 'toggle-group', ids: string[]): void
  (e: 'toggle-select-all'): void
  (e: 'confirm'): void
}>()

const keyword = ref('')
const expandedIds = ref<Set<string>>(new Set())

const selectedSet = computed(() => new Set(props.selectedIds))

const filteredGroups = computed<ComposeKpGroup[]>(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return props.groups
  const matched: ComposeKpGroup[] = []
  for (const group of props.groups) {
    if (group.title.toLowerCase().includes(q)) {
      matched.push(group)
      continue
    }
    const points = group.points.filter((pt) => pt.name.toLowerCase().includes(q))
    if (points.length > 0) {
      matched.push({ ...group, points })
    }
  }
  return matched
})

const resetDefaultExpansion = () => {
  const firstId = props.groups[0]?.id
  expandedIds.value = firstId ? new Set([firstId]) : new Set()
}

watch(
  () => props.visible,
  (open) => {
    if (open) {
      keyword.value = ''
      resetDefaultExpansion()
    }
  },
)

watch(
  () => props.groups,
  () => {
    if (!keyword.value.trim()) resetDefaultExpansion()
  },
  { immediate: true },
)

const isSelected = (id: string) => selectedSet.value.has(id)
const countGroupSelected = (points: KnowledgePointOption[]) =>
  points.filter((pt) => selectedSet.value.has(pt.id)).length
const isGroupAllSelected = (points: KnowledgePointOption[]) =>
  points.length > 0 && points.every((pt) => selectedSet.value.has(pt.id))

const isGroupExpanded = (groupId: string) =>
  keyword.value.trim().length > 0 || expandedIds.value.has(groupId)

const isAllExpanded = computed(
  () =>
    filteredGroups.value.length > 0
    && filteredGroups.value.every((group) => isGroupExpanded(group.id)),
)

const toggleExpand = (groupId: string) => {
  if (keyword.value.trim()) return
  const next = new Set(expandedIds.value)
  if (next.has(groupId)) next.delete(groupId)
  else next.add(groupId)
  expandedIds.value = next
}

const toggleExpandAll = () => {
  if (isAllExpanded.value) {
    expandedIds.value = new Set()
  } else {
    expandedIds.value = new Set(filteredGroups.value.map((group) => group.id))
  }
}

const close = () => {
  emit('update:visible', false)
}

const confirmSelection = () => {
  emit('confirm')
  emit('update:visible', false)
}
</script>

<style lang="scss" scoped>
@import '../../../styles/modal.scss';
@import '../questions.scss';

.picker-sheet-panel { height: 78vh; max-height: 82vh; }
.sheet-grabber { width: 72rpx; height: 8rpx; border-radius: 999rpx; background: var(--color-border-strong); margin: 14rpx auto 6rpx; flex-shrink: 0; }
.picker-header { display: flex; align-items: center; justify-content: space-between; padding: 16rpx 28rpx 14rpx; border-bottom: 1px solid var(--color-paper-border); flex-shrink: 0; }
.picker-title-row { display: flex; align-items: center; gap: 12rpx; }
.picker-title { font-size: 31rpx; font-weight: 700; color: var(--color-ink-primary); }
.picker-count-pill { font-size: 22rpx; font-weight: 600; color: var(--color-academic-blue); background: var(--color-blue-bg); padding: 4rpx 14rpx; border-radius: 999rpx; }
.picker-toolbar { padding: 16rpx 28rpx 14rpx; border-bottom: 1px solid var(--color-surface-muted); display: flex; flex-direction: column; gap: 12rpx; flex-shrink: 0; }
.search-box { display: flex; align-items: center; gap: 12rpx; padding: 0 18rpx; height: 72rpx; background: var(--color-surface-subtle); border: 1px solid var(--color-paper-border); border-radius: 12rpx; }
.search-input { flex: 1; font-size: 25rpx; color: var(--color-ink-primary); height: 72rpx; }
.search-clear { font-size: 23rpx; color: var(--color-ink-subtle); padding: 6rpx 10rpx; }
.toolbar-actions { display: flex; justify-content: flex-end; gap: 24rpx; }
.toolbar-link { font-size: 23rpx; font-weight: 600; color: var(--color-academic-blue); }
.sheet-scroll-wrap { flex: 1; height: 0; min-height: 0; width: 100%; overflow: hidden; display: flex; flex-direction: column; }
.sheet-body { height: 100%; width: 100%; box-sizing: border-box; }
.picker-list { padding: 18rpx 28rpx 28rpx; display: flex; flex-direction: column; gap: 16rpx; }
.acc-group { border: 1px solid var(--color-paper-border); border-radius: 14rpx; background: var(--color-bg-card); overflow: hidden; }
.acc-header { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; padding: 18rpx 20rpx; background: var(--color-surface-warm); }
.acc-title-wrap { flex: 1; min-width: 0; display: flex; align-items: center; gap: 12rpx; }
.acc-chevron { width: 12rpx; height: 12rpx; border-right: 3rpx solid var(--color-ink-secondary); border-bottom: 3rpx solid var(--color-ink-secondary); transform: rotate(-45deg); flex-shrink: 0; }
.acc-chevron.expanded { transform: rotate(45deg); margin-top: -4rpx; }
.acc-title { flex: 1; min-width: 0; font-size: 25rpx; font-weight: 600; color: var(--color-ink-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.acc-ratio { font-size: 22rpx; color: var(--color-ink-subtle); flex-shrink: 0; }
.acc-toggle-btn { font-size: 22rpx; font-weight: 600; color: var(--color-academic-blue); flex-shrink: 0; }
.acc-body { display: flex; flex-wrap: wrap; gap: 12rpx; padding: 16rpx 20rpx; border-top: 1px solid var(--color-surface-muted); }
.picker-empty { padding: 48rpx 0; text-align: center; }
.picker-empty-text { font-size: 25rpx; color: var(--color-ink-muted); }
.sheet-footer { display: flex; align-items: center; justify-content: space-between; gap: 20rpx; padding: 18rpx 28rpx calc(18rpx + env(safe-area-inset-bottom)); background: var(--color-bg-card); border-top: 1px solid var(--color-paper-border); flex-shrink: 0; }
.footer-summary { font-size: 25rpx; font-weight: 600; color: var(--color-ink-secondary); }
.footer-confirm-btn { flex: 1; height: 80rpx; font-size: 28rpx; }
</style>
