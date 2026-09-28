/**
 * usePracticeSync.ts
 * Practice session local storage caching and server synchronization composable.
 * Implements millisecond-level offline draft persistence and debounced remote sync.
 * Zero-Emoji Policy enforced. Lines strictly <= 300.
 */

import { ref, computed } from 'vue';
import type { Ref } from 'vue';
import { saveAnswerDraft, submitPractice } from '../api/practice';
import { getOrCreateSubmitKey, clearSubmitKey } from '../subpackages/practice/utils/submitKey';
import { isAnswerFilled } from '../subpackages/practice/utils/draft';

export interface PracticeDraftAnswerItem {
  questionId: string;
  answer: string | string[];
  flagged: boolean;
  updatedAt: number;
}

export interface PracticeLocalDraft {
  practiceId: string;
  currentIndex: number;
  answers: Record<string, PracticeDraftAnswerItem>;
  lastSyncedAt: number;
}

export interface UnansweredSummary {
  total: number;
  answeredCount: number;
  unansweredCount: number;
  unansweredIndices: number[]; // 1-based indices
}

export function getDraftStorageKey(practiceId: string): string {
  return `practice_draft_${practiceId}`;
}

export function loadLocalDraft(practiceId: string): PracticeLocalDraft | null {
  if (!practiceId) return null;
  try {
    const raw = uni.getStorageSync(getDraftStorageKey(practiceId));
    if (!raw) return null;
    return typeof raw === 'string' ? JSON.parse(raw) : raw;
  } catch (error) {
    console.warn('[practiceSync] failed to load draft from storage', error);
    return null;
  }
}

export function saveLocalDraft(draft: PracticeLocalDraft): void {
  if (!draft?.practiceId) return;
  try {
    const key = getDraftStorageKey(draft.practiceId);
    uni.setStorageSync(key, draft);
  } catch (error) {
    console.warn('[practiceSync] failed to save draft to storage', error);
  }
}

export function clearLocalDraft(practiceId: string): void {
  if (!practiceId) return;
  try {
    uni.removeStorageSync(getDraftStorageKey(practiceId));
  } catch (error) {
    console.warn('[practiceSync] failed to clear draft from storage', error);
  }
}

