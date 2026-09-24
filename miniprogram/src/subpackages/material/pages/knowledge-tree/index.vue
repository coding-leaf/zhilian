<template>
  <view class="knowledge-tree-page">
    <view v-if="hasLowConfidenceWarning" class="low-confidence-banner">
      <wd-icon name="warn-bold" size="32rpx" custom-class="banner-icon" />
      <text class="banner-text">检测到部分知识点抽取可信度较低，已自动降级</text>
    </view>

    <!-- 资料概览统计卡片 -->
    <view class="overview-card">
      <view class="material-header">
        <text class="material-title">{{ materialTitle }}</text>
      </view>
      <view class="stats-grid">
        <view class="stat-item">
          <text class="stat-num">{{ totalNodesCount }}</text>
          <text class="stat-label">知识点总数</text>
        </view>
        <view class="stat-item">
          <text class="stat-num">{{ selectedCount }}</text>
          <text class="stat-label">已选考点</text>
        </view>
        <view class="stat-item">
          <text class="stat-num">{{ coveragePercentage }}%</text>
          <text class="stat-label">覆盖率</text>
        </view>
      </view>
    </view>

    <!-- 视图模式切换 -->
    <view v-if="generatedQuestions.length > 0" class="view-tabs">
      <button class="tab-btn" :class="{ active: currentTab === 'tree' }" @tap="currentTab = 'tree'">
        知识架构树
      </button>
      <button
        class="tab-btn"
        :class="{ active: currentTab === 'questions' }"
        @tap="currentTab = 'questions'"
      >
        题目列表 ({{ generatedQuestions.length }})
      </button>
    </view>

    <!-- 考点树视图 -->
    <template v-if="currentTab === 'tree'">
      <view class="toolbar-card">
        <view class="toolbar-left">
          <text class="section-heading">知识架构树</text>
        </view>
        <view class="toolbar-actions">
          <button class="tool-btn" @tap="handleSelectAll">全选</button>
          <button class="tool-btn" @tap="handleClearSelection">清空</button>
        </view>
      </view>

      <view class="tree-container">
        <view v-if="loading" class="loading-state">
          <wd-loading size="40rpx" />
          <text class="state-text">正在加载知识点树...</text>
        </view>
        <view v-else-if="rootNodes.length === 0" class="empty-state">
          <wd-icon name="info" size="64rpx" color="var(--color-gray-5)" />
          <text class="state-text">暂无知识点数据</text>
        </view>
        <view v-else class="tree-list">
          <KnowledgeTreeNode
            v-for="node in rootNodes"
            :key="node.id"
            :node="node"
            :level="1"
            :selected-ids="materialStore.selectedKnowledgeIds"
            :collapsed-map="materialStore.knowledgeTreeCollapsedMap"
            @toggle-select="handleToggleSelect"
            @toggle-collapse="handleToggleCollapse"
          />
        </view>
      </view>
    </template>

    <!-- 题目预览列表视图 -->
    <view v-else class="questions-container">
      <view v-for="q in generatedQuestions" :key="q.id" class="question-card">
        <view class="q-header">
          <text class="q-type-badge">{{ formatQuestionType(q.question_type) }}</text>
          <text class="q-difficulty">难度 {{ q.difficulty }}</text>
        </view>
        <text class="q-stem">{{ q.stem }}</text>
        <view class="q-answer-box">
          <text class="ans-label">参考答案：</text>
          <text class="ans-content">{{ q.answer }}</text>
        </view>
        <view class="q-actions">
          <button class="action-btn primary" @tap="handleOpenEdit(q)">编辑</button>
          <button class="action-btn" @tap="handleOpenAudit(q.id)">修改痕迹</button>
          <button class="action-btn danger" @tap="handleDeleteQuestion(q.id)">删除</button>
        </view>
      </view>
    </view>

    <!-- 底部吸底操作栏 -->
    <view class="bottom-action-bar">
      <view class="selection-summary">
        <text class="summary-text">
          已选择
          <text class="highlight-count">{{ selectedCount }}</text>
          项考点
        </text>
        <text class="coverage-text">考点覆盖率 {{ coveragePercentage }}%</text>
      </view>
      <button
        class="primary-action-btn"
        :class="{ disabled: selectedCount === 0 }"
        :disabled="selectedCount === 0"
        @tap="handleGenerateQuestions"
      >
        生成题目
      </button>
    </view>

    <!-- 抽屉挂载 -->
    <QuestionConfigDrawer
      :visible="isConfigDrawerOpen"
      :material-id="targetMaterialId"
      :selected-knowledge-ids="materialStore.selectedKnowledgeIds"
      @success="handleGenerateSuccess"
      @close="isConfigDrawerOpen = false"
    />
    <QuestionEditDrawer
      :visible="isEditDrawerOpen"
      :question="editingQuestion"
      @updated="handleQuestionUpdated"
      @close="isEditDrawerOpen = false"
    />
    <QuestionAuditDrawer
      :visible="isAuditDrawerOpen"
      :question-id="auditingQuestionId"
      @close="isAuditDrawerOpen = false"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { onLoad } from '@dcloudio/uni-app';
