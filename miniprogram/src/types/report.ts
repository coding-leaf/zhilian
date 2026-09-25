/**
 * ZhiLian Mini-Program Diagnosis and Mastery Report Types
 * Defines four-tier mastery levels, weak knowledge points and diagnostic reports.
 * Complies with docs/DESIGN.md & spec ZL-135.
 */

export type MasteryTier = 'mastered' | 'proficient' | 'weak' | 'unlearned';

export type GradingChannel = 'offline' | 'ai' | 'user_self';

export type ItemGradingStatus = 'correct' | 'wrong' | 'pending_regrade' | 'unanswered';

export type GradingStatus = ItemGradingStatus;

export interface AssociatedMistake {
  question_id: string;
  is_negation_inversion?: boolean;
}

export interface WeakPoint {
  knowledge_point_id: string;
  knowledge_name: string;
  current_score: number;
  previous_score?: number | null;
  score_delta?: number;
  priority?: number | string;
  cause_type?: string;
  cause_explanation?: string;
  actionable_advice?: string;
  associated_mistakes?: AssociatedMistake[];
  // Compatibility fields
  knowledge_id?: string;
  knowledge_title?: string;
}

export interface DiagnosisReport {
  id: string;
  practice_id: string;
  mastery_before?: number | null;
  mastery_after?: number | null;
  overall_score: number;
  score_rate?: number;
  mastery_rate: number;
  total_questions?: number;
  unanswered_count?: number;
  wrong_count?: number;
  pending_regrade_count?: number;
  is_structure_degraded?: boolean;
  weak_points: WeakPoint[];
  summary?: string | null;
  created_at: string;
}

export interface SnippetHighlightPart {
  text: string;
  isHighlight: boolean;
}

export interface MasteryTierInfo {
  tier: MasteryTier;
  label: string;
  color: string;
  bgColor: string;
  fillColor: string;
}

export interface GradingStatusInfo {
  status: ItemGradingStatus;
  label: string;
  color: string;
  bgColor: string;
  borderColor?: string;
  textColor?: string;
}

export interface OriginalSnippet {
  id?: string;
  snippet_content?: string;
  chapter_title?: string;
  page_index?: number;
  keywords?: string[];
}

export interface AttemptGradingItem {
  attempt_item_id: string;
  id?: string;
  question_id?: string;
  order_index: number;
  status: string;
  user_answer?: unknown;
  time_spent_seconds?: number;
  duration_seconds?: number;
  score?: number | null;
  max_score?: number;
  is_answered?: boolean;
  question_snapshot: {
    id?: string;
    stem: string;
    question_type: string;
    options?: Array<{ key: string; text: string }>;
    answer?: string;
    analysis?: string;
    grading_rubric?: Record<string, unknown>;
    knowledge_point_id?: string;
    knowledge_name?: string;
    source_snippet?: OriginalSnippet | null;
    source_snippet_id?: string | null;
    hit_keywords?: string[];
    missing_keywords?: string[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
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
