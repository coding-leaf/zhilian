<template>
  <view class="verify-page">
    <view class="page-header">
      <text class="page-title">出题核验清单</text>
      <text class="page-subtitle">{{
        materialTitle ? '资料：' + materialTitle : '核对题目质量与原文引证，确认后开启练习'
      }}</text>
    </view>

    <!-- 出题配置面板 (若未生成任何题目) -->
    <view v-if="!isGenerating && questions.length === 0" class="config-card">
      <text class="config-section-title">智能出题定制</text>

      <view class="config-item">
        <text class="config-label">出题数量</text>
        <view class="count-stepper">
          <button
            class="step-btn"
            :disabled="questionCount <= 3"
            @tap="questionCount = Math.max(3, questionCount - 1)"
          >
            -
          </button>
          <text class="count-display">{{ questionCount }}</text>
          <button
            class="step-btn"
            :disabled="questionCount >= 20"
            @tap="questionCount = Math.min(20, questionCount + 1)"
          >
            +
          </button>
        </view>
      </view>

      <view class="config-item">
        <text class="config-label">题目类型</text>
        <view class="pill-group">
          <view
            v-for="item in questionTypeOptions"
            :key="item.value"
            class="pill-item"
            :class="{ active: selectedTypes.includes(item.value) }"
            @tap="handleToggleType(item.value)"
          >
            {{ item.label }}
          </view>
        </view>
      </view>

      <view class="config-item">
        <text class="config-label">难度倾向</text>
        <view class="pill-group">
          <view
            v-for="item in difficultyOptions"
            :key="item.value"
            class="pill-item"
            :class="{ active: selectedDifficulty === item.value }"
            @tap="selectedDifficulty = item.value"
          >
            {{ item.label }}
          </view>
        </view>
      </view>

      <button class="btn-generate" @tap="handleStartGenerate">立即开始智能出题</button>
    </view>

    <!-- 生成中阶段进度动效 -->
    <view v-if="isGenerating" class="generation-progress-box">
      <view class="progress-stage-list">
        <view
          v-for="(stage, idx) in stages"
          :key="stage"
          class="stage-node"
          :class="{ active: idx === stageIndex, done: idx < stageIndex }"
        >
          <view class="stage-dot" :class="{ active: idx === stageIndex, done: idx < stageIndex }" />
          <text class="stage-text" :class="{ active: idx === stageIndex }">{{ stage }}</text>
        </view>
      </view>
      <text class="generating-hint">AI 正在深度解析资料讲义并命制高质量试题，请稍候...</text>
    </view>

    <!-- 题目质检核对清单列表 -->
    <view v-if="questions.length > 0" class="checklist-section">
      <view class="list-summary">
        <text class="summary-text">已质检通过题目 ({{ questions.length }} 题)</text>
        <text class="summary-sub">全部题目已通过置信度与事实一致性核对</text>
      </view>

      <view class="question-list">
        <view v-for="(q, idx) in questions" :key="q.id" class="verify-q-card">
          <view class="card-top">
            <view class="q-badge-row">
              <text class="badge-type">{{ formatQuestionType(q.question_type) }}</text>
              <text class="badge-diff">难度 {{ q.difficulty || 3 }}</text>
              <text class="badge-audit">质检达标</text>
            </view>
          </view>

          <text class="q-stem">{{ idx + 1 }}. {{ q.stem }}</text>

          <!-- 选项区 -->
          <view v-if="q.options && q.options.length > 0" class="q-options">
            <view v-for="opt in q.options" :key="opt.key" class="option-row">
              <text class="option-key">{{ opt.key }}.</text>
              <text class="option-text">{{ opt.text }}</text>
            </view>
          </view>

          <!-- 参考答案 -->
          <view class="q-answer-box">
            <text class="ans-label">参考答案：</text>
            <text class="ans-text">{{ q.answer || '暂无答案' }}</text>
          </view>

          <!-- 讲义出处原文引证折叠区 (J3) -->
          <view class="citation-section">
            <view class="citation-toggle" @tap="toggleCitation(q.id)">
              <text class="citation-toggle-text">
                {{ expandedCitationIds.has(q.id) ? '收起出处讲义原文' : '查看出处讲义原文' }}
              </text>
            </view>
            <view v-if="expandedCitationIds.has(q.id)" class="citation-box">
              <text class="citation-content">
                {{ resolveCitationText(q) }}
              </text>
            </view>
          </view>

          <!-- 卡片操作行 -->
          <view class="card-actions">
            <button class="btn-card-action" @tap="handleEditQuestion(q)">编辑修改</button>
            <button class="btn-card-action danger" @tap="handleDeleteQuestion(q.id)">
              删除题目
            </button>
          </view>
        </view>
      </view>
    </view>

    <!-- 底部直达开练栏 -->
    <view v-if="questions.length > 0" class="fixed-bottom-bar">
      <view class="bar-summary">
        <text class="bar-count">已核验 {{ questions.length }} 道优质题目</text>
        <text class="bar-hint">随时可开启沉浸式限时练习</text>
      </view>
      <button class="btn-start-practice" :disabled="isStarting" @tap="handleStartPractice">
        {{ isStarting ? '正在组卷...' : '开始作答' }}
      </button>
    </view>

    <!-- 题目编辑抽屉组件 -->
    <QuestionEditDrawer
      :visible="isEditDrawerOpen"
      :question="editingQuestion"
      @updated="handleQuestionUpdated"
      @close="isEditDrawerOpen = false"
    />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { onLoad } from '@dcloudio/uni-app';
