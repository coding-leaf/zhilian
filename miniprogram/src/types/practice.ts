import type { QuestionItem, QuestionOption, QuestionType, SourceSnippet } from './question'

export type PracticeQuestionItem = QuestionItem

/** 单次练习题数上限（对齐后端 PracticeCreateRequest.question_count le=50）。 */
export const MAX_PRACTICE_QUESTIONS = 50

// 练习生命周期：与 backend/app/models/practice.py::PracticeStatus 保持一致
export type PracticeStatus =
  | 'not_started'
  | 'in_progress'
  | 'paused'
  | 'submitted'
  | 'timeout'
  | 'partially_graded'
  | 'completed'

// 单题判题状态：与 backend PracticeItemDetailResponse.grading_status 保持一致
export type GradingStatus = 'unanswered' | 'pending_regrade' | 'graded'

export interface PracticeItem {
  attempt_item_id: string
  id?: string | null
  question_id?: string | null
  order_index: number
  status: string
  user_answer?: unknown
  is_answered: boolean
  score?: number | null
  grading_status?: GradingStatus | null
  max_score: number
  hit_keywords?: string[]
  missing_keywords?: string[]
  source_snippet?: SourceSnippet | null
  question_snapshot: QuestionItem
}

export interface PracticeSession {
  id: string
  practice_id?: string
  title: string
  material_id?: string | null
  folder_id?: string | null
  mode?: string
  status: PracticeStatus
  questions: QuestionItem[]
  items?: PracticeItem[]
  total_count: number
  completed_count?: number
  total_score?: number | null
  max_score?: number | null
  source_type?: string
  source_report_id?: string | null
  completed_at?: string | null
  submitted_at?: string | null
  created_at?: string
  user_answers?: Record<string, unknown>
}

export interface PracticeSummary {
  id: string
  practice_id?: string | null
  material_id?: string | null
  folder_id?: string | null
  folder_name?: string | null
  material_title?: string | null
  title: string
  status: PracticeStatus
  question_count: number
  total_count?: number | null
  completed_count?: number | null
  mode?: string | null
  total_score?: number | null
  max_score?: number | null
  score_rate?: number | null
  graded_count?: number
  pending_regrade_count?: number
  source_type?: string
  created_at?: string | null
  submitted_at?: string | null
  completed_at?: string | null
}

export interface CreatePracticeParams {
  title: string
  material_id?: string
  folder_id?: string
  knowledge_point_ids?: string[]
  question_ids?: string[]
  question_count?: number
  question_types?: QuestionType[]
  difficulty?: number
  mode?: string
  source_type?: string
  source_report_id?: string
}

export interface PracticeListQuery {
  status?: string
  material_id?: string
  offset?: number
  limit?: number
}

export interface PracticeListResult {
  items: PracticeSummary[]
  total: number
  limit: number
  offset: number
}

/**
 * 结果页/报告页统一卷面投影。
 * 由练习详情的 items[].question_snapshot 与判题状态组合而来，不依赖诊断报告。
 */
export interface AttemptResult {
  attemptItemId: string
  questionId: string
  knowledgePointId?: string
  knowledgePointName?: string
  orderIndex: number
  type: QuestionType
  stem: string
  options: QuestionOption[]
  userAnswer: unknown
  correctAnswer: unknown
  isAnswered: boolean
  gradingStatus: GradingStatus | 'grading'
  isPending: boolean
  score: number | null
  maxScore: number
  isCorrect: boolean | null
  hitKeywords: string[]
  missingKeywords: string[]
  gradingPoints: string[]
  analysis?: string
  sourceQuote?: string
}
