import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { ref } from 'vue';
import {
  usePracticeSync,
  getDraftStorageKey,
  loadLocalDraft,
  saveLocalDraft,
  clearLocalDraft,
} from '@/composables/usePracticeSync';
import * as practiceApi from '@/api/practice';
import * as submitKeyModule from '@/subpackages/practice/utils/submitKey';

describe('usePracticeSync.ts', () => {
  const practiceId = 'prac_test_123';
  let storageMap: Record<string, unknown> = {};

  beforeEach(() => {
    vi.useFakeTimers();
    storageMap = {};

    uni.getStorageSync = vi.fn(
      (key: string) => storageMap[key] ?? null,
    ) as unknown as typeof uni.getStorageSync;
    uni.setStorageSync = vi.fn((key: string, val: unknown) => {
      storageMap[key] = val;
    }) as unknown as typeof uni.setStorageSync;
    uni.removeStorageSync = vi.fn((key: string) => {
      delete storageMap[key];
    }) as unknown as typeof uni.removeStorageSync;

    vi.spyOn(practiceApi, 'saveAnswerDraft').mockResolvedValue({
      code: 0,
      message: 'success',
      data: { attempt_item_id: 'att_01', status: 'saved' },
    });

    vi.spyOn(practiceApi, 'submitPractice').mockResolvedValue({
      code: 0,
      message: 'success',
      data: { practice_id: practiceId, status: 'submitted' },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('generates storage key with practice_draft_ prefix', () => {
    expect(getDraftStorageKey(practiceId)).toBe('practice_draft_prac_test_123');
  });

  it('saves and loads local draft from storage', () => {
    const draft = {
      practiceId,
      currentIndex: 2,
      answers: {
        q1: { questionId: 'q1', answer: 'A', flagged: false, updatedAt: 1000 },
      },
      lastSyncedAt: 1000,
    };

    saveLocalDraft(draft);
    expect(uni.setStorageSync).toHaveBeenCalledWith('practice_draft_prac_test_123', draft);

    const loaded = loadLocalDraft(practiceId);
    expect(loaded).toEqual(draft);

    clearLocalDraft(practiceId);
    expect(uni.removeStorageSync).toHaveBeenCalledWith('practice_draft_prac_test_123');
    expect(loadLocalDraft(practiceId)).toBeNull();
  });

  it('records answer with immediate storage persistence and debounced sync', async () => {
    const pidRef = ref(practiceId);
    const sync = usePracticeSync(pidRef, { debounceMs: 800 });

    sync.recordAnswer('q1', 'B', 3);

    // Millisecond-level local persistence check
    expect(uni.setStorageSync).toHaveBeenCalledWith(
      'practice_draft_prac_test_123',
      expect.objectContaining({
        practiceId,
        answers: expect.objectContaining({
          q1: expect.objectContaining({
            questionId: 'q1',
            answer: 'B',
            flagged: false,
          }),
        }),
      }),
    );

    // Before debounce: server api should not be called yet
    expect(practiceApi.saveAnswerDraft).not.toHaveBeenCalled();

    // Fast-forward 800ms
    vi.advanceTimersByTime(800);
    await vi.runAllTimersAsync();

    expect(practiceApi.saveAnswerDraft).toHaveBeenCalledWith(practiceId, {
      question_id: 'q1',
      user_answer: 'B',
      time_spent_seconds: 3,
    });
    expect(sync.lastSyncedAt.value).toBeGreaterThan(0);
  });

  it('toggles flagged question status and persists state', () => {
    const pidRef = ref(practiceId);
    const sync = usePracticeSync(pidRef);

    expect(sync.isFlagged('q1')).toBe(false);
    expect(sync.flaggedQuestionIds.value).toEqual([]);

    const flaggedNow = sync.toggleFlag('q1');
    expect(flaggedNow).toBe(true);
    expect(sync.isFlagged('q1')).toBe(true);
    expect(sync.flaggedQuestionIds.value).toEqual(['q1']);

    const unflaggedNow = sync.toggleFlag('q1');
    expect(unflaggedNow).toBe(false);
    expect(sync.isFlagged('q1')).toBe(false);
    expect(sync.flaggedQuestionIds.value).toEqual([]);
  });

  it('restores state from existing local draft', () => {
    saveLocalDraft({
      practiceId,
      currentIndex: 3,
      answers: {
        q1: { questionId: 'q1', answer: 'A', flagged: true, updatedAt: 5000 },
      },
      lastSyncedAt: 4000,
    });

    const pidRef = ref(practiceId);
    const sync = usePracticeSync(pidRef);

    const restored = sync.restoreFromLocal();
    expect(restored).not.toBeNull();
    expect(sync.currentIndex.value).toBe(3);
    expect(sync.getAnswer('q1')).toBe('A');
    expect(sync.isFlagged('q1')).toBe(true);
  });

  it('accurately computes unanswered questions summary', () => {
    const pidRef = ref(practiceId);
    const sync = usePracticeSync(pidRef);

    sync.recordAnswer('q1', 'A');
    sync.recordAnswer('q3', ['Option1', 'Option2']);

    const summary = sync.checkUnanswered(['q1', 'q2', 'q3', 'q4']);
    expect(summary.total).toBe(4);
    expect(summary.answeredCount).toBe(2);
    expect(summary.unansweredCount).toBe(2);
    expect(summary.unansweredIndices).toEqual([2, 4]); // 1-based indices
  });

  it('submits practice with idempotency key and clears local draft upon success', async () => {
    const pidRef = ref(practiceId);
    const sync = usePracticeSync(pidRef);

    sync.recordAnswer('q1', 'A');
    const spyClearSubmitKey = vi.spyOn(submitKeyModule, 'clearSubmitKey');

    const res = await sync.submitWithIdempotency(true);

    expect(practiceApi.submitPractice).toHaveBeenCalledWith(practiceId, expect.any(String), {
      confirm_unanswered: true,
    });
    expect(res.status).toBe('submitted');
    expect(spyClearSubmitKey).toHaveBeenCalledWith(practiceId);
    expect(uni.removeStorageSync).toHaveBeenCalledWith('practice_draft_prac_test_123');
  });

  it('gracefully handles storage exceptions during draft persistence', () => {
    uni.setStorageSync = vi.fn(() => {
      throw new Error('QuotaExceeded');
    }) as unknown as typeof uni.setStorageSync;

    const pidRef = ref(practiceId);
    const sync = usePracticeSync(pidRef);

    // Should not throw
    expect(() => {
      sync.recordAnswer('q1', 'A');
    }).not.toThrow();
  });
});
