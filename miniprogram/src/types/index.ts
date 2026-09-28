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

export type MaterialStatus = 'WAITING' | 'PROCESSING' | 'PARSED' | 'FAILED'

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

export type QuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'fill_in_blank'
  | 'term_explanation'
  | 'short_answer'
  | 'case_analysis'

export interface QuestionItem {
  id: string
  material_id?: string
  type: QuestionType
  stem: string
  options?: string[]
  answer: string | string[]
  explanation?: string
  source_quote?: string
  knowledge_point?: string
  knowledge_point_id?: string
  difficulty?: number
  grading_points?: string[]
  scoring_criteria?: Record<string, any>
  max_score?: number
}

export interface PracticeSession {
  id: string
  title: string
  status: 'IN_PROGRESS' | 'COMPLETED' | 'PAUSED'
  questions: QuestionItem[]
  total_count: number
  submitted_count: number
  user_answers?: Record<string, any>
  created_at: string
}

export interface AnswerPayload {
  question_id: string
  answer: any
  time_spent_seconds?: number
}

export interface DiagnosisWeakness {
  knowledge_point: string
  knowledge_point_id?: string
  mastery_rate: number
  reason: string
  suggestion: string
}

export interface QuestionGradingResult {
  question_id: string
  attempt_item_id?: string
  type: QuestionType
  stem: string
  user_answer: any
  correct_answer: any
  is_correct: boolean
  score: number
  max_score: number
  feedback?: string
  key_points_hit?: string[]
  key_points_missed?: string[]
  source_quote?: string
  knowledge_point?: string
  knowledge_point_id?: string
}

export interface DiagnosisReport {
  id: string
  practice_id: string
  score: number
  total_score: number
  accuracy: number
  created_at: string
  weaknesses: DiagnosisWeakness[]
  details: QuestionGradingResult[]
  next_step_suggestion?: string
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
  question_id: string
  coach_reply: string
  next_thought_prompt?: string
}

export interface WrongRecordItem {
  id: string
  practice_id: string
  question_id: string
  knowledge_point_id?: string
  knowledge_point_name?: string
  error_type?: string
  is_mastered: boolean
  created_at: string
  question?: QuestionItem
}

export interface WrongRecordListResult {
  items: WrongRecordItem[]
  total: number
  page: number
  page_size: number
}
