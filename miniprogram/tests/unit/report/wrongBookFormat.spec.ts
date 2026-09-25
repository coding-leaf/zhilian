import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getErrorTypeInfo,
  getErrorTypeMeta,
  getResolvedStatusInfo,
  formatWrongCount,
  formatRelativeErrorTime,
  filterWrongRecords,
  generateIdempotencyKey,
  debounce,
  buildContinuePracticePayload,
} from '@/subpackages/report/utils/wrongBookFormat';
import type { WrongRecordItem, WrongRecordQueryParams } from '@/types/report';

describe('wrongBookFormat pure utility functions', () => {
  describe('getErrorTypeInfo and getErrorTypeMeta', () => {
    it('returns conceptual error metadata by default or when unknown', () => {
      const defaultMeta = getErrorTypeInfo();
      expect(defaultMeta.type).toBe('conceptual');
      expect(defaultMeta.label).toBe('概念性错误');
      expect(defaultMeta.color).toBe('#EF4444');
      expect(defaultMeta.bgColor).toBe('#FEF2F2');
      expect(defaultMeta.borderColor).toBe('#FECACA');

      const unknownMeta = getErrorTypeMeta('unknown_type');
      expect(unknownMeta.type).toBe('conceptual');
      expect(unknownMeta.label).toBe('概念性错误');
    });

    it('returns incomplete error metadata', () => {
      const meta = getErrorTypeInfo('incomplete');
      expect(meta.type).toBe('incomplete');
      expect(meta.label).toBe('表述不全');
      expect(meta.color).toBe('#F59E0B');
      expect(meta.bgColor).toBe('#FFFBEB');
      expect(meta.borderColor).toBe('#FDE68A');
    });

    it('returns deviation error metadata', () => {
      const meta = getErrorTypeInfo('deviation');
      expect(meta.type).toBe('deviation');
      expect(meta.label).toBe('审题偏差');
      expect(meta.color).toBe('#3B82F6');
      expect(meta.bgColor).toBe('#EFF6FF');
      expect(meta.borderColor).toBe('#BFDBFE');
    });

    it('returns unanswered error metadata', () => {
      const meta = getErrorTypeInfo('unanswered');
      expect(meta.type).toBe('unanswered');
      expect(meta.label).toBe('未作答');
      expect(meta.color).toBe('#64748B');
      expect(meta.bgColor).toBe('#F1F5F9');
      expect(meta.borderColor).toBe('#E2E8F0');
    });
  });

  describe('getResolvedStatusInfo', () => {
    it('returns mastered metadata when true', () => {
      const res = getResolvedStatusInfo(true);
      expect(res.isMastered).toBe(true);
      expect(res.label).toBe('已攻克');
      expect(res.color).toBe('#10B981');
      expect(res.bgColor).toBe('#ECFDF5');
    });

    it('returns unresolved metadata when false', () => {
      const res = getResolvedStatusInfo(false);
      expect(res.isMastered).toBe(false);
      expect(res.label).toBe('待攻克');
      expect(res.color).toBe('#F59E0B');
      expect(res.bgColor).toBe('#FFFBEB');
    });
  });

  describe('formatWrongCount', () => {
    it('formats defensive values to 答错 1 次', () => {
      expect(formatWrongCount()).toBe('答错 1 次');
      expect(formatWrongCount(null)).toBe('答错 1 次');
      expect(formatWrongCount(undefined)).toBe('答错 1 次');
      expect(formatWrongCount(0)).toBe('答错 1 次');
      expect(formatWrongCount(-3)).toBe('答错 1 次');
      expect(formatWrongCount(NaN)).toBe('答错 1 次');
    });

    it('formats positive integers correctly', () => {
      expect(formatWrongCount(1)).toBe('答错 1 次');
      expect(formatWrongCount(2)).toBe('答错 2 次');
      expect(formatWrongCount(5.8)).toBe('答错 5 次');
    });
  });

  describe('formatRelativeErrorTime', () => {
    const fixedNow = new Date('2026-09-25T12:00:00Z').getTime();

    it('returns 刚刚 for empty, invalid, or future dates', () => {
      expect(formatRelativeErrorTime(null, fixedNow)).toBe('刚刚');
      expect(formatRelativeErrorTime(undefined, fixedNow)).toBe('刚刚');
      expect(formatRelativeErrorTime('', fixedNow)).toBe('刚刚');
      expect(formatRelativeErrorTime('invalid-date', fixedNow)).toBe('刚刚');
      expect(formatRelativeErrorTime(fixedNow + 10_000, fixedNow)).toBe('刚刚');
      expect(formatRelativeErrorTime(fixedNow - 30_000, fixedNow)).toBe('刚刚');
    });

    it('returns minutes ago for < 1 hour', () => {
      const fifteenMinsAgo = fixedNow - 15 * 60_000;
      expect(formatRelativeErrorTime(fifteenMinsAgo, fixedNow)).toBe('15分钟前');
    });

    it('returns hours ago for < 24 hours', () => {
      const threeHoursAgo = fixedNow - 3 * 3600_000;
      expect(formatRelativeErrorTime(threeHoursAgo, fixedNow)).toBe('3小时前');
    });

    it('returns days ago for < 30 days', () => {
      const fiveDaysAgo = fixedNow - 5 * 86400_000;
      expect(formatRelativeErrorTime(fiveDaysAgo, fixedNow)).toBe('5天前');
    });

    it('returns YYYY-MM-DD for dates >= 30 days', () => {
      const fortyDaysAgo = fixedNow - 40 * 86400_000;
      const res = formatRelativeErrorTime(fortyDaysAgo, fixedNow);
      expect(res).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    });
  });

  describe('filterWrongRecords', () => {
    const mockRecords: WrongRecordItem[] = [
      {
        id: 'rec_1',
        practice_id: 'prac_1',
        question_id: 'q_1',
        material_id: 'mat_1',
        knowledge_point_id: 'kp_1',
        question_type: 'single_choice',
        error_type: 'conceptual',
        is_mastered: false,
        created_at: '2026-09-25T10:00:00Z',
      },
      {
        id: 'rec_2',
        practice_id: 'prac_1',
        question_id: 'q_2',
        material_id: 'mat_1',
        knowledge_point_id: 'kp_2',
        question_type: 'short_answer',
        error_type: 'incomplete',
        is_mastered: true,
        created_at: '2026-09-25T10:05:00Z',
      },
      {
        id: 'rec_3',
        practice_id: 'prac_2',
        question_id: 'q_3',
        material_id: 'mat_2',
        knowledge_point_id: 'kp_1',
        question_type: '',
        question_snapshot: {
          stem: '题目快照',
          question_type: 'multiple_choice',
        },
        error_type: 'deviation',
        is_mastered: false,
        created_at: '2026-09-25T10:10:00Z',
      },
    ];

    it('returns empty array when input is invalid or empty', () => {
      expect(filterWrongRecords([], {})).toEqual([]);
      expect(filterWrongRecords(null as unknown as WrongRecordItem[], {})).toEqual([]);
    });

    it('filters by material_id', () => {
      const res = filterWrongRecords(mockRecords, { material_id: 'mat_2' });
      expect(res).toHaveLength(1);
      expect(res[0].id).toBe('rec_3');
    });

    it('filters by knowledge_point_id', () => {
      const res = filterWrongRecords(mockRecords, { knowledge_point_id: 'kp_1' });
      expect(res).toHaveLength(2);
      expect(res.map((r) => r.id)).toEqual(['rec_1', 'rec_3']);
    });

    it('filters by error_type', () => {
      const res = filterWrongRecords(mockRecords, { error_type: 'incomplete' });
      expect(res).toHaveLength(1);
      expect(res[0].id).toBe('rec_2');
    });

    it('filters by is_mastered', () => {
      const mastered = filterWrongRecords(mockRecords, { is_mastered: true });
      expect(mastered).toHaveLength(1);
      expect(mastered[0].id).toBe('rec_2');

      const unmastered = filterWrongRecords(mockRecords, { is_mastered: false });
      expect(unmastered).toHaveLength(2);
      expect(unmastered.map((r) => r.id)).toEqual(['rec_1', 'rec_3']);
    });

    it('filters by question_type (including snapshot fallback)', () => {
      const single = filterWrongRecords(mockRecords, { question_type: 'single_choice' });
      expect(single).toHaveLength(1);
      expect(single[0].id).toBe('rec_1');

      const multi = filterWrongRecords(mockRecords, { question_type: 'multiple_choice' });
      expect(multi).toHaveLength(1);
      expect(multi[0].id).toBe('rec_3');
    });

    it('combines multiple filter criteria', () => {
      const filters: WrongRecordQueryParams = {
        material_id: 'mat_1',
        is_mastered: false,
        error_type: 'conceptual',
      };
      const res = filterWrongRecords(mockRecords, filters);
      expect(res).toHaveLength(1);
      expect(res[0].id).toBe('rec_1');
    });
  });

  describe('generateIdempotencyKey', () => {
    it('generates valid UUID v4 compliant string', () => {
      const key1 = generateIdempotencyKey();
      const key2 = generateIdempotencyKey();

      const uuidV4Regex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      expect(key1).toMatch(uuidV4Regex);
      expect(key2).toMatch(uuidV4Regex);
      expect(key1).not.toBe(key2);
    });
  });

  describe('debounce', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('delays execution and fires only once for rapid triggers', () => {
      const fn = vi.fn();
      const debouncedFn = debounce(fn, 500);

      debouncedFn('first');
      debouncedFn('second');
      debouncedFn('third');

      expect(fn).not.toHaveBeenCalled();

      vi.advanceTimersByTime(499);
      expect(fn).not.toHaveBeenCalled();

      vi.advanceTimersByTime(1);
      expect(fn).toHaveBeenCalledTimes(1);
      expect(fn).toHaveBeenCalledWith('third');
    });

    it('supports cancel method to abort pending call', () => {
      const fn = vi.fn();
      const debouncedFn = debounce(fn, 500);

      debouncedFn('action');
      expect(fn).not.toHaveBeenCalled();

      debouncedFn.cancel();
      vi.advanceTimersByTime(600);

      expect(fn).not.toHaveBeenCalled();
    });
  });

  describe('buildContinuePracticePayload', () => {
    it('builds payload with default options', () => {
      const payload = buildContinuePracticePayload({
        knowledgePointIds: ['kp_10', 'kp_20'],
      });

      expect(payload).toEqual({
        material_id: undefined,
        knowledge_point_ids: ['kp_10', 'kp_20'],
        source_report_id: undefined,
        title: '薄弱点强化练习',
        question_count: 10,
        source_type: 'weakness',
        mode: 'weak_points',
        idempotency_key: undefined,
      });
    });

    it('builds payload with customized options', () => {
      const payload = buildContinuePracticePayload({
        materialId: 'mat_99',
        knowledgePointIds: ['kp_1'],
        sourceReportId: 'rep_1',
        title: '错题巩固练习',
        questionCount: 5,
        sourceType: 'wrong_record',
        mode: 'random',
        idempotencyKey: 'idem-uuid-999',
      });

      expect(payload).toEqual({
        material_id: 'mat_99',
        knowledge_point_ids: ['kp_1'],
        source_report_id: 'rep_1',
        title: '错题巩固练习',
        question_count: 5,
        source_type: 'wrong_record',
        mode: 'random',
        idempotency_key: 'idem-uuid-999',
      });
    });
  });
});
