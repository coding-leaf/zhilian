/**
 * Diagnosis report response adapter.
 *
 * Single adaptation boundary between the backend diagnosis contract
 * (`DiagnosisReportResponse`: `weak_knowledge_points`, `score_rate`, `mastery_after`)
 * and the frontend `DiagnosisReport` consumers (`weak_points`, `overall_score`, `mastery_rate`).
 *
 * Authoritative contract: backend/app/schemas/diagnosis.py
 * See spec: backend/quality-guidelines.md "Backend<->Frontend Response Field-Name Contract Pinning".
 *
 * The adapter is idempotent: when a payload already carries frontend fields
 * (`weak_points` / `overall_score` / `mastery_rate`), those values always win.
 */

import type { ApiResponse } from '../../types/common';
import type { DiagnosisReport, WeakPoint } from '../../types/report';

/**
 * Backend-shaped diagnosis report payload.
 *
 * Extends the frontend contract so already-normalized payloads pass through,
 * while declaring the backend-only field names this adapter consumes.
 */
export interface RawDiagnosisReport extends Partial<DiagnosisReport> {
  weak_knowledge_points?: WeakPoint[] | null;
}

/**
 * Normalizes a raw backend diagnosis report payload into the frontend `DiagnosisReport`.
 *
 * Derivation rules (backend-provided values always win):
 * - `weak_points` = `weak_points` ?? `weak_knowledge_points` ?? `[]`
 * - `overall_score` = `overall_score` ?? `Math.round(score_rate * 100)`
 * - `mastery_rate` = `mastery_rate` ?? `Math.round(mastery_after * 100)` (falls back to `score_rate`)
 *
 * @param raw Raw backend payload (or null/undefined).
 * @returns Adapted frontend diagnosis report with stable defaults.
 */
export function adaptDiagnosisReport(raw: RawDiagnosisReport | null | undefined): DiagnosisReport {
  const source: RawDiagnosisReport = raw ?? {};

  const scoreRate = typeof source.score_rate === 'number' ? source.score_rate : undefined;
  const weakPoints = Array.isArray(source.weak_points)
    ? source.weak_points
    : Array.isArray(source.weak_knowledge_points)
      ? source.weak_knowledge_points
      : [];

  const overallScore =
    typeof source.overall_score === 'number'
      ? source.overall_score
      : Math.round((scoreRate ?? 0) * 100);

  const masteryRate =
    typeof source.mastery_rate === 'number'
      ? source.mastery_rate
      : Math.round((source.mastery_after ?? scoreRate ?? 0) * 100);

  return {
    id: source.id ?? '',
    practice_id: source.practice_id ?? '',
    mastery_before: source.mastery_before ?? null,
    mastery_after: source.mastery_after ?? null,
    overall_score: overallScore,
    score_rate: scoreRate,
    mastery_rate: masteryRate,
    total_questions: source.total_questions ?? 0,
    unanswered_count: source.unanswered_count ?? 0,
    wrong_count: source.wrong_count ?? 0,
    pending_regrade_count: source.pending_regrade_count ?? 0,
    is_structure_degraded: source.is_structure_degraded ?? false,
    weak_points: weakPoints,
    summary: source.summary ?? null,
    created_at: source.created_at ?? '',
  };
}

/**
 * Adapts a full `ApiResponse` envelope so API modules can return the frontend contract.
 *
 * @param res Raw backend response envelope.
 * @returns Response envelope whose `data` is a `DiagnosisReport`.
 */
export function adaptDiagnosisReportResponse(
  res: ApiResponse<RawDiagnosisReport>,
): ApiResponse<DiagnosisReport> {
  return {
    ...res,
    data: adaptDiagnosisReport(res.data),
  };
}
