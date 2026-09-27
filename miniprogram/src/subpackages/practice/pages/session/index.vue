<template>
  <view class="practice-session-page">
    <!-- 顶部状态栏：练习标题、题量进度、实时计时器、答题卡与退出入口 -->
    <PracticeHeader
      :title="practiceTitle"
      :current-index="practiceStore.currentIndex"
      :total-questions="practiceStore.totalQuestions"
      :elapsed-seconds="elapsedSeconds"
      @open-sheet="handleOpenSheet"
      @exit="handleExit"
    />

    <!-- 题目主渲染区域 -->
    <view class="session-body">
      <view v-if="normalizedQuestion" class="question-container">
        <QuestionRenderer
          :question="normalizedQuestion"
          :model-value="currentAnswer"
          :order-index="practiceStore.currentIndex + 1"
          @update:model-value="handleAnswerChange"
        />
      </view>
      <view v-else-if="!loading" class="empty-state">
        <text class="state-text">暂无题目数据</text>
      </view>
      <view v-else class="loading-state">
        <text class="state-text">加载中...</text>
      </view>

      <!-- 底部安全区与操作栏占位 -->
      <view class="bottom-placeholder" />
    </view>

    <!-- 底部常驻吸底操作栏 -->
    <BottomActionBar
      :current-index="practiceStore.currentIndex"
      :total-count="practiceStore.totalQuestions"
      :is-submitting="practiceStore.isSubmitting"
      @prev="handlePrev"
      @next="handleNext"
      @submit="handleSubmitClick"
    />

    <!-- 答题卡底部抽屉浮层 -->
    <AnswerSheetDrawer
      v-model:visible="sheetDrawerVisible"
      :total-count="practiceStore.totalQuestions"
      :current-index="practiceStore.currentIndex"
      :answers="currentAnswersMap"
      :question-ids="questionIds"
      @select="handleSelectFromSheet"
    />

    <!-- 交卷二次确认与未答题清单阻断弹窗 -->
    <SubmitConfirmModal
      v-model:visible="confirmModalVisible"
      :total-count="practiceStore.totalQuestions"
      :answered-count="practiceStore.answeredCount"
      :unanswered-indices="unansweredIndices"
      :submitting="practiceStore.isSubmitting"
      @confirm="handleConfirmSubmit"
      @locate-unanswered="handleLocateUnanswered"
    />
  </view>
</template>

<script setup lang="ts">
/**
 * session/index.vue
 * Practice session assembly page.
 * Reference: docs/sdlc/ZL-134/spec.md
 * Zero-Emoji Policy enforced. Lines strictly <= 300.
 */

import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { onLoad, onUnload } from '@dcloudio/uni-app';
import { usePracticeStore, type PracticeQuestion } from '../../../../stores/practiceStore';
import { usePracticeSession } from '../../composables/usePracticeSession';
import PracticeHeader from '../../components/PracticeHeader.vue';
import QuestionRenderer, { type RendererQuestion } from '../../components/QuestionRenderer.vue';
import BottomActionBar from '../../components/BottomActionBar.vue';
import AnswerSheetDrawer from '../../components/AnswerSheetDrawer.vue';
import SubmitConfirmModal from '../../components/SubmitConfirmModal.vue';
import { submitPractice } from '../../../../api/practice';
import { clearDraftFromStorage, calculateQuestionStats } from '../../utils/draft';
import { getOrCreateSubmitKey, clearSubmitKey } from '../../utils/submitKey';
import { AppError } from '../../../../utils/error';

const practiceStore = usePracticeStore();
const {
  practiceId,
  practiceTitle,
  elapsedSeconds,
  loading,
  stopTimer,
  loadPractice,
  handleAnswerChange,
  syncPendingDrafts,
  handleNetworkChange,
  cleanupSession,
} = usePracticeSession();

const sheetDrawerVisible = ref<boolean>(false);
const confirmModalVisible = ref<boolean>(false);
const unansweredIndices = ref<number[]>([]);

const questionIds = computed<string[]>(() => {
  return practiceStore.questions.map((q) => q.id);
});

