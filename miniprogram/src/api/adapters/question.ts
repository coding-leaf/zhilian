import type {
  BatchSource,
  QuestionBankItem,
  QuestionBankListResult,
  QuestionBatchListResult,
  QuestionBatchSummary,
  QuestionGenerationJob,
  QuestionGenerationJobListResult,
  QuestionGenerationJobStatus,
  QuestionItem,
  QuestionOption,
  QuestionType,
  SourceSnippet,
} from '@/types'
import { SUBJECTIVE_QUESTION_TYPES } from '@/types'

/**
 * 后端 QuestionDetailResponse 的 wire 形状。
 * 事实源：backend/app/schemas/question.py::QuestionDetailResponse
 * 全部消费方必须经 adaptQuestion 归一化，禁止在页面/Store 自行断言字段。
 */
export interface WireQuestion {
  id?: string | null
  material_id?: string
  version_id?: string
  knowledge_point_id?: string
  knowledge_point?: string
  knowledge_point_name?: string | null
  batch_id?: string | null
  /** 后端 QuestionStatus：available 可选 / pending_review 待处理区 */
  status?: string | null
  question_type: QuestionType
  stem: string
  options?: Array<{ key: string; content: string }>
  answer?: string | string[] | number | null
  analysis?: string
  explanation?: string
  difficulty?: number
  grading_rubric?: Record<string, unknown>
  max_score?: number
  source_snippet_id?: string | null
  source_snippet_ids?: Array<Record<string, unknown>>
  source_snippet?: SourceSnippet | null
}

function normalizeQuestionOption(option: { key?: string; content?: string }, index: number): QuestionOption {
  const cleanKey = String(option.key ?? '')
    .trim()
    .replace(/[.。:：、)）]+$/, '')
  const key = cleanKey || String.fromCharCode(65 + index)
  const rawContent = String(option.content ?? '').trim()
  const content = rawContent.replace(/^(?:(?:[(（][A-Z][)）]|[A-Z][.。、:：)）])\s*)+/i, '')
  return { key, content }
}

export function adaptQuestion(question: WireQuestion): QuestionItem {
  const options: QuestionOption[] = (question.options || []).map(normalizeQuestionOption)
  const rubric = question.grading_rubric
  const rubricPoints = rubric?.points ?? rubric?.key_points
  const gradingPoints = Array.isArray(rubricPoints)
    ? rubricPoints.flatMap((point: unknown) => {
      if (typeof point === 'string') return [point]
      if (point && typeof point === 'object' && 'point' in point) {
        const value = (point as { point?: unknown }).point
        return typeof value === 'string' ? [value] : []
      }
      return []
    })
    : []
  const rubricTotal = typeof rubric?.total_score === 'number' ? rubric.total_score : undefined
  const kpName = question.knowledge_point_name ?? question.knowledge_point ?? null

  return {
    ...question,
    id: question.id || '',
    type: question.question_type,
    options,
    explanation: question.explanation ?? question.analysis,
    analysis: question.analysis,
    knowledge_point_name: kpName,
    knowledge_point: question.knowledge_point ?? kpName ?? undefined,
    grading_points: gradingPoints,
    scoring_criteria: question.grading_rubric,
    max_score: question.max_score ?? rubricTotal,
    source_quote: question.source_snippet?.snippet_content,
  }
}

/**
 * 后端 QuestionBatchSummaryResponse / QuestionBatchListResponse 的 wire 形状。
 * 事实源：backend/app/schemas/question.py
 */
export interface WireQuestionBatchSource {
  material_id?: string | null
  material_title?: string | null
  folder_id?: string | null
  folder_name?: string | null
}

export interface WireQuestionBatchSummary {
  batch_id?: string | null
  question_count?: number | null
  available_count?: number | null
  pending_review_count?: number | null
  created_at?: string | null
  sources?: WireQuestionBatchSource[] | null
}

export interface WireQuestionBatchList {
  items?: WireQuestionBatchSummary[] | null
  total?: number | null
  limit?: number | null
  offset?: number | null
}

function adaptBatchSource(source: WireQuestionBatchSource): BatchSource {
  return {
    materialId: source.material_id || '',
    materialTitle: source.material_title ?? null,
    folderId: source.folder_id ?? null,
    folderName: source.folder_name ?? null,
  }
}

/** 批次摘要归一化：计数字段一律取整，缺失按 0；批次标识为 null 是合法语义。 */
export function adaptQuestionBatch(batch: WireQuestionBatchSummary): QuestionBatchSummary {
  const availableCount = Math.max(0, batch.available_count ?? 0)
  const pendingReviewCount = Math.max(0, batch.pending_review_count ?? 0)
  return {
    batchId: batch.batch_id ?? null,
    questionCount: batch.question_count ?? availableCount + pendingReviewCount,
    availableCount,
    pendingReviewCount,
    createdAt: batch.created_at ?? '',
    sources: (batch.sources ?? []).map(adaptBatchSource),
  }
}

