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
        <text class="material-link" @tap="handleGoQuestionList">查看题目列表</text>
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

    <!-- 考点树视图（题目统一在独立题目页查看，避免双数据源） -->
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
      <view v-else-if="loadError" class="empty-state">
        <wd-icon name="info" size="64rpx" color="var(--color-gray-5)" />
        <text class="state-text">知识点树加载失败</text>
        <button class="tool-btn" @tap="handleRetryLoad">重新加载</button>
      </view>
      <view v-else-if="rootNodes.length === 0" class="empty-state">
        <wd-icon name="info" size="64rpx" color="var(--color-gray-5)" />
        <text class="state-text">暂无知识点数据</text>
      </view>
      <view v-else class="tree-list">
        <KnowledgeTreeNode
          v-for="row in visibleRows"
          :key="row.node.id"
          :node="row.node"
          :level="row.depth"
          :selected-ids="materialStore.selectedKnowledgeIds"
          :collapsed-map="materialStore.knowledgeTreeCollapsedMap"
          :check-status-map="checkStatusMap"
          @toggle-select="handleToggleSelect"
          @toggle-collapse="handleToggleCollapse"
        />
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

    <!-- 出题配置抽屉：成功后组件内直接跳转独立题目页 -->
    <QuestionConfigDrawer
      :visible="isConfigDrawerOpen"
      :material-id="targetMaterialId"
      :version-id="currentVersionId"
      :selected-knowledge-ids="materialStore.selectedKnowledgeIds"
      @close="isConfigDrawerOpen = false"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { onLoad } from '@dcloudio/uni-app';
import { useMaterialStore } from '@/stores/materialStore';
import { fetchKnowledgeTree, fetchMaterialDetail } from '@/api/material';
import {
  buildCheckStatusMap,
  flattenKnowledgeTree,
  flattenVisibleTree,
  calculateKnowledgeCoverage,
} from '../../utils/tree';
import KnowledgeTreeNode from '../../components/KnowledgeTreeNode.vue';
import QuestionConfigDrawer from '../../components/QuestionConfigDrawer.vue';

interface Props {
  materialId?: string;
  id?: string;
}

const props = defineProps<Props>();
const materialStore = useMaterialStore();
const targetMaterialId = ref<string>('');
const currentVersionId = ref<string>('');
const materialTitle = ref<string>('学习资料考点大纲');
const loading = ref<boolean>(false);
const loadError = ref<boolean>(false);
const isConfigDrawerOpen = ref<boolean>(false);

const rootNodes = computed(() => materialStore.currentKnowledgeTree);
const visibleRows = computed(() =>
  flattenVisibleTree(materialStore.currentKnowledgeTree, materialStore.knowledgeTreeCollapsedMap),
);
// 单次 O(N) 遍历预计算勾选状态，避免逐行重走子树（修复大树卡顿）。
const checkStatusMap = computed(() =>
  buildCheckStatusMap(
    materialStore.currentKnowledgeTree,
    new Set(materialStore.selectedKnowledgeIds),
  ),
);
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
    if (res.data?.version_id) {
      currentVersionId.value = res.data.version_id;
    }
    if (res.data?.nodes) materialStore.setKnowledgeTree(res.data.nodes);
    loadError.value = false;
  } catch {
    loadError.value = true;
    uni.showToast({ title: '加载知识点树失败', icon: 'none' });
  } finally {
    loading.value = false;
  }
}

function handleRetryLoad(): void {
  void loadKnowledgeTree(targetMaterialId.value);
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

const handleToggleSelect = (): void => {
  // 级联勾选状态由 KnowledgeTreeNode 内置的 toggleKnowledgeSubtree 管理
};
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

function handleGoQuestionList(): void {
  if (!targetMaterialId.value) {
    uni.showToast({ title: '缺少资料信息', icon: 'none' });
    return;
  }
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?material_id=${targetMaterialId.value}`,
    fail: () => {
      uni.showToast({ title: '题目页打开失败，请稍后重试', icon: 'none' });
    },
  });
}

function initData(id?: string): void {
  if (id && !targetMaterialId.value) {
    targetMaterialId.value = id;
    // Reset stale考点 selection/collapse state before loading a new material.
    materialStore.clearKnowledgeState();
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
