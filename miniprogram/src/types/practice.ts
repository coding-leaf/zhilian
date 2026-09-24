/**
 * ZhiLian Mini-Program Practice Data Contracts
 * Defines practice sessions, question outlines, answer drafts and submission payloads.
 */

import type { QuestionItem, QuestionType } from './question';

export interface PracticeQuestionOutline {
  id: string;
  type: QuestionType;
  stem: string;
  options?: Array<{ key: string; text: string }>;
  order_index: number;
}

export type PracticeStatus = 'idle' | 'in_progress' | 'paused' | 'submitted' | 'graded';

export interface PracticeSession {
  id: string;
  title: string;
  material_id: string;
  status: PracticeStatus;
  questions: PracticeQuestionOutline[] | QuestionItem[];
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
