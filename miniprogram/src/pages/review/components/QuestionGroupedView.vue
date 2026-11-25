<template>
  <view class="grouped-view">
    <view v-if="isLoading && materials.length === 0" class="paper-card bank-state-card">
      <text class="bank-state-text">正在汇总讲义与考点题目...</text>
    </view>

    <view v-else-if="loadError && materials.length === 0" class="paper-card bank-state-card bank-error-card">
      <text class="bank-state-text">{{ loadError }}</text>
      <button class="bank-retry-btn" @tap="loadSummary">重试</button>
    </view>

    <view v-else-if="materials.length === 0" class="paper-card bank-state-card">
      <text class="bank-state-text">当前范围内暂无讲义题目，到资料详情页出题后会按讲义自动归类。</text>
    </view>

    <template v-else>
      <view v-for="mat in materials" :key="mat.materialId" class="paper-card grp-mat-card">
        <view class="grp-mat-head">
          <view class="grp-mat-titles">
            <text class="grp-mat-title">{{ mat.materialTitle }}</text>
            <text v-if="mat.folderName" class="grp-folder-pill">{{ mat.folderName }}</text>
          </view>
          <text class="grp-mat-count">共 {{ mat.questionCount }} 题</text>
        </view>

        <view class="grp-kp-list">
          <view v-for="kp in mat.knowledgePoints" :key="kpKey(mat.materialId, kp.kpId)" class="grp-kp-block">
            <view
              :class="['grp-kp-row', isExpanded(kpKey(mat.materialId, kp.kpId)) ? 'active' : '']"
              @tap="toggleExpandKp(mat.materialId, kp.kpId)"
            >
              <text class="grp-kp-name">{{ kp.kpName }}</text>
              <view class="grp-kp-right">
                <text class="grp-kp-count">{{ kp.questionCount }} 题</text>
                <text class="grp-kp-arrow">{{ isExpanded(kpKey(mat.materialId, kp.kpId)) ? '收起' : '展开' }}</text>
              </view>
            </view>

            <view v-if="isExpanded(kpKey(mat.materialId, kp.kpId))" class="grp-q-list">
              <view v-if="isLoadingKp(kpKey(mat.materialId, kp.kpId))" class="bank-state-line">
                <text class="bank-state-text">正在加载题目...</text>
              </view>
              <view v-else-if="kpError(kpKey(mat.materialId, kp.kpId))" class="bank-state-line">
                <text class="bank-state-text">{{ kpError(kpKey(mat.materialId, kp.kpId)) }}</text>
                <text class="bank-retry-text" @tap="loadKpQuestions(mat.materialId, kp.kpId)">重试</text>
              </view>
              <view v-else-if="questionsFor(kpKey(mat.materialId, kp.kpId)).length === 0" class="bank-state-line">
                <text class="bank-state-text">该考点下暂无可见题目。</text>
              </view>
              <template v-else>
                <QuestionBankQuestionRow
                  v-for="q in questionsFor(kpKey(mat.materialId, kp.kpId))"
                  :key="q.id"
                  :question="q"
                  :selected="selectedIds.includes(q.id)"
                  :detail-expanded="cache.expandedDetailIds.value.includes(q.id)"
                  :detail="cache.questionDetails.value.get(q.id)"
                  :loading-detail="cache.loadingDetailIds.value.includes(q.id)"
                  :detail-error="cache.detailErrors.value.get(q.id) || ''"
                  @toggle="toggleSelect(q)"
                  @toggle-detail="cache.toggleQuestionDetail(q.id)"
                  @retry-detail="cache.loadQuestionDetail(q.id)"
                  @collect="emit('collect', q.id)"
                >
                  <template #action>
                    <view
                      :class="[
                        'bank-wrong-btn',
                        wrongMarkClass(q.id),
                        { pending: wrongPendingIds.includes(q.id) },
                      ]"
                      @tap="emit('toggle-wrong', q.id)"
                    >
                      <text class="bank-wrong-text">{{ wrongMarkLabel(wrongMarks.get(q.id) ?? null) }}</text>
                    </view>
                  </template>
                </QuestionBankQuestionRow>
              </template>
            </view>
          </view>
        </view>
      </view>

      <view class="paper-card action-card bank-action-card">
        <view class="action-info">
          <text class="action-title">已选 {{ selectedIds.length }} 题</text>
          <text class="action-desc">
            {{ selectedIds.length === 0 ? '展开考点勾选题目，组卷巩固薄弱环节' : '点击立即开练进入作答' }}
          </text>
        </view>
        <button
          class="paper-btn-primary quick-gen-btn"
          :loading="isStarting"
          :disabled="selectedIds.length === 0 || isStarting"
          @tap="startSelectedPractice"
        >
          立即开练
        </button>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { MAX_PRACTICE_QUESTIONS, apiCreatePractice } from '@/api'
