<template>
  <view class="questions-container">
    <!-- 顶部配置或核对概览 -->
    <view class="page-header">
      <text class="page-title">{{ isConfigMode ? '智能组卷与出题配置' : '核对生成题目' }}</text>
      <text class="page-subtitle">
        {{ isConfigMode ? '勾选考点、指定题型与难度，生成针对性批次练习' : `已生成 ${questions.length} 道针对性测验题，核对后开始答题` }}
      </text>
    </view>

    <!-- 配置模式：知识点勾选、题型选择、难度与题量 -->
    <view v-if="isConfigMode" class="config-section">
      <!-- 知识点勾选 -->
      <view class="paper-card form-card">
        <view class="card-header-row">
          <text class="card-label">1. 考点范围 ({{ selectedKpIds.length }} 已选)</text>
          <text class="select-all-btn" @tap="toggleSelectAllKp">
            {{ isAllKpSelected ? '取消全选' : '全部全选' }}
          </text>
        </view>

        <view v-if="availableKpList.length > 0" class="kp-chips-group">
          <view
            v-for="kp in availableKpList"
            :key="kp.id"
            :class="['kp-chip', isKpSelected(kp.id) ? 'active' : '']"
            @tap="toggleKp(kp.id)"
          >
            <text class="kp-chip-text">{{ kp.name }}</text>
            <text v-if="isKpSelected(kp.id)" class="kp-check">✓</text>
          </view>
        </view>
        <view v-else class="empty-kp">
          <text class="empty-kp-text">正在拉取考点列表中...</text>
        </view>
      </view>

      <!-- 题型勾选 -->
      <view class="paper-card form-card">
        <text class="card-label">2. 测验题型多选</text>
        <view class="type-chips-group">
          <view
            v-for="t in typeOptions"
            :key="t.value"
            :class="['type-chip', isTypeSelected(t.value) ? 'active' : '']"
            @tap="toggleType(t.value)"
          >
            <text class="type-chip-text">{{ t.label }}</text>
            <text v-if="isTypeSelected(t.value)" class="type-check">✓</text>
          </view>
        </view>
      </view>

      <!-- 题量与难度 -->
      <view class="paper-card form-card">
        <text class="card-label">3. 题量与难度设置</text>

        <view class="setting-row">
          <text class="setting-title">题目数量：{{ questionCount }} 题</text>
          <slider
            :value="questionCount"
            :min="1"
            :max="15"
            :step="1"
            active-color="#1E3A8A"
            :block-size="20"
            @change="onCountChange"
          />
        </view>

        <view class="setting-row">
          <text class="setting-title">难度等级：{{ difficultyText(difficulty) }} ({{ difficulty }}/5)</text>
          <slider
            :value="difficulty"
            :min="1"
            :max="5"
            :step="1"
            active-color="#1E3A8A"
            :block-size="20"
            @change="onDifficultyChange"
          />
        </view>
      </view>

      <view class="config-action-bar">
        <button
          class="paper-btn-primary full-btn"
          :loading="isGenerating"
          :disabled="selectedKpIds.length === 0 || selectedTypes.length === 0 || isGenerating"
          @tap="handleGenerateQuestions"
        >
          {{ isGenerating ? 'AI 正在组卷中...' : `一键智能出题 (${selectedKpIds.length} 考点)` }}
        </button>
      </view>
    </view>

    <!-- 题目核对与开始作答模式 -->
    <view v-else class="preview-section">
      <view class="questions-list">
        <view
          v-for="(q, idx) in questions"
          :key="q.id || idx"
          class="paper-card question-card"
        >
          <view class="q-header">
            <text class="q-num">第 {{ idx + 1 }} 题</text>
            <view class="q-meta-badges">
              <text class="q-type">{{ getTypeText(q.type) }}</text>
              <text v-if="q.difficulty" class="q-diff">难度 {{ q.difficulty }}</text>
            </view>
          </view>

          <text class="q-stem">{{ q.stem }}</text>

          <!-- 选项预览 (选择题) -->
          <view v-if="q.options && q.options.length" class="q-options">
            <view
              v-for="(opt, optIdx) in q.options"
              :key="optIdx"
              class="option-item"
            >
              <text class="option-index">{{ String.fromCharCode(65 + optIdx) }}.</text>
              <text class="option-text">{{ opt }}</text>
            </view>
          </view>

          <!-- 来源依据锚点 -->
          <view v-if="q.source_quote" class="source-box">
            <text class="source-tag">📖 讲义依据切片：</text>
            <text class="source-text">{{ q.source_quote }}</text>
          </view>
        </view>
      </view>

      <!-- 底部固定行动栏 -->
      <view class="bottom-action-bar">
        <button class="reconfig-btn" @tap="isConfigMode = true">重新调整</button>
        <button class="paper-btn-primary start-btn" :loading="isStarting" @tap="handleStartPractice">
          开始作答 ({{ questions.length }} 题)
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useMaterialStore } from '@/stores/material'
import { usePracticeStore } from '@/stores/practice'
import { useFolderStore } from '@/stores/folder'
import type { QuestionItem, FolderKnowledgePointItem } from '@/types'