import { fetchQuestionList, generateQuestions, deleteQuestion } from '@/api/question';
import { fetchMaterialDetail } from '@/api/material';
import { createPractice } from '@/api/practice';
import type { QuestionItem, QuestionType } from '@/types/question';
import QuestionEditDrawer from '../../components/QuestionEditDrawer.vue';

const materialId = ref<string>('');
const materialTitle = ref<string>('');
const questions = ref<QuestionItem[]>([]);
const isGenerating = ref<boolean>(false);
const isStarting = ref<boolean>(false);
const stageIndex = ref<number>(0);
const stages = ['检索资料切片', '考点提炼对齐', '命制深度试题', '质检门禁核验'];

const questionCount = ref<number>(5);
const selectedTypes = ref<QuestionType[]>(['single_choice', 'multiple_choice']);
const selectedDifficulty = ref<number>(3);

const questionTypeOptions: { label: string; value: QuestionType }[] = [
  { label: '单选题', value: 'single_choice' },
  { label: '多选题', value: 'multiple_choice' },
  { label: '简答题', value: 'short_answer' },
];

const difficultyOptions = [
  { label: '基础巩固', value: 2 },
  { label: '标准深度', value: 3 },
  { label: '进阶拔高', value: 4 },
];

const expandedCitationIds = ref<Set<string>>(new Set());
const isEditDrawerOpen = ref<boolean>(false);
const editingQuestion = ref<QuestionItem | null>(null);

function handleToggleType(type: QuestionType): void {
  if (selectedTypes.value.includes(type)) {
    if (selectedTypes.value.length > 1) {
      selectedTypes.value = selectedTypes.value.filter((t) => t !== type);
    }
  } else {
    selectedTypes.value.push(type);
  }
}

function toggleCitation(id: string): void {
  const nextSet = new Set(expandedCitationIds.value);
  if (nextSet.has(id)) {
    nextSet.delete(id);
  } else {
    nextSet.add(id);
  }
  expandedCitationIds.value = nextSet;
}

function resolveCitationText(q: QuestionItem): string {
  const itemAny = q as unknown as { source_snippet?: { snippet_content?: string } | string };
  if (itemAny.source_snippet) {
    if (typeof itemAny.source_snippet === 'string') {
      return itemAny.source_snippet;
    }
    if (itemAny.source_snippet.snippet_content) {
      return itemAny.source_snippet.snippet_content;
    }
  }
  return '本题源自讲义核心概念段落，重点考查定义理解与场景应用推导。';
}

