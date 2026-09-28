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
}

export interface LoginResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in?: number
  user?: UserProfile
}

export type MaterialStatus = 'WAITING' | 'PROCESSING' | 'PARSED' | 'FAILED'

export interface MaterialItem {
  id: string
  title: string
  status: MaterialStatus
  created_at: string
  updated_at?: string
  error_message?: string
  page_count?: number
  file_size?: number
  folder_id?: string | null
}

export type QuestionType = 'single_choice' | 'multiple_choice' | 'true_false' | 'short_answer'

export interface QuestionItem {
  id: string
  material_id: string
  type: QuestionType
  stem: string
  options?: string[]
  answer: string | string[]
  explanation?: string
  source_quote?: string
  knowledge_point?: string
  difficulty?: number
}

export interface PracticeSession {
  id: string
  title: string
  status: 'IN_PROGRESS' | 'COMPLETED'
  questions: QuestionItem[]
  total_count: number
  submitted_count: number
  user_answers?: Record<string, any>
  created_at: string
}

export interface AnswerPayload {
  question_id: string
  answer: any
}

export interface DiagnosisWeakness {
  knowledge_point: string
  mastery_rate: number
  reason: string
  suggestion: string
}

export interface QuestionGradingResult {
  question_id: string
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
