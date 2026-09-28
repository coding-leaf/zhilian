<template>
  <view class="explanation-page">
    <!-- 顶部状态栏 -->
    <view class="page-header">
      <view class="header-tag-row">
        <text class="order-badge">第 {{ currentOrderIndex }} 题</text>
        <text class="type-badge">{{ questionTypeLabel }}</text>
        <text v-if="difficulty" class="difficulty-badge">难度 {{ difficulty }}/5</text>
      </view>
      <text class="page-title">题目深度解析</text>
    </view>

    <!-- 题干卡片 -->
    <view class="card-box stem-card">
      <text class="stem-text">{{ stem }}</text>
      <!-- 客观题选项展示 -->
      <view v-if="options.length > 0" class="options-list">
        <view
          v-for="opt in options"
          :key="opt.key"
          class="option-row"
          :class="{
            'option-correct': isCorrectOption(opt.key),
            'option-user-wrong': isUserWrongOption(opt.key),
          }"
        >
          <text class="opt-key">{{ opt.key }}.</text>
          <text class="opt-text">{{ opt.text || opt.content }}</text>
        </view>
      </view>
    </view>

    <!-- 答题对比与得分卡片 -->
    <view class="card-box comparison-card">
      <text class="section-title">作答与核对</text>
      <view class="answer-block">
        <text class="label">您的作答：</text>
        <text class="val-user">{{ formatAnswer(userAnswer) }}</text>
      </view>
      <view v-if="standardAnswer" class="answer-block">
        <text class="label">参考答案：</text>
        <text class="val-standard">{{ standardAnswer }}</text>
      </view>
      <view v-if="score !== null && score !== undefined" class="score-row">
        <text class="score-label">本题得分：</text>
        <text class="score-value">{{ score }} / {{ maxScore }} 分</text>
      </view>
    </view>

    <!-- 主观题采分点对齐卡片 -->
    <view v-if="hitKeywords.length > 0 || missingKeywords.length > 0" class="card-box rubric-card">
      <text class="rubric-title">采分点对齐</text>
      <view class="keywords-group">
        <text v-for="kw in hitKeywords" :key="`hit-${kw}`" class="chip-hit">
          命中采分点：{{ kw }}
        </text>
        <text v-for="kw in missingKeywords" :key="`miss-${kw}`" class="chip-miss">
          遗漏采分点：{{ kw }}
        </text>
      </view>
    </view>

    <!-- 讲义原文切片依据 -->
    <view v-if="sourceSnippet" class="card-box snippet-card">
      <text class="snippet-meta">
        讲义依据：{{ sourceSnippet.chapter_title || '参考讲义' }} (第
        {{ sourceSnippet.page_index || 1 }} 页)
      </text>
      <text class="snippet-text">{{ sourceSnippet.snippet_content }}</text>
    </view>

    <!-- 标准深度解析 -->
    <view v-if="analysis" class="card-box analysis-card">
      <text class="analysis-title">标准解析</text>
      <text class="analysis-body">{{ analysis }}</text>
    </view>

    <!-- 双通道纠偏操作栏 -->
    <view v-if="isSubjective" class="card-box action-buttons-card">
      <view class="action-btn btn-self-grade" @tap="selfGradeVisible = true">
        <text>信任自评打分</text>
      </view>
      <view class="action-btn btn-regrade" @tap="regradeVisible = true">
        <text>申请 AI 复核</text>
      </view>
    </view>

    <!-- UX Delighter: 追问 AI 助教 -->
    <AICoachCard
      :question-id="currentQuestionId"
      :user-answer="formatAnswer(userAnswer)"
      :grading-points="[...missingKeywords, ...hitKeywords]"
    />

    <!-- 自评与复核弹窗 -->
    <SelfGradeModal
      :visible="selfGradeVisible"
      :attempt-item-id="attemptItemId"
      :stem="stem"
      :user-answer="formatAnswer(userAnswer)"
      :standard-answer="standardAnswer"
      :max-score="maxScore"
      :current-score="score || 0"
      :rubric="gradingRubric"
      @update:visible="selfGradeVisible = $event"
      @success="onSelfGradeSuccess"
    />

    <RegradeModal
      :visible="regradeVisible"
      :attempt-item-id="attemptItemId"
      :stem="stem"
      @update:visible="regradeVisible = $event"
      @success="onRegradeSuccess"
    />
  </view>
</template>

<script setup lang="ts">
/**
 * explanation/index.vue
 * Question depth explanation and AI coach interactive follow-up page.
 * Zero-Emoji Policy enforced. Lines strictly <= 300.
 */

import { ref, computed, onMounted } from 'vue';
import { onLoad } from '@dcloudio/uni-app';
import { fetchPracticeSession } from '../../../../api/practice';
import { fetchQuestionDetail } from '../../../../api/question';
import type { AttemptGradingItem, OriginalSnippet } from '../../../../types/report';
import type { QuestionOption } from '../../../../types/question';
import SelfGradeModal from '../../components/SelfGradeModal.vue';
import RegradeModal from '../../components/RegradeModal.vue';
import AICoachCard from '../../components/AICoachCard.vue';

