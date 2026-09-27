/**
 * ZhiLian Mini-Program Practice Data Contracts
 * Defines practice sessions, question outlines, answer drafts and submission payloads.
 */

import type { QuestionType } from './question';

export interface PracticeQuestionOutline {
  id: string;
  type: QuestionType;
  stem: string;
  options?: Array<{ key: string; text: string }>;
  order_index: number;
}

export interface PracticeQuestionOption {
  key: string;
  text: string;
}

/**
 * Canonical frontend practice question produced by the practice response adapter.
 *
 * Flattens backend `PracticeItemDetailResponse.question_snapshot` onto the attempt
 * item so consumers only ever read `PracticeSession.questions`.
 */
export interface PracticeQuestionItem {
  id: string;
  question_type: QuestionType | string;
  stem: string;
  options?: PracticeQuestionOption[];
  order_index: number;
  answer?: string;
  analysis?: string;
  difficulty?: number;
  grading_rubric?: Record<string, unknown>;
  source_snippet_id?: string | null;
}

export interface RawPracticeQuestionOption {
  key?: string;
  content?: string;
  text?: string;
}

/**
 * Raw backend question snapshot contract. Authoritative source:
 * `backend/app/schemas/practice.py` -> `QuestionSnapshotDTO`.
 */
export interface RawPracticeQuestionSnapshot {
  stem?: string;
  question_type?: string;
  options?: RawPracticeQuestionOption[];
  answer?: string;
  explanation?: string | null;
  analysis?: string | null;
  source_snippet_id?: string | null;
  source_snippet_ids?: unknown[];
  difficulty?: number;
  grading_rubric?: Record<string, unknown>;
}

/**
 * Raw backend attempt item contract. Authoritative source:
 * `backend/app/schemas/practice.py` -> `PracticeItemDetailResponse`.
 */
export interface RawPracticeItem {
  attempt_item_id?: string;
  id?: string;
  question_id?: string;
  order_index?: number;
  status?: string;
  grading_status?: string | null;
  user_answer?: unknown;
  time_spent_seconds?: number;
  duration_seconds?: number;
  is_answered?: boolean;
  score?: number | null;
  max_score?: number;
  question_snapshot?: RawPracticeQuestionSnapshot;
}

/**
 * Raw backend practice detail contract. Authoritative source:
 * `backend/app/schemas/practice.py` -> `PracticeDetailResponse`.
 */
export interface RawPracticeSession {
  practice_id?: string;
  id?: string;
  title?: string;
  material_id?: string;
  mode?: string;
  status?: string;
  total_count?: number;
  question_count?: number;
  source_type?: string;
  source_report_id?: string | null;
  created_at?: string;
  submitted_at?: string | null;
  completed_at?: string | null;
  current_index?: number;
  time_elapsed_seconds?: number;
  items?: RawPracticeItem[];
  questions?: unknown[];
}

export type PracticeStatus = 'idle' | 'in_progress' | 'paused' | 'submitted' | 'graded';

export interface PracticeSession {
  id: string;
  title: string;
  material_id: string;
  status: PracticeStatus;
  questions: PracticeQuestionItem[];
  /** Raw backend items passthrough used by report pages that need grading snapshots. */
  items?: RawPracticeItem[];
  current_index?: number;
  time_elapsed_seconds?: number;
  created_at?: string;
}

export interface AnswerDraft {
  practice_id: string;
  answers: Record<string, string | string[]>;
  updated_at: number;
}

export interface SubmitPracticeRequest {
  practice_id: string;
  answers: Record<string, string | string[]>;
  time_spent_seconds?: number;
}

export interface CreatePracticePayload {
  title: string;
  material_id: string;
  knowledge_point_ids: string[];
  question_count?: number;
  question_types?: QuestionType[];
  difficulty?: number;
  mode?: 'sequential' | 'random' | 'weak_points';
  source_type?: 'normal' | 'weakness';
  source_report_id?: string;
}

export interface PracticeListQueryParams {
  status?: string;
  material_id?: string;
  offset?: number;
  limit?: number;
  page?: number;
  page_size?: number;
}

export interface SaveAnswerPayload {
  question_id: string;
  user_answer: string | string[];
  time_spent_seconds?: number;
}
