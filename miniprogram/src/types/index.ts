export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

export interface UserProfile {
  id: string
  nickname: string
  avatar_url?: string
  phone?: string
  created_at?: string
  updated_at?: string
}

export interface UpdateUserProfilePayload {
  nickname?: string
  avatar_url?: string
}

export interface LoginResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in?: number
  user?: UserProfile
}

// 课程文件夹
export interface FolderItem {
  id: string
  name: string
  parent_id?: string | null
  sort_order: number
  is_archived: boolean
  archived_at?: string | null
  purge_after?: string | null
  material_count: number
  ready_material_count: number
  knowledge_point_count: number
  question_count: number
  last_practice_at?: string | null
  created_at: string
  updated_at: string
}

export interface FolderListResult {
  items: FolderItem[]
  total: number
}

export interface FolderKnowledgePointItem {
  id: string
  name: string
  level: number
  parent_id?: string | null
}

export interface FolderKnowledgePointGroup {
  material_id: string
  material_title: string
  knowledge_points: FolderKnowledgePointItem[]
}

export interface FolderKnowledgePointsResult {
  folder_id: string
  groups: FolderKnowledgePointGroup[]
  total: number
}

// 资料状态机：与 backend/app/models/material.py 的主状态保持一致
export type MaterialStatus = 'pending' | 'parsing' | 'ready' | 'failed' | 'retake_required'

export interface MaterialItem {
  id: string
  title: string
  file_format?: string
  file_size?: number
  source_type?: string
  status: MaterialStatus
  created_at: string
  updated_at?: string
  error_message?: string
  page_count?: number
  current_version_id?: string
  folder_id?: string | null
  parse_status?: string | null
  progress_percentage?: number | null
  key_points_count?: number | null
}

export interface MaterialListResult {
  items: MaterialItem[]
  total: number
  limit: number
  offset: number
}

export interface KnowledgeTreeNode {
  id: string
  material_id: string
  version_id: string
  name: string
  level: number
  parent_id?: string | null
  order_index: number
  description?: string | null
  key_phrases?: string[]
  children?: KnowledgeTreeNode[]
}

export interface KnowledgeTreeResult {
  material_id: string
  version_id: string
  nodes: KnowledgeTreeNode[]
}

export interface KnowledgePointDetail {
  id: string
  material_id: string
  version_id: string
  name: string
  level: number
  parent_id?: string | null
  order_index: number
  description?: string | null
  key_phrases?: string[]
  snippet_count?: number
  created_at: string
  updated_at?: string
}

export interface KnowledgeSnippet {
  id: string
  snippet_id?: string
  content: string
  page_number?: number
  similarity?: number
  section_title?: string
}

export interface PointSourceListResult {
  knowledge_point_id: string
  snippets: KnowledgeSnippet[]
}

// 七大题型：与 backend/app/models/question.py::QuestionType 保持一致
export type QuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'fill_in_blank'
  | 'term_explanation'
  | 'short_answer'
  | 'case_analysis'

// 后端标注为主观题的题型集合
export const SUBJECTIVE_QUESTION_TYPES: QuestionType[] = [
  'term_explanation',
  'short_answer',
  'case_analysis',
]

export interface QuestionOption {
  key: string
  content: string
}

export interface SourceSnippet {
  id?: string | null
  chapter_title: string
  page_index: number
  snippet_content: string
}

export interface QuestionItem {
  id: string
  material_id?: string
  version_id?: string
  knowledge_point_id?: string
  batch_id?: string | null
  type: QuestionType
  stem: string
  options?: QuestionOption[]
  answer?: string | string[] | number | null
  explanation?: string
  analysis?: string
  source_quote?: string
  source_snippet_id?: string | null
  source_snippet_ids?: Array<Record<string, unknown>>
  source_snippet?: SourceSnippet | null
  knowledge_point?: string
  difficulty?: number
  grading_points?: string[]
  scoring_criteria?: Record<string, unknown>
  max_score?: number
}

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
  title: string
  status: PracticeStatus
  question_count: number
  total_count?: number | null
  completed_count?: number | null
  mode?: string | null
  total_score?: number | null
  max_score?: number | null
  source_type?: string
  created_at?: string | null
  submitted_at?: string | null
  completed_at?: string | null
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

export interface AnswerPayload {
  question_id: string
  answer: unknown
  time_spent_seconds?: number
}

export interface KnowledgeEvaluationItem {
  knowledge_point_id: string
  score: number
  delta: number
  status: string
  root_causes: string[]
  suggestions: string[]
}

export interface WeakKnowledgeItem {
  knowledge_point_id?: string | null
  knowledge_name?: string | null
  knowledge_id?: string | null
  knowledge_title?: string | null
  current_score: number
  previous_score?: number | null
  score_delta: number
  priority?: number | string | null
  cause_type?: string | null
  cause_explanation?: string | null
  actionable_advice?: string | null
  associated_mistakes?: Array<{ question_id: string; is_negation_inversion: boolean }>
}

export interface AnalysisCauseItem {
  knowledge_id: string
  cause_type: string
  explanation: string
}

export interface ActionableSuggestionItem {
  action: string
}

export interface DiagnosisReport {
  id: string
  practice_id: string
  mastery_before?: number | null
  mastery_after?: number | null
  knowledge_evaluations: KnowledgeEvaluationItem[]
  weak_knowledge_points: WeakKnowledgeItem[]
  regressed_knowledge_points: WeakKnowledgeItem[]
  analysis_causes: AnalysisCauseItem[]
  actionable_suggestions: ActionableSuggestionItem[]
  root_causes: string[]
  suggestions: string[]
  summary?: string | null
  unanswered_count: number
  wrong_count: number
  pending_regrade_count: number
  total_questions: number
  score_rate: number
  is_structure_degraded: boolean
  created_at?: string | null
}

export interface RegradeResponse {
  attempt_item_id: string
  status: string
  message: string
  grading_record_id?: string
  score?: number
  is_final: boolean
}

export interface SelfEvaluateResponse {
  grading_record_id: string
  id?: string
  attempt_item_id: string
  score: number
  is_final: boolean
  evaluated_at?: string
  feedback?: string
}

export interface AskCoachResponse {
  reply: string
  suggestions: string[]
  sources?: CoachSource[]
}

export interface CoachSource {
  snippet_id: string
  material_id: string
  chapter_title?: string | null
  excerpt: string
}

export interface WrongQuestionSnapshot {
  stem?: string
  question_type?: QuestionType
  options?: QuestionOption[]
  answer?: string | string[] | number | null
  analysis?: string
  difficulty?: number
  [key: string]: unknown
}

export interface WrongRecordItem {
  id: string
  folder_id?: string | null
  material_id?: string | null
  practice_id: string
  attempt_item_id: string
  question_id?: string | null
  knowledge_point_id: string
  error_type?: string
  is_mastered: boolean
  wrong_count?: number
  created_at?: string | null
  updated_at?: string | null
  user_answer?: string | null
  question_snapshot: WrongQuestionSnapshot
}

export interface WrongRecordGroup {
  folder_id: string | null
  folder_name: string | null
  material_id: string | null
  material_title: string | null
  count: number
}

export interface WrongRecordListResult {
  items: WrongRecordItem[]
  groups: WrongRecordGroup[]
  total: number
  page?: number
  page_size?: number
  offset: number
  limit: number
}