export function adaptQuestionBatchList(result: WireQuestionBatchList | null): QuestionBatchListResult {
  const items = (result?.items ?? []).map(adaptQuestionBatch)
  return {
    items,
    total: result?.total ?? items.length,
    limit: result?.limit ?? items.length,
    offset: result?.offset ?? 0,
  }
}

/**
 * 题库区块的单题投影。
 *
 * `selectable` 只认 `status === 'available'`：未知状态一律按不可选处理，
 * 宁可让用户看到「这题不能选」，也不要让界面的已选题数高于实际进入练习的题数。
 */
export function adaptQuestionBankItem(question: WireQuestion): QuestionBankItem {
  return {
    id: question.id || '',
    stem: question.stem,
    type: question.question_type,
    selectable: question.status === 'available',
    batchId: question.batch_id ?? null,
  }
}

export interface WireQuestionBankList {
  items?: WireQuestion[] | null
  total?: number | null
}

export function adaptQuestionBankList(result: WireQuestionBankList): QuestionBankListResult {
  const items = (result?.items ?? []).map(adaptQuestionBankItem)
  return { items, total: result?.total ?? items.length }
}

/** 题型中文标签；未知题型回退为通用文案，不伪造具体题型。 */
export function questionTypeLabel(type: QuestionType | string | undefined): string {
  switch (type) {
    case 'single_choice': return '单选题'
    case 'multiple_choice': return '多选题'
    case 'true_false': return '判断题'
    case 'fill_in_blank': return '填空题'
    case 'term_explanation': return '名词解释'
    case 'short_answer': return '简答题'
    case 'case_analysis': return '案例分析'
    default: return '试题'
  }
}

/** 主观题判定：与 backend QuestionType 注释标注的三类主观题一致。 */
export function isSubjectiveType(type: QuestionType | string | undefined): boolean {
  return SUBJECTIVE_QUESTION_TYPES.includes(type as QuestionType)
}

/** 选项键归一化（核对页与练习页共用）。 */
export function optionKey(option: QuestionOption, index: number): string {
  return option.key || String.fromCharCode(65 + index)
}

/** 选项展示文本（核对页与练习页共用，避免页面自行猜测字段）。 */
export function optionDisplayText(option: QuestionOption, index: number): string {
  return `${optionKey(option, index)}. ${option.content}`
}

export interface WireQuestionGenerationJob {
  id: string
  status?: string | null
  material_id?: string | null
  folder_id?: string | null
  total_kps?: number | null
  completed_kps?: number | null
  generated_count?: number | null
  batch_id?: string | null
  question_ids?: unknown[] | null
  result_practice_id?: string | null
  source_type?: string | null
  source_practice_id?: string | null
  practice_title?: string | null
  error_message?: string | null
  created_at?: string | null
  updated_at?: string | null
  completed_at?: string | null
}

const JOB_STATUSES: QuestionGenerationJobStatus[] = ['queued', 'running', 'completed', 'failed']

export function adaptQuestionGenerationJob(job: WireQuestionGenerationJob): QuestionGenerationJob {
  const rawStatus = String(job.status ?? '').toLowerCase()
  const status = (JOB_STATUSES as string[]).includes(rawStatus)
    ? (rawStatus as QuestionGenerationJobStatus)
    : 'queued'
  const questionIds = Array.isArray(job.question_ids)
    ? job.question_ids.map((id) => String(id)).filter(Boolean)
    : []
  return {
    id: job.id,
    status,
    material_id: job.material_id ?? null,
    folder_id: job.folder_id ?? null,
    total_kps: Math.max(0, job.total_kps ?? 0),
    completed_kps: Math.max(0, job.completed_kps ?? 0),
    generated_count: Math.max(0, job.generated_count ?? 0),
    batch_id: job.batch_id ?? null,
    question_ids: questionIds,
    result_practice_id: job.result_practice_id ?? null,
    source_type: job.source_type ?? null,
    source_practice_id: job.source_practice_id ?? null,
    practice_title: job.practice_title ?? null,
    error_message: job.error_message ?? null,
    created_at: job.created_at ?? '',
    updated_at: job.updated_at ?? '',
    completed_at: job.completed_at ?? null,
  }
}

export function adaptQuestionGenerationJobList(
  res: { items?: WireQuestionGenerationJob[] | null; total?: number | null } | WireQuestionGenerationJob[] | null,
): QuestionGenerationJobListResult {
  if (Array.isArray(res)) {
    const items = res.map(adaptQuestionGenerationJob)
    return { items, total: items.length }
  }
  const items = (res?.items ?? []).map(adaptQuestionGenerationJob)
  return { items, total: res?.total ?? items.length }
}

export {
  MAX_QUESTION_BATCH,
  computeKnowledgeCoverage,
  dedupeQuestions,
  planGenerationBatches,
  type CoverageResult,
  type GenerationBatch,
} from './questionPlanning'
