/**
 * ZhiLian Mini-Program Question Data Contracts
 * Defines supported question types, options, question items and generation requests.
 */

export type QuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'fill_in_blank'
  | 'short_answer'
  | 'term_explanation'
  | 'case_analysis';

export interface QuestionOption {
  key: string;
  text: string;
  /**
   * Raw backend option field alias (`{ key, content }`).
   * Only present on un-adapted payloads; the API adapter normalizes it to `text`.
   */
  content?: string;
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
  /** Generation batch id shared by all questions produced in one request. */
  batch_id?: string | null;
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
  /**
   * Owning material id. Optional because a course-folder scope (`folder_id`)
   * may be used instead; at least one of `material_id` / `folder_id` is required.
   */
  material_id?: string;
  /** Owning course folder id. When set, generation spans the folder's ready scope. */
  folder_id?: string;
  version_id?: string;
  knowledge_point_id?: string;
  knowledge_point_ids?: string[];
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

/**
 * Quality-check record contract.
 *
 * Authoritative counterpart: `backend/app/schemas/question.py`
 * -> `QuestionQualityCheckResponse`. Field names are taken verbatim from the
 * backend; the deprecated aliases (`rule_code` / `passed` / `message`) are kept
 * optional for smooth migration and MUST NOT be relied upon by new code.
 */
export interface QuestionQualityCheck {
  id?: string;
  question_id?: string;
  batch_id?: string;
  check_type: string;
  is_passed: boolean;
  reason?: string | null;
  similarity_score?: number | null;
  check_metadata?: Record<string, unknown>;
  created_at?: string;
  /** @deprecated use `check_type` */
  rule_code?: string;
  /** @deprecated use `is_passed` */
  passed?: boolean;
  /** @deprecated use `reason` */
  message?: string;
}

export interface QuestionGenerateResponse {
  batch_id: string;
  /** Null/absent for course-folder scope (backend contract). */
  material_id?: string;
  /** Null/absent for course-folder scope (backend contract). */
  version_id?: string;
  /** First covered knowledge point id; null for course-folder scope when empty. */
  knowledge_point_id?: string;
  knowledge_point_ids?: string[];
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
  /** Course folder scope filter. Mutually exclusive with `material_id`. */
  folder_id?: string;
  knowledge_point_id?: string;
  question_type?: string;
  difficulty?: number;
  review_status?: string;
  status?: string;
  /** Filter by generation batch id. */
  batch_id?: string;
  page?: number;
  page_size?: number;
  limit?: number;
  offset?: number;
}

/**
 * Raw backend option element. Authoritative contract:
 * `backend/app/schemas/question.py` -> `QuestionDetailResponse.options` (`{ key, content }`).
 */
export interface RawQuestionOption {
  key?: string;
  content?: string;
  text?: string;
}

/**
 * Raw backend question payload (before adaptation).
 * Authoritative contract: `backend/app/schemas/question.py` -> `QuestionDetailResponse`.
 */
export interface RawQuestionItem {
  id?: string;
  material_id?: string;
  version_id?: string;
  knowledge_point_id?: string;
  source_snippet_id?: string | null;
  question_type?: string;
  status?: string;
  is_deleted?: boolean;
  batch_id?: string | null;
  stem?: string;
  options?: RawQuestionOption[];
  answer?: string;
  analysis?: string;
  difficulty?: number;
  grading_rubric?: Record<string, unknown>;
  source_snippet_ids?: Array<Record<string, unknown>>;
  reason?: string;
  created_at?: string;
  updated_at?: string;
}

/**
 * Raw backend generate response whose nested questions carry raw options.
 * Authoritative contract: `backend/app/schemas/question.py` -> `QuestionGenerateResponse`.
 */
export interface RawQuestionGenerateResponse extends Omit<
  QuestionGenerateResponse,
  'qualified_questions' | 'pending_questions'
> {
  qualified_questions: RawQuestionItem[];
  pending_questions: RawQuestionItem[];
}

/**
 * Raw backend update payload after mapping frontend `text` back to `content`.
 * Authoritative contract: `backend/app/schemas/question.py` -> `QuestionUpdateRequest`.
 */
export type RawQuestionUpdatePayload = Omit<QuestionUpdateRequest, 'options'> & {
  options?: RawQuestionOption[];
};

export interface AskCoachRequest {
  user_prompt: string;
  user_answer?: string;
  grading_points?: string[];
}

export interface AskCoachResponse {
  reply: string;
  suggestions: string[];
}