const props = withDefaults(
  defineProps<{
    practiceId?: string;
    questionId?: string;
    orderIndex?: number;
  }>(),
  {
    practiceId: '',
    questionId: '',
    orderIndex: 1,
  },
);

const currentPracticeId = ref<string>(props.practiceId || '');
const currentQuestionId = ref<string>(props.questionId || '');
const currentOrderIndex = ref<number>(props.orderIndex || 1);
const loading = ref<boolean>(true);

// Question & Attempt state
const attemptItemId = ref<string>('');
const stem = ref<string>('');
const questionType = ref<string>('single_choice');
const difficulty = ref<number>(3);
const options = ref<QuestionOption[]>([]);
const userAnswer = ref<unknown>('');
const standardAnswer = ref<string>('');
const analysis = ref<string>('');
const score = ref<number | null>(null);
const maxScore = ref<number>(5);
const hitKeywords = ref<string[]>([]);
const missingKeywords = ref<string[]>([]);
const sourceSnippet = ref<OriginalSnippet | null>(null);
const gradingRubric = ref<Record<string, unknown>>({});

// Modals
const selfGradeVisible = ref<boolean>(false);
const regradeVisible = ref<boolean>(false);

const questionTypeLabel = computed(() => {
  const map: Record<string, string> = {
    single_choice: '单选题',
    multiple_choice: '多选题',
    true_false: '判断题',
    fill_in_blank: '填空题',
    short_answer: '简答题',
    term_explanation: '名词解释',
    case_analysis: '案例分析',
  };
  return map[questionType.value] || '试题解析';
});

const isSubjective = computed(() => {
  return ['short_answer', 'term_explanation', 'case_analysis'].includes(questionType.value);
});

function formatAnswer(ans: unknown): string {
  if (ans === null || ans === undefined || ans === '') return '未作答';
  return Array.isArray(ans) ? ans.join(', ') : String(ans);
}

function isCorrectOption(key: string): boolean {
  if (!standardAnswer.value) return false;
  return standardAnswer.value.includes(key);
}

function isUserWrongOption(key: string): boolean {
  const formatted = formatAnswer(userAnswer.value);
  return formatted.includes(key) && !isCorrectOption(key);
}

function onSelfGradeSuccess(payload: { attempt_item_id: string; score: number }): void {
  score.value = payload.score;
  uni.showToast({ title: '自评打分已更新', icon: 'success' });
}

function onRegradeSuccess(payload: { status?: string; score?: number | null }): void {
  if (payload.status === 'success' && typeof payload.score === 'number') {
    score.value = payload.score;
  }
  uni.showToast({ title: '复核申请已提交', icon: 'success' });
}

async function loadExplanationData(): Promise<void> {
  loading.value = true;
  try {
    if (currentPracticeId.value) {
      const res = await fetchPracticeSession(currentPracticeId.value);
      const rawData = res.data as unknown as { items?: AttemptGradingItem[] };
      const matched = rawData?.items?.find(
        (it) =>
          it.question_id === currentQuestionId.value ||
          it.attempt_item_id === currentQuestionId.value,
      );
      if (matched) {
        attemptItemId.value = matched.attempt_item_id || '';
        currentOrderIndex.value = matched.order_index || currentOrderIndex.value;
        userAnswer.value = matched.user_answer;
        score.value = matched.score ?? null;
        maxScore.value = matched.max_score ?? 5;
        hitKeywords.value = matched.hit_keywords || matched.question_snapshot?.hit_keywords || [];
        missingKeywords.value =
          matched.missing_keywords || matched.question_snapshot?.missing_keywords || [];
        sourceSnippet.value =
          matched.source_snippet || matched.question_snapshot?.source_snippet || null;

        const snap = matched.question_snapshot;
        if (snap) {
          stem.value = snap.stem || '';
          questionType.value = snap.question_type || 'single_choice';
          difficulty.value = (snap.difficulty as number) ?? 3;
          standardAnswer.value = snap.answer || '';
          analysis.value = ((snap.analysis || snap.explanation) as string) || '';
          options.value = (snap.options as unknown as QuestionOption[]) || [];
          gradingRubric.value = snap.grading_rubric || {};
          return;
        }
      }
    }

    if (currentQuestionId.value) {
      const qRes = await fetchQuestionDetail(currentQuestionId.value);
      if (qRes.code === 0 && qRes.data) {
        const q = qRes.data;
        stem.value = q.stem;
        questionType.value = q.question_type;
        difficulty.value = q.difficulty;
        standardAnswer.value = q.answer || '';
        analysis.value = q.analysis || '';
        options.value = q.options || [];
        gradingRubric.value = q.grading_rubric || {};
      }
    }
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  if (currentPracticeId.value || currentQuestionId.value) {
    void loadExplanationData();
  }
});

onLoad((query) => {
  if (query?.practice_id) currentPracticeId.value = query.practice_id as string;
  if (query?.question_id || query?.id) {
    currentQuestionId.value = (query.question_id as string) || (query.id as string);
  }
  if (query?.order_index) {
    currentOrderIndex.value = Number(query.order_index) || 1;
  }
  void loadExplanationData();
});
</script>

<style lang="scss" scoped>
@import './explanation.scss';
</style>
