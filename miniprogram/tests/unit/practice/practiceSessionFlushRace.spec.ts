import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { usePracticeStore } from '@/stores/practiceStore';
import * as requestModule from '@/utils/request';
import { usePracticeSession } from '@/subpackages/practice/composables/usePracticeSession';
import type { PracticeQuestionOutline } from '@/types/practice';
import { storage } from '@/utils/storage';

/**
 * Regression guard for PRAC-012: a late-resolving sync of an older answer must
 * not finalize (drop) a newer unsynced answer, and the cleanup flush must still
 * push the latest answer before the session is torn down.
 */
describe('usePracticeSession debounced draft flush race (PRAC-012)', () => {
  const memoryStore: Record<string, unknown> = {};
  const mockQuestions: PracticeQuestionOutline[] = [
    {
      id: 'q_001',
      stem: '以下哪项是 Python 的不可变数据类型？',
      type: 'single_choice',
      order_index: 0,
      options: [
        { key: 'A', text: '列表 (List)' },
        { key: 'B', text: '元组 (Tuple)' },
      ],
    },
  ];

  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    Object.keys(memoryStore).forEach((key) => delete memoryStore[key]);

    uni.getStorageSync = ((key: string) =>
      memoryStore[key] ?? null) as unknown as typeof uni.getStorageSync;
    uni.setStorageSync = (key: string, data: unknown) => {
      memoryStore[key] = data;
    };
    uni.removeStorageSync = (key: string) => {
      delete memoryStore[key];
    };
    uni.clearStorageSync = () => {
      Object.keys(memoryStore).forEach((key) => delete memoryStore[key]);
    };

    storage.clear();

    vi.spyOn(requestModule, 'request').mockImplementation(() =>
      Promise.resolve({
        code: 0,
        message: 'success',
        data: { attempt_item_id: 'item_1', status: 'saved' },
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('does not drop a newer draft when an older in-flight sync resolves late', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);
    const { handleAnswerChange, cleanupSession } = usePracticeSession();

    // Hold the first answers request in flight so its stale response resolves
    // only after a newer answer has already been recorded.
    const gate: { release: () => void } = { release: () => {} };
    const firstGate = new Promise<void>((resolve) => {
      gate.release = resolve;
    });
    vi.mocked(requestModule.request).mockImplementationOnce(async () => {
      await firstGate;
      return {
        code: 0,
        message: 'success',
        data: { attempt_item_id: 'item_1', status: 'saved' },
      };
    });

    // First answer: debounce fires, request is now in flight.
    handleAnswerChange('A');
    vi.advanceTimersByTime(600);

    // Newer answer for the same question before the first response resolves.
    handleAnswerChange('B');

    // Stale response arrives late; it must not finalize the newer pending change.
    gate.release();
    for (let i = 0; i < 20; i += 1) {
      await Promise.resolve();
    }

    // Leaving before B's own debounce fires must still push B to the backend.
    cleanupSession();
    await vi.runAllTimersAsync();

    const answerPayloads = vi
      .mocked(requestModule.request)
      .mock.calls.filter((call) => call[0]?.url.endsWith('/answers'))
      .map((call) => (call[0].data as { user_answer?: string }).user_answer);
    expect(answerPayloads).toContain('B');
  });
});
