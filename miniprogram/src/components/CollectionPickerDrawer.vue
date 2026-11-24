<template>
  <view v-if="visible" class="sheet-overlay picker-sheet-overlay">
    <view class="modal-backdrop" @tap="closeDrawer" />
    <view class="sheet-panel picker-sheet">
      <view class="sheet-grabber" />
      <view class="picker-header">
        <view class="picker-titles">
          <text class="picker-title">收纳到题单</text>
          <text class="picker-subtitle">可勾选多个专题题单，或底部新建</text>
        </view>
        <view class="picker-close" @tap="closeDrawer"><text class="picker-close-text">关闭</text></view>
      </view>

      <scroll-view scroll-y class="picker-body">
        <view v-if="loading" class="picker-state"><text class="picker-state-text">正在加载题单...</text></view>
        <view v-else-if="loadError" class="picker-state">
          <text class="picker-error-text">{{ loadError }}</text>
          <button class="picker-retry-btn" @tap="loadPickerData">重试</button>
        </view>
        <view v-else-if="collections.length === 0" class="picker-state">
          <text class="picker-state-text">暂无题单，请在下方输入名称新建并收进。</text>
        </view>
        <view v-else class="picker-list">
          <view
            v-for="item in collections"
            :key="item.id"
            :class="['picker-row', isChecked(item.id) ? 'selected' : '']"
            @tap="toggleCollection(item.id)"
          >
            <view :class="['picker-checkbox', isChecked(item.id) ? 'checked' : '']">
              <view v-if="isChecked(item.id)" class="picker-check-mark" />
            </view>
            <view class="picker-row-info">
              <text class="picker-row-name">{{ item.name }}</text>
              <text class="picker-row-meta">
                共 {{ item.question_count }} 题{{ item.folder_name ? ` · ${item.folder_name}` : '' }}
              </text>
            </view>
          </view>
        </view>
      </scroll-view>

      <view class="picker-create-bar">
        <input
          v-model="newName"
          class="picker-create-input"
          placeholder="输入新题单名称..."
          :maxlength="40"
          :cursor-spacing="24"
          :disabled="creating"
          confirm-type="done"
          @confirm="handleQuickCreate"
        />
        <button
          class="picker-create-btn"
          :loading="creating"
          :disabled="!newName.trim() || creating"
          @tap="handleQuickCreate"
        >
          新建并收进
        </button>
      </view>

      <view class="picker-footer">
        <button
          class="paper-btn-primary picker-save-btn"
          :loading="saving"
          :disabled="loading || saving"
          @tap="handleSave"
        >
          确认收纳（已选 {{ selectedIds.length }}）
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  apiCreateCollection,
  apiGetQuestionCollections,
  apiListCollections,
  apiSyncQuestionCollections,
} from '@/api/modules/collections'
import type { QuestionCollection } from '@/types'
import { extractUserErrorMessage, safeShowToast } from '@/utils/loadingGuard'

const props = defineProps<{
  visible: boolean
  questionId: string
  folderId?: string
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'saved', payload: { questionId: string; collectionIds: string[] }): void
}>()

const collections = ref<QuestionCollection[]>([])
const selectedIds = ref<string[]>([])
const loading = ref(false)
const loadError = ref('')
const newName = ref('')
const creating = ref(false)
const saving = ref(false)
let openEpoch = 0