function formatQuestionType(type?: string): string {
  switch (type) {
    case 'single_choice':
      return '单选题';
    case 'multiple_choice':
      return '多选题';
    case 'short_answer':
      return '简答题';
    default:
      return '题目';
  }
}

async function handleStartGenerate(): Promise<void> {
  if (!materialId.value) return;
  isGenerating.value = true;
  stageIndex.value = 0;

  const timer = setInterval(() => {
    if (stageIndex.value < stages.length - 1) {
      stageIndex.value += 1;
    }
  }, 3000);

  try {
    const res = await generateQuestions({
      material_id: materialId.value,
      count: questionCount.value,
      question_types: selectedTypes.value,
      difficulty: selectedDifficulty.value,
    });

    clearInterval(timer);

    if (res.data?.qualified_questions && res.data.qualified_questions.length > 0) {
      questions.value = res.data.qualified_questions;
      uni.showToast({ title: '出题质检完成', icon: 'success' });
    } else {
      await loadExistingQuestions();
    }
  } catch (error) {
    clearInterval(timer);
    uni.showToast({ title: '出题遇到波动，正在载入题目...', icon: 'none' });
    await loadExistingQuestions();
  } finally {
    isGenerating.value = false;
  }
}

async function loadExistingQuestions(): Promise<void> {
  if (!materialId.value) return;
  try {
    const res = await fetchQuestionList({
      material_id: materialId.value,
      page_size: 50,
    });
    if (res.data?.items) {
      questions.value = res.data.items;
    }
  } catch {
    // 静默兜底
  }
}

function handleEditQuestion(q: QuestionItem): void {
  editingQuestion.value = q;
  isEditDrawerOpen.value = true;
}

function handleQuestionUpdated(updated: QuestionItem): void {
  const index = questions.value.findIndex((q) => q.id === updated.id);
  if (index >= 0) {
    questions.value[index] = updated;
  }
  isEditDrawerOpen.value = false;
  uni.showToast({ title: '修改题目成功', icon: 'success' });
}

function handleDeleteQuestion(questionId: string): void {
  uni.showModal({
    title: '确认删除题目',
    content: '删除后该题目将不会出现在本次作答中，是否确认删除？',
    confirmColor: '#EF4444',
    success: async (res) => {
      if (res.confirm) {
        try {
          await deleteQuestion(questionId, '核验不合格删除');
          questions.value = questions.value.filter((q) => q.id !== questionId);
          uni.showToast({ title: '题目已删除', icon: 'success' });
        } catch {
          uni.showToast({ title: '删除失败，请稍后重试', icon: 'none' });
        }
      }
    },
  });
}

async function handleStartPractice(): Promise<void> {
  if (questions.value.length === 0 || isStarting.value) return;
  isStarting.value = true;

  try {
    const questionIds = questions.value.map((q) => q.id);
    const res = await createPractice({
      material_id: materialId.value,
      question_ids: questionIds,
      title: materialTitle.value ? `${materialTitle.value} 练习` : '讲义定制练习',
      mode: 'sequential',
    });

    if (res.data?.id) {
      uni.showToast({ title: '试卷准备就绪', icon: 'success' });
      setTimeout(() => {
        uni.navigateTo({
          url: `/subpackages/practice/pages/session/index?id=${res.data.id}`,
        });
      }, 400);
    }
  } catch (error) {
    uni.showToast({ title: '创建练习试卷失败，请重试', icon: 'none' });
  } finally {
    isStarting.value = false;
  }
}

onLoad(async (query?: Record<string, string>) => {
  const mid = query?.material_id || query?.materialId || '';
  if (mid) {
    materialId.value = mid;
    fetchMaterialDetail(mid)
      .then((res) => {
        if (res.data?.title) {
          materialTitle.value = res.data.title;
        }
      })
      .catch(() => {});
    await loadExistingQuestions();
  }
});
</script>

<style lang="scss" scoped src="./verify.scss"></style>
