<template>
  <view class="questions-page">
    <view class="page-summary">
      <text class="summary-title">题目列表</text>
      <text class="summary-count">共 {{ total }} 题</text>
    </view>

    <view v-if="loading && listData.length === 0" class="state-block">
      <wd-loading size="40rpx" />
      <text class="state-text">正在加载题目...</text>
    </view>

    <!-- 空态：按范围给出引导 -->
    <view v-else-if="listData.length === 0" class="state-block empty-state">
      <wd-icon name="info" size="64rpx" color="var(--color-gray-5)" />
      <text class="state-title">{{ emptyCopy.title }}</text>
      <text class="state-desc">{{ emptyCopy.desc }}</text>
      <button class="empty-action-btn" @tap="handleEmptyAction">{{ emptyCopy.action }}</button>
    </view>

    <view v-else class="questions-container">
      <view v-if="activeBatchId" class="batch-filter-bar">
        <text class="batch-filter-text">仅看 {{ activeBatchLabel }}</text>
        <text class="batch-filter-clear" @tap="handleClearBatchFilter">显示全部批次</text>
      </view>

      <view v-for="group in groupedListData" :key="group.batchId || 'unknown'" class="batch-group">
        <view class="batch-head" @tap="handleToggleBatchFilter(group.batchId)">
          <text class="batch-label">{{ group.label }}</text>
          <text class="batch-count">{{ group.items.length }} 题</text>
        </view>
        <QuestionCard
          v-for="item in group.items"
          :key="item.id"
          :question="item"
          @edit="handleOpenEdit"
          @audit="handleOpenAudit"
          @delete="handleDeleteQuestion"
        />
      </view>

      <view class="load-more">
        <text v-if="loading" class="load-more-text">正在加载更多...</text>
        <text v-else-if="hasMore" class="load-more-btn" @tap="handleLoadMore">加载更多</text>
        <text v-else class="load-more-text">已加载全部题目</text>
      </view>

      <view v-if="isFolderScope" class="bottom-bar-placeholder" />
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

    <!-- 课程范围吸底「开始答题」 -->
    <PracticeStartBar
      v-if="isFolderScope && listData.length > 0"
      :total="total"
      :starting="starting"
      @start="handleStartPractice"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { onLoad, onShow, onReachBottom } from '@dcloudio/uni-app';
import { fetchQuestionList, deleteQuestion } from '@/api/question';
import { createPractice } from '@/api/practice';
import { usePracticeStore } from '@/stores/practiceStore';
import type { QuestionItem, QuestionListQueryParams, QuestionType } from '@/types/question';
import QuestionCard from '../../components/QuestionCard.vue';
import QuestionEditDrawer from '../../components/QuestionEditDrawer.vue';
import QuestionAuditDrawer from '../../components/QuestionAuditDrawer.vue';
import PracticeStartBar from '@/components/course/PracticeStartBar.vue';
import { resolveQuestionListEmptyCopy } from '../../utils/questionGeneration';
import { formatBatchLabel, groupQuestionsByBatch } from '../../utils/questionBatch';

interface QuestionPageQuery {
  material_id?: string;
  materialId?: string;
  folder_id?: string;
  folderId?: string;
  id?: string;
}

interface Props {
  materialId?: string;
  folderId?: string;
  id?: string;
}

const props = defineProps<Props>();

const practiceStore = usePracticeStore();

const PRACTICE_QUESTION_TYPES: QuestionType[] = [
  'single_choice',
  'multiple_choice',
  'true_false',
  'short_answer',
];

const targetMaterialId = ref<string>('');
const targetFolderId = ref<string>('');
const listData = ref<QuestionItem[]>([]);
const page = ref<number>(1);
const pageSize = 20;
const total = ref<number>(0);
const loading = ref<boolean>(false);
const starting = ref<boolean>(false);
const isEditDrawerOpen = ref<boolean>(false);
const isAuditDrawerOpen = ref<boolean>(false);
const editingQuestion = ref<QuestionItem | null>(null);
const auditingQuestionId = ref<string>('');
const activeBatchId = ref<string>('');

