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

export type KnowledgeMasteryLevel = 'unlearned' | 'weak' | 'basic' | 'proficient'

export interface KnowledgeMasterySummary {
  knowledge_point_id: string
  knowledge_name: string
  mastery_score: number
  level: KnowledgeMasteryLevel
  practice_count: number
  correct_count: number
  last_practiced_at?: string | null
}

export interface UserMasteryOverview {
  material_id?: string | null
  total_points: number
  total_knowledge_points: number
  mastered_count: number
  proficient_count: number
  learning_count: number
  basic_count: number
  weak_count: number
  unlearned_count: number
  overall_score: number
  overall_mastery_score: number
  points: KnowledgeMasterySummary[]
  weak_knowledge_points: KnowledgeMasterySummary[]
  weak_points: KnowledgeMasterySummary[]
}
