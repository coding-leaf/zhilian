import type { QuestionOption, QuestionType } from './question'

export interface WrongQuestionSnapshot {
  stem?: string
  question_type?: QuestionType
  knowledge_point_name?: string | null
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
  material_title?: string | null
  /** NULL = 手工标记（题库「记入错题」），无练习归属；非空 = 判题写入的真实来源。 */
  practice_id: string | null
  attempt_item_id: string | null
  question_id?: string | null
  knowledge_point_id: string
  knowledge_point_name?: string | null
  error_type?: string
  is_mastered: boolean
  wrong_count?: number
  created_at?: string | null
  updated_at?: string | null
  user_answer?: string | null
  question_snapshot: WrongQuestionSnapshot
}

/** DELETE /wrong-records/{id} 的响应形状。 */
export interface DeleteWrongRecordResult {
  id: string
  success: boolean
  removed: boolean
  message: string
}

/** POST /wrong-records/{id}/master 的响应形状。 */
export interface MarkWrongRecordMasteredResult {
  id: string
  is_mastered: boolean
  mastered_at?: string | null
  message: string
}

export interface WrongRecordGroup {
  folder_id: string | null
  folder_name: string | null
  material_id: string | null
  material_title: string | null
  count: number
}

export interface WrongRecordListQuery {
  folder_id?: string
  unclassified?: boolean
  material_id?: string
  knowledge_point_id?: string
  is_mastered?: boolean
  page?: number
  page_size?: number
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