import { apiGetQuestionGroupedSummary, apiListQuestionBankItems } from '@/api/modules/questions'
import type { GroupedMaterialSummary, QuestionBankItem, WrongRecordItem } from '@/types'
import { extractUserErrorMessage, safeShowToast } from '@/utils/loadingGuard'
import { wrongMarkLabel } from '../reviewView'
import { useBatchQuestionsCache } from '../composables/useBatchQuestionsCache'
import QuestionBankQuestionRow from './QuestionBankQuestionRow.vue'

const props = defineProps<{
  folderId: string
  wrongMarks: Map<string, WrongRecordItem>
  wrongPendingIds: string[]
}>()

const emit = defineEmits<{
  (e: 'toggle-wrong', questionId: string): void
  (e: 'collect', questionId: string): void
}>()

const materials = ref<GroupedMaterialSummary[]>([])
const isLoading = ref(false)
const loadError = ref('')
const expandedKps = ref<string[]>([])
const questionsByKp = ref<Map<string, QuestionBankItem[]>>(new Map())
const loadingKps = ref<string[]>([])
const kpErrors = ref<Map<string, string>>(new Map())
const selectedIds = ref<string[]>([])
const isStarting = ref(false)
const cache = useBatchQuestionsCache(() => props.folderId)
let groupedEpoch = 0

const kpKey = (materialId: string, kpId: string | null) => `${materialId}::${kpId ?? '__none__'}`
const isExpanded = (key: string) => expandedKps.value.includes(key)
const isLoadingKp = (key: string) => loadingKps.value.includes(key)
const kpError = (key: string) => kpErrors.value.get(key) ?? ''
const questionsFor = (key: string) => questionsByKp.value.get(key) ?? []

const wrongMarkClass = (questionId: string): string => {
  const record = props.wrongMarks.get(questionId)
  if (!record) return ''
  return record.is_mastered ? 'mastered' : 'marked'
}

const loadSummary = async () => {
  const epoch = groupedEpoch
  isLoading.value = true
  loadError.value = ''
  try {
    const res = await apiGetQuestionGroupedSummary(props.folderId)
    if (epoch !== groupedEpoch) return
    materials.value = res.materials || []
  } catch (err) {
    if (epoch !== groupedEpoch) return
    loadError.value = extractUserErrorMessage(err, '讲义考点汇总加载失败，请重试')
  } finally {
    if (epoch === groupedEpoch) isLoading.value = false
  }
}

const loadKpQuestions = async (materialId: string, kpId: string | null) => {
  const key = kpKey(materialId, kpId)
  if (loadingKps.value.includes(key)) return
  const epoch = groupedEpoch
  loadingKps.value = [...loadingKps.value, key]
  const nextErr = new Map(kpErrors.value)
  nextErr.delete(key)
  kpErrors.value = nextErr
  try {
    const res = await apiListQuestionBankItems({
      material_id: materialId,
      ...(kpId ? { knowledge_point_id: kpId } : {}),
      ...(props.folderId && props.folderId !== 'all' ? { folder_id: props.folderId } : {}),
      page: 1,
      page_size: 50,
    })
    if (epoch !== groupedEpoch) return
    questionsByKp.value = new Map(questionsByKp.value).set(key, res.items || [])
  } catch (err) {
    if (epoch !== groupedEpoch) return
    kpErrors.value = new Map(kpErrors.value).set(key, extractUserErrorMessage(err, '题目加载失败'))
  } finally {
    loadingKps.value = loadingKps.value.filter((item) => item !== key)
  }
}

