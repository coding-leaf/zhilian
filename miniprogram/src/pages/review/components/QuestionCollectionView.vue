<template>
  <view class="collection-view">
    <view class="col-toolbar">
      <button class="col-new-btn" @tap="openCreateModal">+ 新建题单</button>
      <text class="section-refresh" @tap="store.loadCollections">刷新</text>
    </view>

    <view v-if="store.isLoading.value && store.collections.value.length === 0" class="paper-card bank-state-card">
      <text class="bank-state-text">正在加载题单...</text>
    </view>

    <view v-else-if="store.loadError.value && store.collections.value.length === 0" class="paper-card bank-state-card bank-error-card">
      <text class="bank-state-text">{{ store.loadError.value }}</text>
      <button class="bank-retry-btn" @tap="store.loadCollections">重试</button>
    </view>

    <view v-else-if="store.collections.value.length === 0" class="paper-card bank-state-card">
      <text class="bank-state-text">暂无自定义题单，点击「+ 新建题单」或从题目「收纳」创建。</text>
    </view>

    <view v-for="col in store.collections.value" :key="col.id" class="paper-card col-card">
      <view class="col-card-head">
        <view class="col-card-info" @tap="store.toggleExpandCollection(col.id)">
          <view class="col-title-row">
            <text class="col-name">{{ col.name }}</text>
            <text v-if="col.folder_name" class="col-folder-pill">{{ col.folder_name }}</text>
          </view>
          <text class="col-meta">共 {{ col.question_count }} 题</text>
        </view>
        <view class="col-head-actions">
          <button
            class="paper-btn-primary col-practice-btn"
            :loading="store.startingCollectionId.value === col.id"
            :disabled="col.question_count === 0 || store.startingCollectionId.value === col.id"
            @tap="store.startCollectionPractice(col)"
          >
            整单开练
          </button>
        </view>
      </view>

      <view class="col-sub-actions">
        <text class="col-action-link" @tap="store.toggleExpandCollection(col.id)">
          {{ store.isExpanded(col.id) ? '收起题目' : '查看题目' }}
        </text>
        <view class="col-manage-links">
          <text class="col-action-link" @tap="openRenameModal(col)">重命名</text>
          <text class="col-action-danger" @tap="store.deleteCollection(col)">删除</text>
        </view>
      </view>

      <view v-if="store.isExpanded(col.id)" class="bank-question-list">
        <view v-if="store.isLoadingQuestions(col.id) && store.questionsFor(col.id).length === 0" class="bank-state-line">
          <text class="bank-state-text">正在加载题单题目...</text>
        </view>
        <view v-else-if="store.questionError(col.id)" class="bank-state-line">
          <text class="bank-state-text">{{ store.questionError(col.id) }}</text>
          <text class="bank-retry-text" @tap="store.loadCollectionQuestions(col.id, 1)">重试</text>
        </view>
        <view v-else-if="store.questionsFor(col.id).length === 0" class="bank-state-line">
          <text class="bank-state-text">题单里还没有题目，可在题库或错题本点击「收纳」。</text>
        </view>
        <template v-else>
          <view v-for="item in store.questionsFor(col.id)" :key="item.id" class="col-q-row">
            <view class="col-q-top">
              <view class="col-q-meta">
                <text class="col-q-type">{{ questionTypeLabel(item.question_type) }}</text>
                <text v-if="item.kp_name" class="col-q-kp">{{ item.kp_name }}</text>
              </view>
              <view class="col-q-btns">
                <text class="col-q-btn" @tap="toggleAnalysis(item.question_id)">
                  {{ expandedAnalysisIds.includes(item.question_id) ? '收起解析' : '看解析' }}
                </text>
                <text class="col-q-btn" @tap="emit('collect', item.question_id)">收纳</text>
                <text class="col-q-remove" @tap="store.removeQuestionFromCollection(col.id, item.question_id)">
                  移出
                </text>
              </view>
            </view>
            <RichContent :content="item.content" compact />
            <view v-if="expandedAnalysisIds.includes(item.question_id)" class="col-q-detail">
              <text v-if="formatAnswer(item.answer)" class="col-q-ans">参考答案：{{ formatAnswer(item.answer) }}</text>
              <RichContent v-if="item.explanation" :content="item.explanation" compact muted />
            </view>
          </view>
          <view v-if="store.hasMoreQuestions(col.id)" class="col-more-wrap">
            <button
              class="bank-more-btn"
              :loading="store.isLoadingQuestions(col.id)"
              :disabled="store.isLoadingQuestions(col.id)"
              @tap="store.loadMoreCollectionQuestions(col.id)"
            >
              加载更多题目
            </button>
          </view>
        </template>
      </view>
    </view>

    <view v-if="modalVisible" class="modal-overlay">
      <view class="modal-backdrop" @tap="modalVisible = false" />
      <view class="modal-content">
        <view class="modal-header">
          <text class="modal-title">{{ editingTarget ? '重命名题单' : '新建题单' }}</text>
          <text class="modal-close" @tap="modalVisible = false">关闭</text>
        </view>
        <input
          v-model="formName"
          class="form-input"
          placeholder="例如：期中高频易错、SVM 核心推导"
          :maxlength="40"
          :cursor-spacing="24"
          :disabled="store.isSaving.value"
        />
        <view class="modal-footer">
          <button class="modal-cancel-btn" @tap="modalVisible = false">取消</button>
          <button
            class="paper-btn-primary modal-confirm-btn"
            :loading="store.isSaving.value"
            :disabled="!formName.trim() || store.isSaving.value"
            @tap="submitForm"
          >
            确认
          </button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { questionTypeLabel } from '@/api'