const currentAnswersMap = computed<Record<string, unknown>>(() => {
  return practiceStore.currentDraft?.answers || {};
});

const currentQuestion = computed<PracticeQuestion | null>(() => {
  return practiceStore.currentQuestion;
});

const normalizedQuestion = computed<RendererQuestion | null>(() => {
  const q = currentQuestion.value;
  if (!q) {
    return null;
  }
  const raw = q as unknown as { question_type?: string; type?: string; difficulty?: number };
  const qType = raw.question_type || raw.type || '';
  return {
    id: q.id,
    stem: q.stem,
    question_type: qType,
    options: q.options,
    difficulty: raw.difficulty,
  };
});

const currentAnswer = computed<string | string[]>({
  get: () => {
    const qid = currentQuestion.value?.id;
    if (!qid) {
      return '';
    }
    const ans = practiceStore.currentDraft?.answers[qid];
    return (ans as string | string[]) ?? '';
  },
  set: (val) => {
    handleAnswerChange(val);
  },
});

function handlePrev(): void {
  practiceStore.prevQuestion();
}

function handleNext(): void {
  practiceStore.nextQuestion();
}

function handleOpenSheet(): void {
  sheetDrawerVisible.value = true;
}

function handleSelectFromSheet(index: number): void {
  practiceStore.jumpToQuestion(index);
}

function handleLocateUnanswered(index: number): void {
  practiceStore.jumpToQuestion(index);
}

function handleExit(): void {
  uni.showModal({
    title: '退出练习',
    content: '当前作答进度已自动保存为草稿，确认退出吗？',
    confirmText: '退出',
    cancelText: '继续答题',
    success: (res) => {
      if (res.confirm) {
        stopTimer();
        uni.navigateBack();
      }
    },
  });
}

function handleSubmitClick(): void {
  const stats = calculateQuestionStats(questionIds.value, currentAnswersMap.value);
  unansweredIndices.value = stats.unansweredIndices;
  confirmModalVisible.value = true;
}

async function handleConfirmSubmit(payload: { confirm_unanswered: boolean }): Promise<void> {
  const targetPracticeId = practiceId.value;
  practiceStore.isSubmitting = true;
  try {
    await syncPendingDrafts().catch(() => {});
    const idempotencyKey = getOrCreateSubmitKey(targetPracticeId);
    await submitPractice(targetPracticeId, idempotencyKey, {
      confirm_unanswered: payload.confirm_unanswered,
    });

    clearSubmitKey(targetPracticeId);
    clearDraftFromStorage(targetPracticeId);
    practiceStore.clearSession(targetPracticeId);
    confirmModalVisible.value = false;

    uni.showToast({
      title: '交卷成功',
      icon: 'success',
    });
    uni.redirectTo({
      url: `/subpackages/report/index?practice_id=${targetPracticeId}`,
    });
  } catch (err: unknown) {
    // A 400 means the submission is already in a terminal state, so retrying is
    // pointless; release the key. Network/timeout errors keep it for replay.
    if (err instanceof AppError && err.status_code === 400) {
      clearSubmitKey(targetPracticeId);
    }
    const errorMsg = (err as { message?: string })?.message || '交卷失败，请重试';
    uni.showToast({
      title: errorMsg,
      icon: 'none',
    });
  } finally {
    practiceStore.isSubmitting = false;
  }
}

onLoad((query) => {
  const pid = (query?.id as string) || (query?.practice_id as string) || '';
  if (pid) {
    void loadPractice(pid);
  }
});

onMounted(() => {
  if (typeof uni !== 'undefined' && typeof uni.onNetworkStatusChange === 'function') {
    uni.onNetworkStatusChange(handleNetworkChange);
  }
});

onUnload(() => {
  cleanupSession();
  if (typeof uni !== 'undefined' && typeof uni.offNetworkStatusChange === 'function') {
    uni.offNetworkStatusChange(handleNetworkChange);
  }
});

onBeforeUnmount(() => {
  cleanupSession();
});
</script>

<style lang="scss" scoped>
@import './session.scss';
</style>
