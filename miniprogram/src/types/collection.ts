import type { QuestionOption, QuestionType } from './question'

export interface QuestionCollection {
  id: string
  name: string
  description: string
  folder_id: string | null
  folder_name: string | null
  color_token: string | null
  is_pinned: boolean
  sort_order: number
  question_count: number
  created_at: string
  updated_at: string
}

export interface QuestionCollectionListResult {
  items: QuestionCollection[]
  total: number
}

export interface CreateCollectionParams {
  name: string
  description?: string
  folder_id?: string | null
  color_token?: string | null
  is_pinned?: boolean
}

export interface UpdateCollectionParams {
  name?: string
  description?: string
  folder_id?: string | null
  clear_folder?: boolean
  color_token?: string | null
  is_pinned?: boolean
}

export interface CollectionQuestionItem {
  id: string
  collection_id: string
  question_id: string
  question_type: QuestionType
  difficulty: number
  content: string
  options: QuestionOption[]
  answer: string | string[] | number | null
  explanation: string
  kp_id: string | null
  kp_name: string | null
  material_id: string | null
  material_title: string | null
  note: string | null
  added_at: string
}

export interface CollectionQuestionListResult {
  items: CollectionQuestionItem[]
  total: number
  page: number
  page_size: number
}

export interface AddCollectionItemsResult {
  added_count: number
  skipped_count: number
  total_count: number
}

export interface QuestionCollectionMembership {
  question_id: string
  collection_ids: string[]
}

export interface SyncQuestionCollectionsResult {
  question_id: string
  collection_ids: string[]
  added_count: number
  removed_count: number
}

export interface GroupedKnowledgePointCount {
  kpId: string | null
  kpName: string
  questionCount: number
}

export interface GroupedMaterialSummary {
  materialId: string
  materialTitle: string
  folderId: string | null
  folderName: string | null
  questionCount: number
  knowledgePoints: GroupedKnowledgePointCount[]
}

export interface QuestionGroupedSummaryResult {
  totalQuestions: number
  materials: GroupedMaterialSummary[]
}
