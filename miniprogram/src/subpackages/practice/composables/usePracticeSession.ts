/**
 * usePracticeSession.ts
 * Practice session management composable.
 * Handles timer, remote session loading, local draft caching, and debounced network syncing.
 * Adheres to AGENTS.md & docs/sdlc/ZL-134/spec.md: Zero-Emoji, lines <= 300.
 */

import { ref, computed } from 'vue';
import { usePracticeStore } from '../../../stores/practiceStore';
import { fetchPracticeSession, saveAnswerDraft } from '../../../api/practice';
import {
  createOrUpdateDraft,
  saveDraftToStorage,
  loadDraftFromStorage,
  markDraftSynced,
  extractPendingSyncItems,
} from '../utils/draft';

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

    // 2. 本地 Storage 毫秒级写入草稿
    const cur = loadDraftFromStorage(pid);
    const updated = createOrUpdateDraft(cur, pid, qid, val, 1);
    saveDraftToStorage(pid, updated);

    // 3. 防抖异步同步到远端
    if (syncTimeout) {
      clearTimeout(syncTimeout);
    }
    syncTimeout = setTimeout(() => {
      void syncSingleDraft(qid, val);
    }, 600);
  }

  async function syncSingleDraft(qid: string, val: string | string[]): Promise<void> {
    const pid = practiceId.value;
    if (!pid) {
      return;
    }
    try {
      await saveAnswerDraft(pid, {
        question_id: qid,
        user_answer: val,
        time_spent_seconds: 1,
      });
      const cur = loadDraftFromStorage(pid);
      if (cur) {
        saveDraftToStorage(pid, markDraftSynced(cur, [qid]));
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

  function cleanupSession(): void {
    stopTimer();
    if (syncTimeout) {
      clearTimeout(syncTimeout);
      syncTimeout = null;
    }
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
    handleNetworkChange,
    cleanupSession,
  };
}