import { useMaterialStore } from '@/stores/materialStore';
import { fetchKnowledgeTree, fetchMaterialDetail } from '@/api/material';
import { deleteQuestion } from '@/api/question';
import type { QuestionItem } from '@/types/question';
import { flattenKnowledgeTree, calculateKnowledgeCoverage } from '../../utils/tree';
import KnowledgeTreeNode from '../../components/KnowledgeTreeNode.vue';
import QuestionConfigDrawer from '../../components/QuestionConfigDrawer.vue';
import QuestionEditDrawer from '../../components/QuestionEditDrawer.vue';
import QuestionAuditDrawer from '../../components/QuestionAuditDrawer.vue';

interface Props {
  materialId?: string;
  id?: string;
}

const props = defineProps<Props>();
const materialStore = useMaterialStore();
const targetMaterialId = ref<string>('');
const materialTitle = ref<string>('学习资料考点大纲');
const loading = ref<boolean>(false);
const currentTab = ref<'tree' | 'questions'>('tree');
const generatedQuestions = ref<QuestionItem[]>([]);
const isConfigDrawerOpen = ref<boolean>(false);
const isEditDrawerOpen = ref<boolean>(false);
const isAuditDrawerOpen = ref<boolean>(false);
const editingQuestion = ref<QuestionItem | null>(null);
const auditingQuestionId = ref<string>('');

const rootNodes = computed(() => materialStore.currentKnowledgeTree);
const allFlatNodes = computed(() => flattenKnowledgeTree(materialStore.currentKnowledgeTree));
const totalNodesCount = computed<number>(() => allFlatNodes.value.length);
const selectedCount = computed<number>(() => materialStore.selectedCount);
const coveragePercentage = computed<number>(() =>
  calculateKnowledgeCoverage(
    materialStore.currentKnowledgeTree,
    materialStore.selectedKnowledgeIds,
  ),
);
const hasLowConfidenceWarning = computed<boolean>(() => materialStore.hasLowConfidenceNode);

async function loadKnowledgeTree(id: string): Promise<void> {
  if (!id) return;
  loading.value = true;
  try {
    const res = await fetchKnowledgeTree(id);
    if (res.data?.nodes) materialStore.setKnowledgeTree(res.data.nodes);
  } catch {
    uni.showToast({ title: '加载知识点树失败', icon: 'none' });
  } finally {
    loading.value = false;
  }
}

async function loadMaterialInfo(id: string): Promise<void> {
  if (!id) return;
  if (materialStore.currentMaterial?.title) {
    materialTitle.value = materialStore.currentMaterial.title;
    return;
  }
  try {
    const res = await fetchMaterialDetail(id);
    if (res.data?.title) materialTitle.value = res.data.title;
  } catch {
    // Preserve default
  }
}

const handleToggleSelect = (id: string): void => materialStore.toggleKnowledgeSelection(id);
const handleToggleCollapse = (id: string): void => materialStore.toggleNodeCollapse(id);
const handleSelectAll = (): void => {
  materialStore.selectAllKnowledge(allFlatNodes.value.map((n) => n.id));
};
const handleClearSelection = (): void => materialStore.clearKnowledgeSelection();

function handleGenerateQuestions(): void {
  if (selectedCount.value === 0) {
    uni.showToast({ title: '请至少选择一个知识点', icon: 'none' });
    return;
  }
  uni.showToast({ title: `已就绪 ${selectedCount.value} 个知识点`, icon: 'none' });
  isConfigDrawerOpen.value = true;
}

function handleGenerateSuccess(questions: QuestionItem[]): void {
  generatedQuestions.value = [...questions, ...generatedQuestions.value];
  currentTab.value = 'questions';
}

function handleOpenEdit(q: QuestionItem): void {
  editingQuestion.value = q;
  isEditDrawerOpen.value = true;
}

function handleOpenAudit(questionId: string): void {
  auditingQuestionId.value = questionId;
  isAuditDrawerOpen.value = true;
}

function handleQuestionUpdated(updated: QuestionItem): void {
  const idx = generatedQuestions.value.findIndex((item) => item.id === updated.id);
  if (idx !== -1) generatedQuestions.value[idx] = updated;
}

function handleDeleteQuestion(questionId: string): void {
  uni.showModal({
    title: '确认删除',
    content: '确定要删除该题目吗？此操作将记录入不可变审计历史。',
    success: async (res) => {
      if (res.confirm) {
        try {
          await deleteQuestion(questionId, '用户手动删除');
          generatedQuestions.value = generatedQuestions.value.filter((q) => q.id !== questionId);
          uni.showToast({ title: '已删除题目', icon: 'success' });
        } catch {
          uni.showToast({ title: '删除失败，请重试', icon: 'none' });
        }
      }
    },
  });
}

function formatQuestionType(type?: string): string {
  const map: Record<string, string> = {
    single_choice: '单选题',
    multiple_choice: '多选题',
    true_false: '判断题',
    fill_in_blank: '填空题',
    short_answer: '主观简答题',
  };
  return (type && map[type]) || type || '题目';
}

function initData(id?: string): void {
  if (id && !targetMaterialId.value) {
    targetMaterialId.value = id;
    materialStore.setActiveMaterial(id);
    void loadKnowledgeTree(id);
    void loadMaterialInfo(id);
  }
}

onMounted(() => initData(props.materialId || props.id));
onLoad((q?: { material_id?: string; materialId?: string; id?: string }) => {
  initData(q?.material_id || q?.materialId || q?.id || props.materialId || props.id);
});
</script>

<style lang="scss" scoped>
@import './knowledge-tree.scss';
</style>