const materialStore = useMaterialStore()
const practiceStore = usePracticeStore()
const folderStore = useFolderStore()

const materialId = ref<string>('')
const folderId = ref<string>('')
const isConfigMode = ref<boolean>(true)
const isGenerating = ref<boolean>(false)
const isStarting = ref<boolean>(false)

const availableKpList = ref<Array<{ id: string; name: string }>>([])
const selectedKpIds = ref<string[]>([])

const typeOptions = [
  { label: '单项选择', value: 'single_choice' },
  { label: '多项选择', value: 'multiple_choice' },
  { label: '判断正误', value: 'true_false' },
  { label: '填空题', value: 'fill_in_blank' },
  { label: '简答/分析题', value: 'short_answer' },
]

const selectedTypes = ref<string[]>([
  'single_choice',
  'multiple_choice',
  'true_false',
  'short_answer',
])

const questionCount = ref<number>(5)
const difficulty = ref<number>(3)

const questions = ref<QuestionItem[]>([])

const isAllKpSelected = computed(() => {
  return (
    availableKpList.value.length > 0 &&
    selectedKpIds.value.length === availableKpList.value.length
  )
})

onLoad(async (options) => {
  if (options && options.folder_id) {
    folderId.value = options.folder_id
    await loadKpFromFolder(options.folder_id)
  } else if (options && options.material_id) {
    materialId.value = options.material_id
    await loadKpFromMaterial(options.material_id)
  }
})

const loadKpFromFolder = async (fId: string) => {
  uni.showLoading({ title: '加载课程考点...' })
  try {
    const res = await folderStore.loadFolderKnowledgePoints(fId)
    const list: Array<{ id: string; name: string }> = []
    for (const g of res.groups || []) {
      for (const kp of g.knowledge_points || []) {
        list.push({ id: kp.id, name: kp.name })
      }
    }
    availableKpList.value = list
    // 默认全选
    selectedKpIds.value = list.map((k) => k.id)
  } finally {
    uni.hideLoading()
  }
}

const loadKpFromMaterial = async (mId: string) => {
  uni.showLoading({ title: '加载讲义考点...' })
  try {
    const tree = await materialStore.loadKnowledgeTree(mId)
    if (tree && tree.nodes) {
      const list: Array<{ id: string; name: string }> = []
      const walk = (nodes: any[]) => {
        for (const n of nodes) {
          list.push({ id: n.id, name: n.name })
          if (n.children && n.children.length) walk(n.children)
        }
      }
      walk(tree.nodes)
      availableKpList.value = list
      selectedKpIds.value = list.map((k) => k.id)
    }
  } finally {
    uni.hideLoading()
  }
}

const isKpSelected = (id: string) => selectedKpIds.value.includes(id)
const toggleKp = (id: string) => {
  if (isKpSelected(id)) {
    selectedKpIds.value = selectedKpIds.value.filter((k) => k !== id)
  } else {
    selectedKpIds.value.push(id)
  }
}

const toggleSelectAllKp = () => {
  if (isAllKpSelected.value) {
    selectedKpIds.value = []
  } else {
    selectedKpIds.value = availableKpList.value.map((k) => k.id)
  }
}

const isTypeSelected = (t: string) => selectedTypes.value.includes(t)
const toggleType = (t: string) => {
  if (isTypeSelected(t)) {
    if (selectedTypes.value.length === 1) {
      uni.showToast({ title: '至少选择一种题型', icon: 'none' })
      return
    }
    selectedTypes.value = selectedTypes.value.filter((val) => val !== t)
  } else {
    selectedTypes.value.push(t)
  }
}

const onCountChange = (e: any) => {
  questionCount.value = e.detail.value
}

const onDifficultyChange = (e: any) => {
  difficulty.value = e.detail.value
}

const difficultyText = (diff: number) => {
  switch (diff) {
    case 1: return '极简入门'
    case 2: return '基础巩固'
    case 3: return '进阶综合'
    case 4: return '高阶拓展'
    case 5: return '硬核挑战'
    default: return '适中'
  }
}

const getTypeText = (type: string) => {
  switch (type) {
    case 'single_choice': return '单选题'
    case 'multiple_choice': return '多选题'
    case 'true_false': return '判断题'
    case 'fill_in_blank': return '填空题'
    case 'short_answer': return '简答题'
    case 'case_analysis': return '案例分析'
    default: return '试题'
  }
}

const handleGenerateQuestions = async () => {
  if (selectedKpIds.value.length === 0) {
    uni.showToast({ title: '请至少勾选一个知识点', icon: 'none' })
    return
  }
  isGenerating.value = true
  uni.showLoading({ title: 'AI 严密出题中...' })
  try {
    const res = await materialStore.generateQuestions({
      folder_id: folderId.value || undefined,
      material_id: materialId.value || undefined,
      knowledge_point_ids: selectedKpIds.value,
      question_types: selectedTypes.value,
      count: questionCount.value,
      difficulty: difficulty.value,
    })
    questions.value = res || []
    uni.hideLoading()
    if (questions.value.length > 0) {
      isConfigMode.value = false
    } else {
      uni.showToast({ title: '生成题目不足，请重试', icon: 'none' })
    }
  } catch (err: any) {
    uni.hideLoading()
    uni.showToast({ title: err?.message || '生成失败', icon: 'none' })
  } finally {
    isGenerating.value = false
  }
}