const toggleExpandKp = async (materialId: string, kpId: string | null) => {
  const key = kpKey(materialId, kpId)
  if (isExpanded(key)) {
    expandedKps.value = expandedKps.value.filter((item) => item !== key)
    return
  }
  expandedKps.value = [...expandedKps.value, key]
  if (!questionsByKp.value.has(key)) await loadKpQuestions(materialId, kpId)
}

const toggleSelect = (q: QuestionBankItem) => {
  if (!q.selectable) return
  selectedIds.value = selectedIds.value.includes(q.id)
    ? selectedIds.value.filter((id) => id !== q.id)
    : [...selectedIds.value, q.id]
}

const startSelectedPractice = async () => {
  if (isStarting.value || selectedIds.value.length === 0) return
  isStarting.value = true
  try {
    const ids = selectedIds.value.slice(0, MAX_PRACTICE_QUESTIONS)
    const session = await apiCreatePractice({
      title: `讲义考点练习 · ${ids.length} 题`,
      question_ids: ids,
      question_count: ids.length,
    })
    if (!session?.id) {
      safeShowToast('创建练习失败，请重试')
      return
    }
    uni.navigateTo({
      url: `/subpackages/practice/pages/session/index?practice_id=${session.id}`,
      fail: () => safeShowToast('打开练习失败，请重试'),
    })
  } catch (err) {
    safeShowToast(extractUserErrorMessage(err, '创建练习失败'))
  } finally {
    isStarting.value = false
  }
}

const resetState = () => {
  groupedEpoch += 1
  materials.value = []
  loadError.value = ''
  isLoading.value = false
  expandedKps.value = []
  questionsByKp.value = new Map()
  loadingKps.value = []
  kpErrors.value = new Map()
  selectedIds.value = []
  cache.resetCache()
}

defineExpose({ refresh: loadSummary, resetState })
</script>

<style lang="scss" scoped>
@import '../questionBank.scss';

.grp-mat-card { padding: 24rpx 26rpx; margin-bottom: 20rpx; }
.grp-mat-head { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; margin-bottom: 14rpx; }
.grp-mat-titles { display: flex; align-items: center; gap: 10rpx; flex-wrap: wrap; flex: 1; min-width: 0; }
.grp-mat-title { font-size: 28rpx; font-weight: 700; color: var(--color-ink-primary); }
.grp-folder-pill { font-size: 20rpx; padding: 2rpx 10rpx; border-radius: 6rpx; background: var(--color-surface-muted); color: var(--color-ink-subtle); }
.grp-mat-count { font-size: 22rpx; color: var(--color-ink-muted); flex-shrink: 0; }
.grp-kp-list { display: flex; flex-direction: column; gap: 10rpx; }
.grp-kp-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12rpx;
  padding: 14rpx 18rpx; border-radius: 10rpx; background: var(--color-surface-subtle); border: 1px solid var(--color-paper-border);
}
.grp-kp-row.active { background: var(--color-blue-bg); border-color: var(--color-blue-border); }
.grp-kp-name { flex: 1; min-width: 0; font-size: 25rpx; font-weight: 600; color: var(--color-ink-primary); }
.grp-kp-right { display: flex; align-items: center; gap: 12rpx; flex-shrink: 0; }
.grp-kp-count { font-size: 22rpx; color: var(--color-ink-subtle); }
.grp-kp-arrow { font-size: 22rpx; color: var(--color-academic-blue); font-weight: 600; }
.grp-q-list { padding: 6rpx 4rpx 4rpx; }
</style>
