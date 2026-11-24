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
  status?: string | null
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
  knowledge_point_name?: string | null
  difficulty?: number
  grading_points?: string[]
  scoring_criteria?: Record<string, unknown>
  max_score?: number
}

export type QuestionJobSourceType = 'initial_compose' | 'wrong_record' | 'weakness'

export interface PollingRequestOptions {
  silentToast?: boolean
}

export interface GenerateQuestionsParams {
  material_id?: string
  folder_id?: string
  knowledge_point_id?: string
  knowledge_point_ids?: string[]
  count?: number
  difficulty?: number
  question_types?: QuestionType[]
  max_retries?: number
  auto_create_practice?: boolean
  practice_title?: string
  source_type?: QuestionJobSourceType
  source_practice_id?: string
}

export interface QuestionGenerateResult {
  batch_id: string
  total_generated: number
  qualified_count: number
  pending_count: number
  qualified_questions: QuestionItem[]
  pending_questions: QuestionItem[]
}

export interface QuestionBatchQuery {
  page?: number
  page_size?: number
}

export interface QuestionBankQuery {
  /** 批次标识；缺省时不按批次过滤。未分批分组请传 `unbatched: true`。 */
  batchId?: string | null
  /** 只看 `batch_id IS NULL` 的历史题目（后端 batch_id 过滤无法表达 IS NULL）。 */
  unbatched?: boolean
  reviewStatus?: 'available' | 'pending_review'
  page?: number
  page_size?: number
}

export interface AskCoachHistoryItem {
  role: 'user' | 'assistant'
  content: string
}

export interface AskCoachParams {
  user_prompt: string
  user_answer?: string
  grading_points?: string[]
  /** 多轮对话线程 ID（前端传 sessionKey）；与 backend AskCoachRequest.thread_id 对齐，可选。 */
  thread_id?: string
  /** 近期历史对话（仅作服务端冷启动兜底）；与 backend AskCoachRequest.history 对齐，可选。 */
  history?: AskCoachHistoryItem[]
}

export interface ScopedCoachParams {
  folder_id?: string
  material_id?: string
  knowledge_point_id?: string
  user_prompt: string
  /** 多轮对话线程 ID（前端传 sessionKey）；与 backend ScopedCoachRequest.thread_id 对齐，可选。 */
  thread_id?: string
}

// 题库批次：与 backend/app/schemas/question.py::QuestionBatchSummaryResponse 一致
export interface BatchSource {
  materialId: string
  /** 资料行已缺失时为 null，界面渲染「来源已删除」而不丢整条批次 */
  materialTitle: string | null
  folderId: string | null
  folderName: string | null
}

export interface QuestionBatchSummary {
  /** null = 未分批的历史题目（batch_id IS NULL），不得伪造 ID */
  batchId: string | null
  questionCount: number
  availableCount: number
  pendingReviewCount: number
  createdAt: string
  sources: BatchSource[]
}

export interface QuestionBatchListResult {
  items: QuestionBatchSummary[]
  total: number
  limit: number
  offset: number
}

/** 题库区块展开后的单题投影：只保留勾选与展示所需字段。 */
export interface QuestionBankItem {
  id: string
  stem: string
  type: QuestionType
  /** 仅 available 题目可选；未知状态一律按不可选处理，不夸大已选题数 */
  selectable: boolean
  batchId: string | null
}

export interface QuestionBankListResult {
  items: QuestionBankItem[]
  total: number
}

export type QuestionGenerationJobStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface QuestionGenerationJob {
  id: string
  status: QuestionGenerationJobStatus
  material_id?: string | null
  folder_id?: string | null
  total_kps: number
  completed_kps: number
  generated_count: number
  batch_id?: string | null
  question_ids: string[]
  result_practice_id?: string | null
  source_type?: string | null
  source_practice_id?: string | null
  practice_title?: string | null
  error_message?: string | null
  created_at: string
  updated_at: string
  completed_at?: string | null
  timedOut?: boolean
}

export interface QuestionGenerationJobQuery {
  active_only?: boolean
  material_id?: string
  folder_id?: string
}

export interface QuestionGenerationJobListResult {
  items: QuestionGenerationJob[]
  total: number
}
