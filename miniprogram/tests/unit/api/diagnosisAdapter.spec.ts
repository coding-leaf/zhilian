import { describe, expect, it } from 'vitest';
import { adaptDiagnosisReport, adaptDiagnosisReportResponse } from '@/api/adapters/diagnosis';
import type { RawDiagnosisReport } from '@/api/adapters/diagnosis';

/**
 * Backend-shaped fixture: uses the canonical DiagnosisReportResponse field names
 * (`weak_knowledge_points`, `score_rate`, `mastery_after`) and deliberately omits
 * the frontend-only fields (`weak_points`, `overall_score`, `mastery_rate`).
 */
const backendReport: RawDiagnosisReport = {
  id: 'rep_2001',
  practice_id: 'prac_2001',
  mastery_before: 0.62,
  mastery_after: 0.78,
  score_rate: 0.78,
  summary: '综合诊断总评',
  created_at: '2026-09-25T11:00:00Z',
  total_questions: 10,
  unanswered_count: 1,
  wrong_count: 2,
  pending_regrade_count: 0,
  is_structure_degraded: false,
  weak_knowledge_points: [
    {
      knowledge_point_id: 'kp_1',
      knowledge_id: 'kp_1',
      knowledge_name: '二叉树遍历',
      knowledge_title: '二叉树遍历',
      current_score: 0.35,
      previous_score: 0.55,
      score_delta: -0.2,
      cause_explanation: '递归基设计不熟练',
      actionable_advice: '加强递归与线索二叉树训练',
    },
  ],
};

describe('diagnosis response adapter (backend -> frontend contract)', () => {
  it('maps backend weak_knowledge_points to frontend weak_points (DIAG-001)', () => {
    const adapted = adaptDiagnosisReport(backendReport);

    expect(adapted.weak_points).toHaveLength(1);
    expect(adapted.weak_points[0].knowledge_point_id).toBe('kp_1');
    expect(adapted.weak_points[0].knowledge_name).toBe('二叉树遍历');
  });

  it('derives overall_score from score_rate when backend omits it (DIAG-002)', () => {
    const adapted = adaptDiagnosisReport(backendReport);

    expect(adapted.overall_score).toBe(78);
  });

  it('derives mastery_rate from mastery_after when backend omits it (DIAG-002)', () => {
    const adapted = adaptDiagnosisReport(backendReport);

    expect(adapted.mastery_rate).toBe(78);
  });

  it('falls back to score_rate for mastery_rate when mastery_after is null', () => {
    const adapted = adaptDiagnosisReport({ ...backendReport, mastery_after: null });

    expect(adapted.mastery_rate).toBe(78);
  });

  it('keeps backend-provided frontend fields untouched (idempotent)', () => {
    const alreadyAdapted: RawDiagnosisReport = {
      ...backendReport,
      overall_score: 91,
      mastery_rate: 88,
      weak_points: [
        {
          knowledge_point_id: 'kp_9',
          knowledge_name: '已归一知识点',
          current_score: 0.5,
        },
      ],
    };

    const adapted = adaptDiagnosisReport(alreadyAdapted);

    expect(adapted.overall_score).toBe(91);
    expect(adapted.mastery_rate).toBe(88);
    expect(adapted.weak_points).toHaveLength(1);
    expect(adapted.weak_points[0].knowledge_name).toBe('已归一知识点');
  });

  it('handles null/undefined payloads defensively', () => {
    const adapted = adaptDiagnosisReport(null);

    expect(adapted.id).toBe('');
    expect(adapted.practice_id).toBe('');
    expect(adapted.weak_points).toEqual([]);
    expect(adapted.overall_score).toBe(0);
    expect(adapted.mastery_rate).toBe(0);
  });

  it('wraps the ApiResponse envelope while preserving code/message', () => {
    const wrapped = adaptDiagnosisReportResponse({
      code: 0,
      message: 'success',
      data: backendReport,
    });

    expect(wrapped.code).toBe(0);
    expect(wrapped.message).toBe('success');
    expect(wrapped.data.overall_score).toBe(78);
    expect(wrapped.data.weak_points).toHaveLength(1);
  });
});
