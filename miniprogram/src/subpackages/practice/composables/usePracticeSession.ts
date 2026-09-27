/**
 * usePracticeSession.ts
 * Practice session management composable.
 * Handles timer, remote session loading, local draft caching, and debounced network syncing.
 * Adheres to AGENTS.md & docs/sdlc/ZL-134/spec.md: Zero-Emoji, lines <= 300.
 */

import { ref, computed, watch } from 'vue';
import { usePracticeStore } from '../../../stores/practiceStore';
import {
  fetchPracticeSession,
  saveAnswerDraft,
  pausePractice,
  resumePractice,
} from '../../../api/practice';
import {
  createOrUpdateDraft,
  saveDraftToStorage,
  loadDraftFromStorage,
  markDraftSynced,
  extractPendingSyncItems,
} from '../utils/draft';

interface PendingDraftSync {
  questionId: string;
  value: string | string[];
  elapsed: number;
}

export function usePracticeSession() {
  const practiceStore = usePracticeStore();

  const localPracticeId = ref<string>('');
  const practiceId = computed<string>(() => {
    return localPracticeId.value || practiceStore.sessionId || '';
  });
  const practiceTitle = ref<string>('练习作答');
  const elapsedSeconds = ref<number>(0);
  const loading = ref<boolean>(false);

  let timer: ReturnType<typeof setInterval> | null = null;
  let syncTimeout: ReturnType<typeof setTimeout> | null = null;
  let questionStartTime = Date.now();
  // Identity token of the latest unsynced answer. Compared by reference so a
  // slow in-flight sync cannot finalize a newer pending change (PRAC-012).
  let pendingSync: PendingDraftSync | null = null;

  // Reset the per-question entry timestamp whenever the active question changes.
  watch(
    () => practiceStore.currentQuestion?.id,
    () => {
      questionStartTime = Date.now();
    },
  );

  function takeQuestionElapsedSeconds(): number {
    const elapsed = Math.max(1, Math.round((Date.now() - questionStartTime) / 1000));
    questionStartTime = Date.now();
    return elapsed;
  }

  function startTimer(): void {
    stopTimer();
    timer = setInterval(() => {
      elapsedSeconds.value += 1;
    }, 1000);
  }

  function stopTimer(): void {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  async function loadPractice(id: string): Promise<void> {
    localPracticeId.value = id;
    loading.value = true;
    try {
      const res = await fetchPracticeSession(id);
      if (res.data) {
        practiceTitle.value = res.data.title || '练习作答';
        practiceStore.initSession(id, res.data.questions || []);
        elapsedSeconds.value = res.data.time_elapsed_seconds || 0;
        questionStartTime = Date.now();

        // 从 Storage 恢复本地草稿
        const localDraft = loadDraftFromStorage(id);
        if (localDraft?.answers) {
          for (const [qid, ans] of Object.entries(localDraft.answers)) {
            practiceStore.updateDraft(qid, ans);
          }
        }
      }
    } finally {
      loading.value = false;
      startTimer();
    }
  }

  function handleAnswerChange(val: string | string[]): void {
    const qid = practiceStore.currentQuestion?.id;
    const pid = practiceId.value;
    if (!qid || !pid) {
      return;
    }
    // 1. 同步更新 Store
    practiceStore.updateAnswer(qid, val);

    // 2. 本地 Storage 毫秒级写入草稿（记录真实停留耗时，消除硬编码 1 秒）
    const elapsed = takeQuestionElapsedSeconds();
    const cur = loadDraftFromStorage(pid);
    const updated = createOrUpdateDraft(cur, pid, qid, val, elapsed);
    saveDraftToStorage(pid, updated);

    // 3. 防抖异步同步到远端
    const pending: PendingDraftSync = { questionId: qid, value: val, elapsed };
    pendingSync = pending;
    if (syncTimeout) {
      clearTimeout(syncTimeout);
    }
    syncTimeout = setTimeout(() => {
      syncTimeout = null;
      void syncSingleDraft(pending);
    }, 600);
  }

  async function syncSingleDraft(pending: PendingDraftSync): Promise<void> {
    const pid = practiceId.value;
    if (!pid) {
      return;
    }
    try {
      await saveAnswerDraft(pid, {
        question_id: pending.questionId,
        user_answer: pending.value,
        time_spent_seconds: pending.elapsed,
      });
      // A newer answer may have superseded this one while the request was in
      // flight; only the latest token may clear pending state and mark synced,
      // otherwise the newer answer would be dropped (PRAC-012).
      if (pendingSync !== pending) {
        return;
      }
      pendingSync = null;
      const cur = loadDraftFromStorage(pid);
      if (cur) {
        saveDraftToStorage(pid, markDraftSynced(cur, [pending.questionId]));
      }
    } catch {
      // 离线或同步失败，保留待同步状态
    }
  }

  async function syncPendingDrafts(): Promise<void> {
    const pid = practiceId.value;
    if (!pid) {
      return;
    }
    const cur = loadDraftFromStorage(pid);
    const pending = extractPendingSyncItems(cur);
    if (pending.length === 0) {
      return;
    }
    for (const item of pending) {
      try {
        await saveAnswerDraft(pid, {
          question_id: item.question_id,
          user_answer: item.user_answer,
          time_spent_seconds: item.time_spent_seconds,
        });
        const latest = loadDraftFromStorage(pid);
        if (latest) {
          saveDraftToStorage(pid, markDraftSynced(latest, [item.question_id]));
        }
      } catch {
        // 保持 pending 状态
      }
    }
  }

  function handleNetworkChange(res: { isConnected: boolean }): void {
    if (res.isConnected) {
      void syncPendingDrafts();
    }
  }

  /**
   * Immediately flush any draft still held by the debounce timer.
   *
   * Called on session teardown so the last answer before leaving is pushed to
   * the backend instead of being silently dropped with the cleared timer
   * (BUG-PRAC-012). Network failure degrades to keeping the local draft.
   */
  function flushPendingDraft(): void {
    if (syncTimeout) {
      clearTimeout(syncTimeout);
      syncTimeout = null;
    }
    if (pendingSync) {
      // Keep the token in place so syncSingleDraft can compare identity and
      // finalize (clear + mark synced) only when this exact change is synced.
      void syncSingleDraft(pendingSync);
      return;
    }
    void syncPendingDrafts();
  }

  /**
   * Pause the practice: stop local timing and notify the backend.
   *
   * Restarts local timing if the backend call fails so client and server stay
   * consistent (BUG-PRAC-017).
   */
  async function pauseSession(): Promise<void> {
    const pid = practiceId.value;
    if (!pid) {
      return;
    }
    stopTimer();
    try {
      await pausePractice(pid);
    } catch (error) {
      startTimer();
      throw error;
    }
  }

  /**
   * Resume the practice: notify the backend then restart local timing (BUG-PRAC-017).
   */
  async function resumeSession(): Promise<void> {
    const pid = practiceId.value;
    if (!pid) {
      return;
    }
    await resumePractice(pid);
    questionStartTime = Date.now();
    startTimer();
  }

  function cleanupSession(): void {
    stopTimer();
    flushPendingDraft();
  }

  return {
    practiceId,
    localPracticeId,
    practiceTitle,
    elapsedSeconds,
    loading,
    startTimer,
    stopTimer,
    loadPractice,
    handleAnswerChange,
    syncPendingDrafts,
    flushPendingDraft,
    handleNetworkChange,
    pauseSession,
    resumeSession,
    cleanupSession,
  };
}
