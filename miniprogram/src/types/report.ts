/**
 * ZhiLian Mini-Program Diagnosis and Mastery Report Types
 * Defines four-tier mastery levels, weak knowledge points and diagnostic reports.
 */

export type MasteryTier = 'mastered' | 'proficient' | 'weak' | 'unlearned';

export interface WeakPoint {
  knowledge_point_id: string;
  knowledge_name: string;
  current_score: number;
  previous_score?: number | null;
  score_delta?: number;
  priority?: number | string;
  cause_explanation?: string;
  actionable_advice?: string;
}

export interface DiagnosisReport {
  id: string;
  practice_id: string;
  overall_score: number;
  mastery_rate: number;
  weak_points: WeakPoint[];
  created_at: string;
}

export interface UserMasteryOverview {
  mastered_count: number;
  proficient_count: number;
  weak_count: number;
  unlearned_count: number;
  weak_points: WeakPoint[];
}

export interface KnowledgeMasterySummary {
  knowledge_point_id: string;
  current_score: number;
  tier: MasteryTier;
  sample_count: number;
  last_practiced_at?: string;
}

export interface WrongRecordItem {
  id: string;
  practice_id: string;
  question_id: string;
  knowledge_point_id: string;
  question_stem: string;
  question_type: string;
  options?: Array<{ key: string; text: string }>;
  user_answer?: string | string[];
  correct_answer?: string;
  analysis?: string;
  error_type?: string;
  is_mastered: boolean;
  mastered_at?: string | null;
  created_at: string;
}

export interface WrongRecordQueryParams {
  material_id?: string;
  knowledge_point_id?: string;
  error_type?: string;
  is_mastered?: boolean;
  status?: string;
  page?: number;
  page_size?: number;
  limit?: number;
  offset?: number;
}

export interface SelfGradePayload {
  attempt_item_id: string;
  score: number;
  feedback?: string;
}

export interface RegradePayload {
  attempt_item_id: string;
  reason?: string;
}

export interface ContinuePracticePayload {
  material_id: string;
  knowledge_point_ids: string[];
  source_report_id?: string;
  title?: string;
  question_count?: number;
}