export function usePracticeSync(
  practiceIdRef: Ref<string> | { value: string },
  options: { debounceMs?: number } = {},
) {
  const debounceMs = options.debounceMs ?? 800;
  const answers = ref<Record<string, PracticeDraftAnswerItem>>({});
  const currentIndex = ref<number>(0);
  const lastSyncedAt = ref<number>(0);
  const isSyncing = ref<boolean>(false);
  const isSubmitting = ref<boolean>(false);

  let syncTimer: ReturnType<typeof setTimeout> | null = null;
  let pendingSyncItem: { questionId: string; answer: string | string[]; elapsed: number } | null =
    null;

  function restoreFromLocal(practiceId?: string): PracticeLocalDraft | null {
    const pid = practiceId || practiceIdRef.value;
    if (!pid) return null;

    const draft = loadLocalDraft(pid);
    if (draft && draft.answers) {
      answers.value = { ...draft.answers };
      currentIndex.value = draft.currentIndex || 0;
      lastSyncedAt.value = draft.lastSyncedAt || 0;
      return draft;
    }
    return null;
  }

  function persistCurrentState(): void {
    const pid = practiceIdRef.value;
    if (!pid) return;

    saveLocalDraft({
      practiceId: pid,
      currentIndex: currentIndex.value,
      answers: answers.value,
      lastSyncedAt: lastSyncedAt.value,
    });
  }

  function recordAnswer(
    questionId: string,
    answer: string | string[],
    durationSeconds = 1,
    flagged?: boolean,
  ): void {
    const pid = practiceIdRef.value;
    if (!pid || !questionId) return;

    const prev = answers.value[questionId];
    const isFlagged = flagged !== undefined ? flagged : prev ? prev.flagged : false;
    const now = Date.now();

    answers.value[questionId] = {
      questionId,
      answer,
      flagged: isFlagged,
      updatedAt: now,
    };

    // Millisecond-level local storage write
    persistCurrentState();

    // Schedule debounced remote synchronization
    pendingSyncItem = { questionId, answer, elapsed: durationSeconds };
    if (syncTimer) {
      clearTimeout(syncTimer);
    }
    syncTimer = setTimeout(() => {
      syncTimer = null;
      void flushPendingSync();
    }, debounceMs);
  }

  function toggleFlag(questionId: string): boolean {
    const prev = answers.value[questionId];
    const nextFlag = prev ? !prev.flagged : true;
    const currentAns = prev ? prev.answer : '';

    answers.value[questionId] = {
      questionId,
      answer: currentAns,
      flagged: nextFlag,
      updatedAt: Date.now(),
    };

    persistCurrentState();
    return nextFlag;
  }

  function isFlagged(questionId: string): boolean {
    return Boolean(answers.value[questionId]?.flagged);
  }

  function getAnswer(questionId: string): string | string[] {
    return answers.value[questionId]?.answer ?? '';
  }

  async function flushPendingSync(): Promise<void> {
    const pid = practiceIdRef.value;
    if (!pid || !pendingSyncItem) return;

    const itemToSync = pendingSyncItem;
    pendingSyncItem = null;
    isSyncing.value = true;

    try {
      await saveAnswerDraft(pid, {
        question_id: itemToSync.questionId,
        user_answer: itemToSync.answer,
        time_spent_seconds: itemToSync.elapsed,
      });
      lastSyncedAt.value = Date.now();
      persistCurrentState();
    } catch (error) {
      console.warn('[practiceSync] debounced sync to server degraded', error);
    } finally {
      isSyncing.value = false;
    }
  }

  function flushSyncImmediately(): void {
    if (syncTimer) {
      clearTimeout(syncTimer);
      syncTimer = null;
    }
    void flushPendingSync();
  }

  function checkUnanswered(questionIds: string[]): UnansweredSummary {
    const total = questionIds.length;
    let answeredCount = 0;
    const unansweredIndices: number[] = [];

    for (let i = 0; i < total; i++) {
      const qid = questionIds[i];
      const ansItem = answers.value[qid];
      const ansValue = ansItem ? ansItem.answer : undefined;

      if (isAnswerFilled(ansValue)) {
        answeredCount += 1;
      } else {
        unansweredIndices.push(i + 1);
      }
    }

    return {
      total,
      answeredCount,
      unansweredCount: total - answeredCount,
      unansweredIndices,
    };
  }

  async function submitWithIdempotency(
    confirmUnanswered = false,
  ): Promise<{ practice_id: string; status: string }> {
    const pid = practiceIdRef.value;
    if (!pid) {
      throw new Error('练习会话未初始化');
    }

    if (isSubmitting.value) {
      return { practice_id: pid, status: 'submitting' };
    }

    isSubmitting.value = true;
    try {
      flushSyncImmediately();
      const idempotencyKey = getOrCreateSubmitKey(pid);
      const res = await submitPractice(pid, idempotencyKey, {
        confirm_unanswered: confirmUnanswered,
      });

      // Clear local state and submit key on successful submission
      clearSubmitKey(pid);
      clearLocalDraft(pid);
      answers.value = {};

      return res.data;
    } finally {
      isSubmitting.value = false;
    }
  }

  const answeredCount = computed(() => {
    return Object.values(answers.value).filter((item) => isAnswerFilled(item.answer)).length;
  });

  const flaggedQuestionIds = computed(() => {
    return Object.values(answers.value)
      .filter((item) => item.flagged)
      .map((item) => item.questionId);
  });

  return {
    answers,
    currentIndex,
    lastSyncedAt,
    isSyncing,
    isSubmitting,
    answeredCount,
    flaggedQuestionIds,
    restoreFromLocal,
    persistCurrentState,
    recordAnswer,
    toggleFlag,
    isFlagged,
    getAnswer,
    flushPendingSync,
    flushSyncImmediately,
    checkUnanswered,
    submitWithIdempotency,
  };
}
