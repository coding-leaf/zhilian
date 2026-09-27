import { describe, expect, it, beforeEach, vi } from 'vitest';
import {
  formatDurationSeconds,
  formatElapsedDuration,
  isAnswerFilled,
  checkUnansweredQuestions,
  calculateQuestionStats,
  createOrUpdateDraft,
  enqueueUnsyncedAnswer,
  markDraftSynced,
  extractPendingSyncItems,
  saveDraftToStorage,
  loadDraftFromStorage,
  clearDraftFromStorage,
  generateIdempotencyKey,
} from '@/subpackages/practice/utils/draft';
import { storage } from '@/utils/storage';
import { AppError } from '@/utils/error';
import type { PracticeDraftRecord } from '@/subpackages/practice/types/draft';

describe('Practice Draft Utilities (draft.ts)', () => {
  const memoryStore: Record<string, unknown> = {};

  beforeEach(() => {
    Object.keys(memoryStore).forEach((k) => delete memoryStore[k]);

    uni.getStorageSync = ((key: string) =>
      memoryStore[key] ?? null) as unknown as typeof uni.getStorageSync;
    uni.setStorageSync = (key: string, data: unknown) => {
      memoryStore[key] = data;
    };
    uni.removeStorageSync = (key: string) => {
      delete memoryStore[key];
    };
    uni.clearStorageSync = () => {
      Object.keys(memoryStore).forEach((k) => delete memoryStore[k]);
    };

    storage.clear();
    vi.restoreAllMocks();
  });

  describe('formatDurationSeconds', () => {
    it('formats less than 1 hour correctly as mm:ss', () => {
      expect(formatDurationSeconds(0)).toBe('00:00');
      expect(formatDurationSeconds(5)).toBe('00:05');
      expect(formatDurationSeconds(59)).toBe('00:59');
      expect(formatDurationSeconds(65)).toBe('01:05');
      expect(formatDurationSeconds(3599)).toBe('59:59');
    });

    it('formats 1 hour and above correctly as hh:mm:ss', () => {
      expect(formatDurationSeconds(3600)).toBe('01:00:00');
      expect(formatDurationSeconds(3661)).toBe('01:01:01');
      expect(formatDurationSeconds(7325)).toBe('02:02:05');
    });

    it('handles negative or invalid seconds defensively', () => {
      expect(formatDurationSeconds(-10)).toBe('00:00');
      expect(formatDurationSeconds(Number.NaN)).toBe('00:00');
      expect(formatElapsedDuration(120)).toBe('02:00');
    });
  });

  describe('isAnswerFilled', () => {
    it('identifies empty or falsy answers correctly', () => {
      expect(isAnswerFilled(null)).toBe(false);
      expect(isAnswerFilled(undefined)).toBe(false);
      expect(isAnswerFilled('')).toBe(false);
      expect(isAnswerFilled('   ')).toBe(false);
      expect(isAnswerFilled([])).toBe(false);
      expect(isAnswerFilled(['', '  '])).toBe(false);
    });

    it('identifies filled answers for strings and string arrays', () => {
      expect(isAnswerFilled('A')).toBe(true);
      expect(isAnswerFilled('  Option B  ')).toBe(true);
      expect(isAnswerFilled(['A'])).toBe(true);
      expect(isAnswerFilled(['A', 'B'])).toBe(true);
    });

    it('handles draft item objects with user_answer property', () => {
      expect(isAnswerFilled({ user_answer: 'True' })).toBe(true);
      expect(isAnswerFilled({ user_answer: '   ' })).toBe(false);
      expect(isAnswerFilled({ user_answer: ['B'] })).toBe(true);
      expect(isAnswerFilled({ other_prop: 123 })).toBe(false);
    });
  });

  describe('checkUnansweredQuestions & calculateQuestionStats', () => {
    const questionIds = ['q1', 'q2', 'q3', 'q4'];

    it('calculates answered and unanswered counts with 1-based indices', () => {
      const answers = {
        q1: 'A',
        q2: '',
        q3: ['B', 'C'],
        q4: null,
      };

      const result = checkUnansweredQuestions(questionIds, answers);
      expect(result.total).toBe(4);
      expect(result.answeredCount).toBe(2);
      expect(result.unansweredCount).toBe(2);
      expect(result.unansweredIndices).toEqual([2, 4]);

      const aliasResult = calculateQuestionStats(questionIds, answers);
      expect(aliasResult).toEqual(result);
    });

    it('handles all answered and all unanswered states', () => {
      const allAnswered = {
        q1: 'A',
        q2: 'B',
        q3: 'C',
        q4: 'D',
      };
      const resultAll = checkUnansweredQuestions(questionIds, allAnswered);
      expect(resultAll.answeredCount).toBe(4);
      expect(resultAll.unansweredCount).toBe(0);
      expect(resultAll.unansweredIndices).toEqual([]);

      const resultNone = checkUnansweredQuestions(questionIds, {});
      expect(resultNone.answeredCount).toBe(0);
      expect(resultNone.unansweredCount).toBe(4);
      expect(resultNone.unansweredIndices).toEqual([1, 2, 3, 4]);
    });
  });

  describe('createOrUpdateDraft & enqueueUnsyncedAnswer', () => {
    it('creates a new draft record when existing is null', () => {
      const record = createOrUpdateDraft(null, 'p_100', 'q_1', 'A', 15);
      expect(record.practice_id).toBe('p_100');
      expect(record.items.q_1).toBeDefined();
      expect(record.items.q_1.user_answer).toBe('A');
      expect(record.items.q_1.time_spent_seconds).toBe(15);
      expect(record.items.q_1.sync_status).toBe('pending');
    });

    it('accumulates time spent and preserves other answers immutably', () => {
      const record1 = createOrUpdateDraft(null, 'p_100', 'q_1', 'A', 10);
      const record2 = createOrUpdateDraft(record1, 'p_100', 'q_2', ['B', 'C'], 5);
      const record3 = enqueueUnsyncedAnswer(record2, 'q_1', 'D', 8);

      expect(record3.items.q_1.user_answer).toBe('D');
      expect(record3.items.q_1.time_spent_seconds).toBe(18); // 10 + 8
      expect(record3.items.q_2.user_answer).toEqual(['B', 'C']);
      expect(record3.items.q_2.time_spent_seconds).toBe(5);

      // Verify immutability
      expect(record1.items.q_2).toBeUndefined();
      expect(record2.items.q_1.user_answer).toBe('A');
    });

    it('handles negative or zero duration safely', () => {
      const record = createOrUpdateDraft(null, 'p_100', 'q_1', 'A', -5);
      expect(record.items.q_1.time_spent_seconds).toBe(0);
    });

    it('preserves an existing submit_key when the draft is updated (PRAC-003)', () => {
      const first: PracticeDraftRecord = {
        ...createOrUpdateDraft(null, 'p_100', 'q_1', 'A', 1),
        submit_key: 'key-1',
      };
      const updated = createOrUpdateDraft(first, 'p_100', 'q_2', 'B', 1);
      expect(updated.submit_key).toBe('key-1');
    });
  });

  describe('saveDraftToStorage degradation (PRAC-004)', () => {
    it('swallows storage overflow failures without throwing', () => {
      const draft = createOrUpdateDraft(null, 'p_overflow', 'q_1', 'A', 5);
      vi.spyOn(storage, 'setItem').mockImplementation(() => {
        throw new AppError(10001, 'Storage key forbidden');
      });

      expect(() => saveDraftToStorage('p_overflow', draft)).not.toThrow();
      // The in-memory record stays intact for the caller and remote sync.
      expect(draft.items.q_1.user_answer).toBe('A');
    });

    it('never throws when clearing a draft fails after a successful submit (PRAC-004)', () => {
      saveDraftToStorage('p_clear', createOrUpdateDraft(null, 'p_clear', 'q_1', 'A', 5));

      vi.spyOn(storage, 'setItem').mockImplementation(() => {
        throw new AppError(10001, 'Storage key forbidden');
      });

      expect(() => clearDraftFromStorage('p_clear')).not.toThrow();
    });
  });

  describe('markDraftSynced & extractPendingSyncItems', () => {
    it('marks specified question items as synced', () => {
      let draft: PracticeDraftRecord | null = null;
      draft = createOrUpdateDraft(draft, 'p_1', 'q_1', 'A', 5);
      draft = createOrUpdateDraft(draft, 'p_1', 'q_2', 'B', 10);

      const syncedDraft = markDraftSynced(draft, ['q_1']);
      expect(syncedDraft.items.q_1.sync_status).toBe('synced');
      expect(syncedDraft.items.q_2.sync_status).toBe('pending');

      const nullSynced = markDraftSynced(null, ['q_1']);
      expect(nullSynced.practice_id).toBe('');
    });

    it('extracts pending and failed sync items only', () => {
      let draft: PracticeDraftRecord | null = null;
      draft = createOrUpdateDraft(draft, 'p_1', 'q_1', 'A', 5);
      draft = createOrUpdateDraft(draft, 'p_1', 'q_2', 'B', 10);
      draft = markDraftSynced(draft, ['q_1']);

      // Inject a failed item for test
      draft.items.q_3 = {
        question_id: 'q_3',
        user_answer: 'C',
        time_spent_seconds: 3,
        sync_status: 'failed',
        updated_at: Date.now(),
      };

      const pendingItems = extractPendingSyncItems(draft);
      expect(pendingItems).toHaveLength(2);
      expect(pendingItems.map((i) => i.question_id)).toEqual(['q_2', 'q_3']);

      expect(extractPendingSyncItems(null)).toEqual([]);
    });
  });

  describe('Storage Integration (saveDraftToStorage, loadDraftFromStorage, clearDraftFromStorage)', () => {
    it('saves and loads draft record to/from storage under practice_drafts key', () => {
      const draft = createOrUpdateDraft(null, 'p_200', 'q_1', 'A', 12);
      saveDraftToStorage('p_200', draft);

      const loaded = loadDraftFromStorage('p_200');
      expect(loaded).not.toBeNull();
      expect(loaded?.practice_id).toBe('p_200');
      expect(loaded?.items.q_1.user_answer).toBe('A');

      const notFound = loadDraftFromStorage('p_non_existent');
      expect(notFound).toBeNull();
    });

    it('clears specific practice draft from storage without breaking others', () => {
      const draftA = createOrUpdateDraft(null, 'p_A', 'q_1', 'A', 10);
      const draftB = createOrUpdateDraft(null, 'p_B', 'q_2', 'B', 20);

      saveDraftToStorage('p_A', draftA);
      saveDraftToStorage('p_B', draftB);

      clearDraftFromStorage('p_A');
      expect(loadDraftFromStorage('p_A')).toBeNull();
      expect(loadDraftFromStorage('p_B')).not.toBeNull();

      // Clear non-existent safely
      expect(() => clearDraftFromStorage('p_none')).not.toThrow();
    });

    it('generates valid UUIDv4 idempotency key', () => {
      const key1 = generateIdempotencyKey();
      const key2 = generateIdempotencyKey();
      expect(key1).toBeTypeOf('string');
      expect(key2).toBeTypeOf('string');
      expect(key1).not.toBe(key2);
      // Valid UUID v4 pattern
      const uuidV4Regex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      expect(uuidV4Regex.test(key1)).toBe(true);
      expect(uuidV4Regex.test(key2)).toBe(true);
    });
  });
});