const isChecked = (id: string) => selectedIds.value.includes(id)
const toggleCollection = (id: string) => {
  selectedIds.value = isChecked(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}
const closeDrawer = () => { emit('update:visible', false) }

const loadPickerData = async () => {
  if (!props.questionId) return
  const epoch = ++openEpoch
  loading.value = true
  loadError.value = ''
  try {
    const [listRes, memberRes] = await Promise.all([
      apiListCollections(),
      apiGetQuestionCollections(props.questionId),
    ])
    if (epoch !== openEpoch) return
    collections.value = listRes.items || []
    selectedIds.value = [...(memberRes.collection_ids || [])]
  } catch (err) {
    if (epoch !== openEpoch) return
    loadError.value = extractUserErrorMessage(err, '题单加载失败，请重试')
  } finally {
    if (epoch === openEpoch) loading.value = false
  }
}

watch(
  () => [props.visible, props.questionId] as const,
  ([visible, qid]) => {
    if (!visible) return
    newName.value = ''
    if (qid) void loadPickerData()
  },
  { immediate: true },
)

const handleQuickCreate = async () => {
  const name = newName.value.trim()
  if (!name || creating.value) return
  creating.value = true
  try {
    const folderId = props.folderId && props.folderId !== 'all' && props.folderId !== '__none__'
      ? props.folderId
      : undefined
    const created = await apiCreateCollection({ name, ...(folderId ? { folder_id: folderId } : {}) })
    collections.value = [created, ...collections.value]
    if (!selectedIds.value.includes(created.id)) selectedIds.value = [...selectedIds.value, created.id]
    newName.value = ''
    safeShowToast('已新建题单', 'success')
  } catch (err) {
    safeShowToast(extractUserErrorMessage(err, '新建题单失败'))
  } finally {
    creating.value = false
  }
}

const handleSave = async () => {
  if (!props.questionId || saving.value) return
  saving.value = true
  try {
    const res = await apiSyncQuestionCollections(props.questionId, selectedIds.value)
    safeShowToast('已更新收纳', 'success')
    emit('saved', { questionId: props.questionId, collectionIds: res.collection_ids })
    closeDrawer()
  } catch (err) {
    safeShowToast(extractUserErrorMessage(err, '保存收纳失败'))
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
@import '../styles/modal.scss';
@import '../styles/tokens.scss';

.picker-sheet-overlay { z-index: var(--z-modal); }
.picker-sheet { max-height: 76vh; }
.sheet-grabber {
  width: 68rpx; height: 8rpx; border-radius: 999rpx;
  background: var(--color-border-strong); margin: 12rpx auto 4rpx; flex-shrink: 0;
}
.picker-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16rpx 28rpx 18rpx; border-bottom: 1px solid var(--color-surface-muted);
}
.picker-titles { flex: 1; min-width: 0; }
.picker-title { display: block; font-size: 30rpx; font-weight: 700; color: var(--color-ink-primary); }
.picker-subtitle { display: block; font-size: 22rpx; color: var(--color-ink-subtle); margin-top: 4rpx; }
.picker-close { padding: 6rpx 18rpx; border-radius: 24rpx; background: var(--color-surface-muted); }
.picker-close-text { font-size: 22rpx; color: var(--color-ink-subtle); }
.picker-body { max-height: 42vh; padding: 16rpx 28rpx; }
.picker-state { padding: 36rpx 0; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 14rpx; }
.picker-state-text { font-size: 24rpx; color: var(--color-ink-subtle); }
.picker-error-text { font-size: 24rpx; color: var(--color-wrong); }
.picker-retry-btn {
  margin: 0; padding: 0 28rpx; height: 60rpx; line-height: 60rpx; font-size: 24rpx;
  color: var(--color-academic-blue); background: var(--color-blue-bg); border-radius: 10rpx;
  &::after { border: none; }
}
.picker-list { display: flex; flex-direction: column; gap: 12rpx; }
.picker-row {
  display: flex; align-items: center; gap: 16rpx; padding: 18rpx 20rpx; border-radius: 12rpx;
  background: var(--color-surface-subtle); border: 1px solid var(--color-paper-border);
}
.picker-row.selected { background: var(--color-blue-bg); border-color: var(--color-blue-border); }
.picker-checkbox {
  width: 36rpx; height: 36rpx; border-radius: 8rpx; border: 2rpx solid var(--color-border-strong);
  background: var(--color-paper-card); display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.picker-checkbox.checked { background: var(--color-academic-blue); border-color: var(--color-academic-blue); }
.picker-check-mark { @include css-checkmark(var(--color-ink-on-primary), 14rpx, 8rpx); }
.picker-row-info { flex: 1; min-width: 0; }
.picker-row-name { display: block; font-size: 26rpx; font-weight: 600; color: var(--color-ink-primary); }
.picker-row-meta { display: block; font-size: 21rpx; color: var(--color-ink-subtle); margin-top: 4rpx; }
.picker-create-bar {
  display: flex; align-items: center; gap: 12rpx; padding: 14rpx 28rpx;
  border-top: 1px solid var(--color-surface-muted); background: var(--color-surface-warm);
}
.picker-create-input {
  flex: 1; height: 70rpx; padding: 0 18rpx; font-size: 25rpx; border-radius: 10rpx;
  background: var(--color-paper-card); border: 1px solid var(--color-paper-border);
}
.picker-create-btn {
  margin: 0; padding: 0 22rpx; height: 70rpx; line-height: 70rpx; font-size: 24rpx; font-weight: 600;
  color: var(--color-academic-blue); background: var(--color-blue-bg);
  border: 1px solid var(--color-blue-border); border-radius: 10rpx; flex-shrink: 0;
  &::after { border: none; }
}
.picker-footer {
  padding: 16rpx 28rpx calc(18rpx + env(safe-area-inset-bottom));
  border-top: 1px solid var(--color-surface-muted); background: var(--color-bg-card);
}
.picker-save-btn {
  margin: 0; height: 80rpx; line-height: 80rpx; font-size: 27rpx;
  &::after { border: none; }
}
</style>
