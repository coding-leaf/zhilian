import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useReportStore } from '@/stores/reportStore';
import type { DiagnosisReport, UserMasteryOverview, WeakPoint } from '@/types/report';

describe('ReportStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  const mockWeakPoints: WeakPoint[] = [
    {
      knowledge_point_id: 'kn-001',
      knowledge_name: 'Deadlock Conditions',
      current_score: 35,
      previous_score: 50,
      score_delta: -15,
      priority: 1,
      actionable_advice: 'Review Coffman conditions.',
    },
  ];

  const mockReport: DiagnosisReport = {
    id: 'rep-001',
    practice_id: 'session-100',
    overall_score: 82,
    mastery_rate: 82,
    weak_points: mockWeakPoints,
    created_at: '2026-09-01T12:00:00Z',
  };

  const mockOverview: UserMasteryOverview = {
    mastered_count: 5,
    proficient_count: 8,
    weak_count: 2,
    unlearned_count: 1,
    weak_points: mockWeakPoints,
  };

  it('should initialize with null state and default getters', () => {
    const store = useReportStore();
    expect(store.currentReport).toBeNull();
    expect(store.masteryOverview).toBeNull();
    expect(store.weakPoints).toEqual([]);
    expect(store.overallMasteryRate).toBe(0);
    expect(store.weakPointCount).toBe(0);
    expect(store.masteryTier).toBe('unlearned');
  });

  it('should set report and derive getters correctly', () => {
    const store = useReportStore();
    store.setReport(mockReport);

    expect(store.currentReport).toEqual(mockReport);
    expect(store.weakPoints).toEqual(mockWeakPoints);
    expect(store.overallMasteryRate).toBe(82);
    expect(store.weakPointCount).toBe(1);
    expect(store.masteryTier).toBe('proficient'); // >= 70 and < 85 is proficient
  });

  it('should correctly derive masteryTier for all thresholds', () => {
    const store = useReportStore();

    // >= 85: mastered
    store.setReport({ ...mockReport, mastery_rate: 90 });
    expect(store.masteryTier).toBe('mastered');

    // >= 70: proficient
    store.setReport({ ...mockReport, mastery_rate: 70 });
    expect(store.masteryTier).toBe('proficient');

    // >= 40: weak
    store.setReport({ ...mockReport, mastery_rate: 45 });
    expect(store.masteryTier).toBe('weak');

    // < 40: unlearned
    store.setReport({ ...mockReport, mastery_rate: 20 });
    expect(store.masteryTier).toBe('unlearned');
  });

  it('should set mastery overview and weak points', () => {
    const store = useReportStore();
    store.setMasteryOverview(mockOverview);
    expect(store.masteryOverview).toEqual(mockOverview);

    const newPoints: WeakPoint[] = [
      ...mockWeakPoints,
      {
        knowledge_point_id: 'kn-002',
        knowledge_name: 'Virtual Memory',
        current_score: 55,
      },
    ];
    store.setWeakPoints(newPoints);
    expect(store.weakPoints).toHaveLength(2);
    expect(store.weakPointCount).toBe(2);
  });

  it('should clear report state cleanly', () => {
    const store = useReportStore();
    store.setReport(mockReport);
    store.setMasteryOverview(mockOverview);

    store.clearReport();

    expect(store.currentReport).toBeNull();
    expect(store.masteryOverview).toBeNull();
    expect(store.weakPoints).toEqual([]);
    expect(store.overallMasteryRate).toBe(0);
    expect(store.weakPointCount).toBe(0);
    expect(store.masteryTier).toBe('unlearned');
  });

  it('should reset weakPoints when a new report has no weak points (BUG-DIAG-016)', () => {
    const store = useReportStore();
    store.setReport(mockReport);
    expect(store.weakPoints).toHaveLength(1);

    const emptyReport: DiagnosisReport = { ...mockReport, id: 'rep-002', weak_points: [] };
    store.setReport(emptyReport);

    expect(store.currentReport?.id).toBe('rep-002');
    expect(store.weakPoints).toEqual([]);
    expect(store.weakPointCount).toBe(0);
  });

  it('should clear weakPoints when setReport(null) is called (BUG-DIAG-016)', () => {
    const store = useReportStore();
    store.setReport(mockReport);
    expect(store.weakPoints).toHaveLength(1);

    store.setReport(null);

    expect(store.currentReport).toBeNull();
    expect(store.weakPoints).toEqual([]);
  });
});