const handleStartPractice = async () => {
  isStarting.value = true
  uni.showLoading({ title: '准备考场中...' })
  try {
    const qIds = questions.value.map((q) => q.id)
    await practiceStore.initPractice(undefined, {
      title: folderId.value ? '课程针对性测验' : '讲义专题测验',
      folder_id: folderId.value || undefined,
      material_id: materialId.value || undefined,
      knowledge_point_ids: selectedKpIds.value,
      question_ids: qIds.length > 0 ? qIds : undefined,
    })
    uni.hideLoading()
    uni.navigateTo({
      url: `/subpackages/practice/pages/session/index`,
    })
  } catch (err: any) {
    uni.hideLoading()
    uni.showToast({ title: err?.message || '初始化练习失败', icon: 'none' })
  } finally {
    isStarting.value = false
  }
}
</script>

<style scoped>
.questions-container {
  padding: 32rpx;
  padding-bottom: 180rpx;
  min-height: 100vh;
}

.page-header {
  margin-bottom: 32rpx;
}

.page-title {
  display: block;
  font-size: 38rpx;
  font-weight: 700;
  color: #1c1917;
  margin-bottom: 8rpx;
}

.page-subtitle {
  display: block;
  font-size: 24rpx;
  color: #78716c;
}

.form-card {
  padding: 32rpx;
  margin-bottom: 24rpx;
}

.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20rpx;
}

.card-label {
  font-size: 28rpx;
  font-weight: 700;
  color: #1c1917;
  display: block;
  margin-bottom: 16rpx;
}

.select-all-btn {
  font-size: 24rpx;
  color: #1e3a8a;
  font-weight: 600;
}

.kp-chips-group,
.type-chips-group {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}

.kp-chip,
.type-chip {
  padding: 12rpx 24rpx;
  border-radius: 24rpx;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
  display: flex;
  align-items: center;
  gap: 8rpx;
  transition: all 0.2s;
}

.kp-chip.active,
.type-chip.active {
  background: #eff6ff;
  border-color: #1e3a8a;
}

.kp-chip-text,
.type-chip-text {
  font-size: 24rpx;
  color: #44403c;
}

.kp-chip.active .kp-chip-text,
.type-chip.active .type-chip-text {
  color: #1e3a8a;
  font-weight: 600;
}

.kp-check,
.type-check {
  font-size: 20rpx;
  color: #1e3a8a;
  font-weight: 700;
}

.setting-row {
  margin-top: 20rpx;
}

.setting-title {
  display: block;
  font-size: 24rpx;
  color: #57534e;
  margin-bottom: 12rpx;
}

.config-action-bar {
  margin-top: 48rpx;
}

.full-btn {
  height: 92rpx;
  font-size: 32rpx;
}

/* 预览卡片 */
.question-card {
  padding: 32rpx;
  margin-bottom: 24rpx;
}

.q-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.q-num {
  font-size: 26rpx;
  font-weight: 600;
  color: #1e3a8a;
}

.q-meta-badges {
  display: flex;
  gap: 12rpx;
}

.q-type,
.q-diff {
  font-size: 22rpx;
  background: #f5f5f4;
  color: #78716c;
  padding: 4rpx 12rpx;
  border-radius: 4rpx;
}

.q-stem {
  display: block;
  font-size: 30rpx;
  color: #1c1917;
  line-height: 1.6;
  font-weight: 500;
  margin-bottom: 20rpx;
}

.option-item {
  display: flex;
  padding: 12rpx 0;
  font-size: 28rpx;
  color: #44403c;
}

.option-index {
  font-weight: 600;
  margin-right: 12rpx;
  color: #78716c;
}

.option-text {
  flex: 1;
}

.source-box {
  margin-top: 20rpx;
  padding: 16rpx 20rpx;
  background: #fafaf9;
  border-left: 4rpx solid #1e3a8a;
  border-radius: 4rpx;
}

.source-tag {
  font-size: 22rpx;
  font-weight: 600;
  color: #1e3a8a;
  display: block;
  margin-bottom: 4rpx;
}

.source-text {
  font-size: 24rpx;
  color: #78716c;
  line-height: 1.5;
}

.bottom-action-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  gap: 20rpx;
  padding: 24rpx 32rpx;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-top: 1px solid #e7e5e4;
  box-shadow: 0 -4rpx 16rpx rgba(0, 0, 0, 0.04);
}

.reconfig-btn {
  width: 220rpx;
  height: 88rpx;
  background: #f5f5f4;
  color: #57534e;
  font-size: 28rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.start-btn {
  flex: 1;
  height: 88rpx;
  font-size: 32rpx;
}
</style>