import RichContent from '@/components/RichContent.vue'
import type { QuestionCollection } from '@/types'
import { useQuestionCollections } from '../composables/useQuestionCollections'

const props = defineProps<{ folderId: string }>()
const emit = defineEmits<{ (e: 'collect', questionId: string): void }>()

const store = useQuestionCollections(() => props.folderId)
const modalVisible = ref(false)
const editingTarget = ref<QuestionCollection | null>(null)
const formName = ref('')
const expandedAnalysisIds = ref<string[]>([])

const openCreateModal = () => {
  editingTarget.value = null
  formName.value = ''
  modalVisible.value = true
}

const openRenameModal = (col: QuestionCollection) => {
  editingTarget.value = col
  formName.value = col.name
  modalVisible.value = true
}

const submitForm = async () => {
  const result = editingTarget.value
    ? await store.renameCollection(editingTarget.value.id, formName.value)
    : await store.createCollection(formName.value)
  if (result) modalVisible.value = false
}

const toggleAnalysis = (questionId: string) => {
  expandedAnalysisIds.value = expandedAnalysisIds.value.includes(questionId)
    ? expandedAnalysisIds.value.filter((id) => id !== questionId)
    : [...expandedAnalysisIds.value, questionId]
}

const formatAnswer = (val: string | string[] | number | null) => {
  if (val === null || val === undefined || val === '') return ''
  return Array.isArray(val) ? val.join('、') : String(val)
}

defineExpose({
  refresh: store.loadCollections,
  resetState: store.resetCollectionsState,
})
</script>

<style lang="scss" scoped>
@import '../../../styles/modal.scss';
@import '../questionBank.scss';

.col-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16rpx; }
.col-new-btn {
  margin: 0; padding: 0 24rpx; height: 60rpx; line-height: 60rpx; font-size: 24rpx; font-weight: 600;
  color: var(--color-academic-blue); background: var(--color-blue-bg); border: 1px solid var(--color-blue-border); border-radius: 10rpx;
  &::after { border: none; }
}
.col-card { padding: 24rpx 28rpx; margin-bottom: 20rpx; }
.col-card-head { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; }
.col-card-info { flex: 1; min-width: 0; }
.col-title-row { display: flex; align-items: center; gap: 10rpx; flex-wrap: wrap; }
.col-name { font-size: 28rpx; font-weight: 700; color: var(--color-ink-primary); }
.col-folder-pill { font-size: 20rpx; padding: 2rpx 10rpx; border-radius: 6rpx; background: var(--color-surface-muted); color: var(--color-ink-subtle); }
.col-meta { display: block; font-size: 22rpx; color: var(--color-ink-muted); margin-top: 6rpx; }
.col-practice-btn {
  margin: 0; padding: 0 22rpx; height: 60rpx; line-height: 60rpx; font-size: 23rpx; flex-shrink: 0;
  &::after { border: none; }
}
.col-sub-actions {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 14rpx; padding-top: 12rpx; border-top: 1px dashed var(--color-surface-muted);
}
.col-manage-links { display: flex; align-items: center; gap: 20rpx; }
.col-action-link { font-size: 23rpx; color: var(--color-academic-blue); }
.col-action-danger { font-size: 23rpx; color: var(--color-wrong); }
.col-q-row { padding: 14rpx 0; border-bottom: 1px solid var(--color-surface-subtle); }
.col-q-top { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; margin-bottom: 8rpx; }
.col-q-meta { display: flex; align-items: center; gap: 8rpx; flex-wrap: wrap; flex: 1; min-width: 0; }
.col-q-type { font-size: 20rpx; color: var(--color-ink-subtle); background: var(--color-surface-muted); padding: 2rpx 10rpx; border-radius: 6rpx; }
.col-q-kp { font-size: 20rpx; color: var(--color-academic-blue); background: var(--color-blue-bg); padding: 2rpx 10rpx; border-radius: 6rpx; }
.col-q-btns { display: flex; align-items: center; gap: 14rpx; flex-shrink: 0; }
.col-q-btn { font-size: 21rpx; color: var(--color-academic-blue); }
.col-q-remove { font-size: 21rpx; color: var(--color-wrong); }
.col-q-detail { margin-top: 10rpx; padding: 12rpx 14rpx; border-radius: 8rpx; background: var(--color-surface-subtle); }
.col-q-ans { display: block; font-size: 22rpx; font-weight: 600; color: var(--color-correct); margin-bottom: 6rpx; }
.col-more-wrap { display: flex; justify-content: center; padding-top: 14rpx; }
.modal-cancel-btn, .modal-confirm-btn {
  margin: 0;
  &::after { border: none; }
}
</style>