const hasMore = computed<boolean>(() => listData.value.length < total.value);
const isFolderScope = computed<boolean>(() => !!targetFolderId.value);
const emptyCopy = computed(() => resolveQuestionListEmptyCopy(isFolderScope.value));
const groupedListData = computed(() => groupQuestionsByBatch(listData.value));
const activeBatchLabel = computed(() => formatBatchLabel(activeBatchId.value));

async function loadQuestions(reset = false): Promise<void> {
  if ((!targetMaterialId.value && !targetFolderId.value) || loading.value) return;
  if (reset) page.value = 1;
  loading.value = true;
  try {
    const params: QuestionListQueryParams = { page: page.value, page_size: pageSize };
    if (targetFolderId.value) {
      params.folder_id = targetFolderId.value;
    } else {
      params.material_id = targetMaterialId.value;
    }
    if (activeBatchId.value) {
      params.batch_id = activeBatchId.value;
    }
    const res = await fetchQuestionList(params);
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

async function handleStartPractice(): Promise<void> {
  if (starting.value || !targetFolderId.value || total.value === 0) return;
  starting.value = true;
  try {
    const res = await createPractice({
      title: '课程练习',
      folder_id: targetFolderId.value,
      question_count: Math.min(total.value, 20),
      question_types: PRACTICE_QUESTION_TYPES,
      mode: 'sequential',
    });
    const session = res?.data;
    if (!session?.id) {
      uni.showToast({ title: '组卷失败，请重试', icon: 'none' });
      return;
    }
    practiceStore.initSession(session.id, session.questions || [], {
      title: session.title,
      folder_id: targetFolderId.value,
    });
    uni.navigateTo({
      url: `/subpackages/practice/pages/session/index?id=${session.id}`,
      fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
    });
  } catch {
    uni.showToast({ title: '组卷失败，请重试', icon: 'none' });
  } finally {
    starting.value = false;
  }
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
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

function handleGoCourseGenerate(): void {
  if (!targetFolderId.value) return;
  uni.navigateTo({
    url: `/subpackages/material/pages/course/index?folder_id=${targetFolderId.value}`,
    fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
  });
}

function handleEmptyAction(): void {
  if (isFolderScope.value) {
    handleGoCourseGenerate();
    return;
  }
  handleGoKnowledgeTree();
}

function handleToggleBatchFilter(batchId: string | null): void {
  if (!batchId) return;
  activeBatchId.value = activeBatchId.value === batchId ? '' : batchId;
  void loadQuestions(true);
}

function handleClearBatchFilter(): void {
  if (!activeBatchId.value) return;
  activeBatchId.value = '';
  void loadQuestions(true);
}

let hasEntered = false;

function initPage(query?: QuestionPageQuery): void {
  if (targetMaterialId.value || targetFolderId.value) return;
  const folder = query?.folder_id || query?.folderId || props.folderId || '';
  const material =
    query?.material_id || query?.materialId || query?.id || props.materialId || props.id || '';
  if (folder) {
    targetFolderId.value = folder;
  } else if (material) {
    targetMaterialId.value = material;
  } else {
    return;
  }
  void loadQuestions(true);
}

onLoad((q?: QuestionPageQuery) => initPage(q));
onShow(() => {
  if (!hasEntered) {
    hasEntered = true;
    return;
  }
  if (targetMaterialId.value || targetFolderId.value) void loadQuestions(true);
});
onReachBottom(() => handleLoadMore());

defineExpose({
  targetMaterialId,
  targetFolderId,
  isFolderScope,
  listData,
  loading,
  starting,
  total,
  hasMore,
  groupedListData,
  activeBatchId,
  loadQuestions,
  handleLoadMore,
  handleToggleBatchFilter,
  handleClearBatchFilter,
  handleStartPractice,
  handleOpenEdit,
  handleOpenAudit,
  handleQuestionUpdated,
  handleDeleteQuestion,
  handleGoKnowledgeTree,
  handleGoCourseGenerate,
  handleEmptyAction,
  initPage,
});
</script>

<style lang="scss" scoped>
@import './questions.scss';
</style>
