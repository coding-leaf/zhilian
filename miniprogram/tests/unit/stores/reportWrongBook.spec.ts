import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useReportStore } from '@/stores/reportStore';
import type { WrongRecordItem } from '@/types/report';

describe('ReportStore - Wrong Book State Flow', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  const mockItem1: WrongRecordItem = {
    id: 'wr-001',
    practice_id: 'session-101',
    question_id: 'q-101',
    knowledge_point_id: 'kp-deadlock',
    question_type: 'single_choice',
    question_stem: '死锁的四个必要条件不包括以下哪一项？',
    error_type: 'conceptual',
    error_count: 2,
    is_mastered: false,
    created_at: '2026-09-25T10:00:00Z',
    question_snapshot: {
      stem: '死锁的四个必要条件不包括以下哪一项？',
      question_type: 'single_choice',
      options: [
        { key: 'A', text: '互斥条件' },
        { key: 'B', text: '请求与保持条件' },
        { key: 'C', text: '不可剥夺条件' },
        { key: 'D', text: '动态分配条件' },
      ],
      answer: 'D',
    },
  };

  const mockItem2: WrongRecordItem = {
    id: 'wr-002',
    practice_id: 'session-101',
    question_id: 'q-102',
    knowledge_point_id: 'kp-paging',
    question_type: 'true_false',
    question_stem: '请求分页存储管理中，页面置换算法只在发生缺页中断时调用。',
    error_type: 'incomplete',
    error_count: 1,
    is_mastered: true,
    mastered_at: '2026-09-25T11:00:00Z',
    created_at: '2026-09-25T10:05:00Z',
  };

  it('should initialize with empty wrong records and default pagination', () => {
    const store = useReportStore();
    expect(store.wrongRecords).toEqual([]);
    expect(store.wrongBookList).toEqual([]);
    expect(store.wrongRecordTotal).toBe(0);
    expect(store.selectedRecordIds).toEqual([]);
    expect(store.selectedRecordCount).toBe(0);
    expect(store.wrongPage).toBe(1);
    expect(store.wrongPageSize).toBe(20);
    expect(store.wrongHasMore).toBe(true);
    expect(store.wrongFilters).toEqual({});
  });

  it('should set wrong records and update total and hasMore correctly', () => {
    const store = useReportStore();
    store.setWrongRecords([mockItem1], 2);

    expect(store.wrongRecords).toHaveLength(1);
    expect(store.wrongBookList).toHaveLength(1);
    expect(store.wrongRecordTotal).toBe(2);
    expect(store.wrongHasMore).toBe(true);

    // Using alias setWrongBookList
    store.setWrongBookList([mockItem1, mockItem2], 2);
    expect(store.wrongRecords).toHaveLength(2);
    expect(store.wrongRecordTotal).toBe(2);
    expect(store.wrongHasMore).toBe(false);
  });

  it('should append wrong records and calculate hasMore against total', () => {
    const store = useReportStore();
    store.setWrongRecords([mockItem1], 3);
    expect(store.wrongRecords).toHaveLength(1);
    expect(store.wrongHasMore).toBe(true);

    store.appendWrongRecords([mockItem2], 3);
    expect(store.wrongRecords).toHaveLength(2);
    expect(store.wrongRecords[1].id).toBe('wr-002');
    expect(store.wrongHasMore).toBe(true);

    const mockItem3 = { ...mockItem1, id: 'wr-003' };
    store.appendWrongRecords([mockItem3]);
    expect(store.wrongRecords).toHaveLength(3);
    expect(store.wrongHasMore).toBe(false);
  });

  it('should optimistically update single wrong record mastered status', () => {
    const store = useReportStore();
    store.setWrongRecords([mockItem1, mockItem2], 2);

    // Mark wr-001 as mastered
    store.updateWrongRecordMastered('wr-001', true);
    expect(store.wrongRecords[0].is_mastered).toBe(true);
    expect(store.wrongRecords[0].mastered_at).toBeTruthy();

    // Mark wr-001 as unmastered
    store.updateWrongRecordMastered('wr-001', false);
    expect(store.wrongRecords[0].is_mastered).toBe(false);
    expect(store.wrongRecords[0].mastered_at).toBeNull();

    // Custom masteredAt timestamp
    store.updateWrongRecordMastered('wr-002', true, '2026-09-25T12:00:00Z');
    expect(store.wrongRecords[1].mastered_at).toBe('2026-09-25T12:00:00Z');
  });

  it('should handle multi-selection actions properly', () => {
    const store = useReportStore();
    expect(store.selectedRecordIds).toEqual([]);
    expect(store.selectedRecordCount).toBe(0);

    // Toggle select
    store.toggleSelectRecord('wr-001');
    expect(store.selectedRecordIds).toEqual(['wr-001']);
    expect(store.selectedRecordCount).toBe(1);

    store.toggleSelectRecord('wr-002');
    expect(store.selectedRecordIds).toEqual(['wr-001', 'wr-002']);
    expect(store.selectedRecordCount).toBe(2);

    // Toggle unselect
    store.toggleSelectRecord('wr-001');
    expect(store.selectedRecordIds).toEqual(['wr-002']);
    expect(store.selectedRecordCount).toBe(1);

    // Select all
    store.selectAllRecords(['wr-001', 'wr-002', 'wr-003']);
    expect(store.selectedRecordCount).toBe(3);

    // Clear selection
    store.clearSelectedRecords();
    expect(store.selectedRecordIds).toEqual([]);
    expect(store.selectedRecordCount).toBe(0);
  });

  it('should update filters and pagination state', () => {
    const store = useReportStore();
    store.setWrongFilters({
      is_mastered: false,
      error_type: 'conceptual',
      question_type: 'single_choice',
    });
    expect(store.wrongFilters).toEqual({
      is_mastered: false,
      error_type: 'conceptual',
      question_type: 'single_choice',
    });

    store.setWrongPage(3);
    expect(store.wrongPage).toBe(3);

    store.setWrongHasMore(false);
    expect(store.wrongHasMore).toBe(false);
  });

  it('should reset wrong records and state via resetWrongBookState', () => {
    const store = useReportStore();
    store.setWrongRecords([mockItem1], 5);
    store.toggleSelectRecord('wr-001');
    store.setWrongFilters({ error_type: 'conceptual' });
    store.setWrongPage(2);
    store.setWrongHasMore(false);

    store.resetWrongBookState();

    expect(store.wrongRecords).toEqual([]);
    expect(store.wrongRecordTotal).toBe(0);
    expect(store.selectedRecordIds).toEqual([]);
    expect(store.wrongFilters).toEqual({});
    expect(store.wrongPage).toBe(1);
    expect(store.wrongHasMore).toBe(true);
  });

  it('should reset both report and wrong book state on resetReportState', () => {
    const store = useReportStore();
    store.setWrongRecords([mockItem1], 1);
    store.toggleSelectRecord('wr-001');

    store.resetReportState();

    expect(store.wrongRecords).toEqual([]);
    expect(store.selectedRecordIds).toEqual([]);
    expect(store.currentReport).toBeNull();
  });
});
