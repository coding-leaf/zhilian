/**
 * ZhiLian Mini-Program Question Data Contracts
 * Defines supported question types, options, question items and generation requests.
 */

export type QuestionType =
  'single_choice' | 'multiple_choice' | 'true_false' | 'fill_in_blank' | 'short_answer';

export interface QuestionOption {
  key: string;
  text: string;
}

export interface QuestionItem {
  id: string;
  material_id: string;
  version_id: string;
  knowledge_point_id: string;
  source_snippet_id?: string | null;
  question_type: QuestionType;
  status?: 'available' | 'pending_review' | string;
  is_deleted?: boolean;
  stem: string;
  options?: QuestionOption[];
  answer?: string;
  analysis?: string;
  difficulty: number;
  grading_rubric?: Record<string, unknown>;
  source_snippet_ids?: Array<Record<string, unknown>>;
  reason?: string;
  created_at?: string;
  updated_at?: string;
}

export interface QuestionGenerateRequest {
  material_id: string;
  version_id?: string;
  knowledge_point_id: string;
  count?: number;
  difficulty?: number;
  question_types?: QuestionType[];
  max_retries?: number;
}

export type GenerationRequest = QuestionGenerateRequest;

export interface QuestionUpdateRequest {
  stem?: string;
  options?: QuestionOption[];
  answer?: string;
  analysis?: string;
  difficulty?: number;
  grading_rubric?: Record<string, unknown>;
  status?: string;
  reason?: string;
  edit_reason?: string;
}

export type QuestionAuditAction = 'CREATE' | 'EDIT' | 'DELETE' | 'REGENERATE' | string;

export interface QuestionAuditItem {
  id: string;
  question_id: string;
  action: QuestionAuditAction;
  changed_fields: string[];
  before_payload: Record<string, unknown>;
  after_payload: Record<string, unknown>;
  reason?: string | null;
  created_at: string;
}

export type QuestionEditLogItem = QuestionAuditItem;

export interface QuestionAuditLogsResponse {
  question_id: string;
  logs: QuestionAuditItem[];
}

export type QuestionEditLogListResponse = QuestionAuditLogsResponse;

export interface QuestionDeleteResponse {
  id: string;
  is_deleted: boolean;
  message?: string;
}

export interface QuestionQualityCheck {
  rule_code: string;
  passed: boolean;
  message?: string;
}

export interface QuestionGenerateResponse {
  batch_id: string;
  material_id: string;
  version_id: string;
  knowledge_point_id: string;
  total_generated: number;
  qualified_count: number;
  pending_count: number;
  retry_count: number;
  qualified_questions: QuestionItem[];
  pending_questions: QuestionItem[];
  quality_checks: QuestionQualityCheck[];
}

export interface QuestionListQueryParams {
  material_id?: string;
  knowledge_point_id?: string;
  question_type?: string;
  difficulty?: number;
  review_status?: string;
  status?: string;
  page?: number;
  page_size?: number;
  limit?: number;
  offset?: number;
}
