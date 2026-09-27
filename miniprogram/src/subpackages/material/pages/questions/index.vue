<template>
  <view class="questions-page">
    <view class="page-summary">
      <text class="summary-title">题目列表</text>
      <text class="summary-count">共 {{ total }} 题</text>
    </view>

    <!-- 首次加载态 -->
    <view v-if="loading && listData.length === 0" class="state-block">
      <wd-loading size="40rpx" />
      <text class="state-text">正在加载题目...</text>
    </view>

    <!-- 空态 -->
    <view v-else-if="listData.length === 0" class="state-block empty-state">
      <wd-icon name="info" size="64rpx" color="var(--color-gray-5)" />
      <text class="state-title">暂无题目，去知识树生成</text>
      <text class="state-desc">选择知识点并生成后，可在此核验出题效果</text>
      <button class="empty-action-btn" @tap="handleGoKnowledgeTree">去知识树生成</button>
    </view>

    <!-- 题目列表 -->
    <view v-else class="questions-container">
      <QuestionCard
        v-for="item in listData"
        :key="item.id"
        :question="item"
        @edit="handleOpenEdit"
        @audit="handleOpenAudit"
        @delete="handleDeleteQuestion"
      />

      <view class="load-more">
        <text v-if="loading" class="load-more-text">正在加载更多...</text>
        <text v-else-if="hasMore" class="load-more-btn" @tap="handleLoadMore">加载更多</text>
        <text v-else class="load-more-text">已加载全部题目</text>
      </view>
    </view>

    <!-- 复用抽屉组件 -->
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
import { ref, computed } from 'vue';
import { onLoad, onShow, onReachBottom } from '@dcloudio/uni-app';
import { fetchQuestionList, deleteQuestion } from '@/api/question';
import type { QuestionItem } from '@/types/question';
import QuestionCard from '../../components/QuestionCard.vue';
import QuestionEditDrawer from '../../components/QuestionEditDrawer.vue';
import QuestionAuditDrawer from '../../components/QuestionAuditDrawer.vue';

interface QuestionPageQuery {
  material_id?: string;
  materialId?: string;
  id?: string;
}

interface Props {
  materialId?: string;
  id?: string;
}

const props = defineProps<Props>();

const targetMaterialId = ref<string>('');
const listData = ref<QuestionItem[]>([]);
const page = ref<number>(1);
const pageSize = 20;
const total = ref<number>(0);
const loading = ref<boolean>(false);
const isEditDrawerOpen = ref<boolean>(false);
const isAuditDrawerOpen = ref<boolean>(false);
const editingQuestion = ref<QuestionItem | null>(null);
const auditingQuestionId = ref<string>('');

const hasMore = computed<boolean>(() => listData.value.length < total.value);

async function loadQuestions(reset = false): Promise<void> {
  if (!targetMaterialId.value || loading.value) return;
  if (reset) page.value = 1;
  loading.value = true;
  try {
    const res = await fetchQuestionList({
      material_id: targetMaterialId.value,
      page: page.value,
      page_size: pageSize,
    });
    const items: QuestionItem[] = res?.data?.items || [];
    total.value = res?.data?.total ?? items.length;
    if (reset) {
      listData.value = items;
    } else {
      const existingIds = new Set(listData.value.map((item) => item.id));
      listData.value = [...listData.value, ...items.filter((item) => !existingIds.has(item.id))];
    }
  } catch {
    // Roll back the incremented page on a failed load-more so the retry does not skip a page.
    if (!reset) page.value = Math.max(1, page.value - 1);
    uni.showToast({ title: '加载题目失败', icon: 'none' });
  } finally {
    loading.value = false;
  }
}

function handleLoadMore(): void {
  if (loading.value || !hasMore.value) return;
  page.value += 1;
  void loadQuestions(false);
}

function handleOpenEdit(question: QuestionItem): void {
  editingQuestion.value = question;
  isEditDrawerOpen.value = true;
}

function handleOpenAudit(questionId: string): void {
  auditingQuestionId.value = questionId;
  isAuditDrawerOpen.value = true;
}

function handleQuestionUpdated(updated: QuestionItem): void {
  const index = listData.value.findIndex((item) => item.id === updated.id);
  if (index !== -1) listData.value[index] = updated;
}

function handleDeleteQuestion(questionId: string): void {
  uni.showModal({
    title: '确认删除',
    content: '确定要删除该题目吗？此操作将记录入不可变审计历史。',
    success: async (res) => {
      if (!res.confirm) return;
      try {
        await deleteQuestion(questionId, '用户手动删除');
        listData.value = listData.value.filter((item) => item.id !== questionId);
        total.value = Math.max(0, total.value - 1);
        uni.showToast({ title: '已删除题目', icon: 'success' });
        // 删除后后端数据集整体前移，重置到第 1 页重新拉取当前可见深度，
        // 确保后续「加载更多」按真实 offset 请求，不跳过前移的题目。
        await loadQuestions(true);
      } catch {
        uni.showToast({ title: '删除失败，请重试', icon: 'none' });
      }
    },
  });
}

function handleGoKnowledgeTree(): void {
  if (!targetMaterialId.value) {
    uni.showToast({ title: '缺少资料信息', icon: 'none' });
    return;
  }
  uni.navigateTo({
    url: `/subpackages/material/pages/knowledge-tree/index?material_id=${targetMaterialId.value}`,
  });
}

let hasEntered = false;

function initPage(query?: QuestionPageQuery): void {
  if (targetMaterialId.value) return;
  const resolved =
    query?.material_id || query?.materialId || query?.id || props.materialId || props.id || '';
  if (!resolved) return;
  targetMaterialId.value = resolved;
  void loadQuestions(true);
}

onLoad((q?: QuestionPageQuery) => initPage(q));
onShow(() => {
  if (!hasEntered) {
    hasEntered = true;
    return;
  }
  if (targetMaterialId.value) void loadQuestions(true);
});
onReachBottom(() => handleLoadMore());

defineExpose({
  targetMaterialId,
  listData,
  loading,
  total,
  hasMore,
  loadQuestions,
  handleLoadMore,
  handleOpenEdit,
  handleOpenAudit,
  handleQuestionUpdated,
  handleDeleteQuestion,
  handleGoKnowledgeTree,
  initPage,
});
</script>

<style lang="scss" scoped>
@import './questions.scss';
</style>
