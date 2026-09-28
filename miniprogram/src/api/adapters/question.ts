import type { QuestionItem, QuestionOption, QuestionType, SourceSnippet } from '@/types'
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
  batch_id?: string | null
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

export function adaptQuestion(question: WireQuestion): QuestionItem {
  const options: QuestionOption[] = (question.options || []).map((option) => ({
    key: option.key,
    content: option.content,
  }))
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

  return {
    ...question,
    id: question.id || '',
    type: question.question_type,
    options,
    explanation: question.explanation ?? question.analysis,
    analysis: question.analysis,
    grading_points: gradingPoints,
    scoring_criteria: question.grading_rubric,
    max_score: question.max_score ?? rubricTotal,
    source_quote: question.source_snippet?.snippet_content,
  }
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

/** 选项展示文本（核对页与练习页共用，避免页面自行猜测字段）。 */
export function optionDisplayText(option: QuestionOption, index: number): string {
  const key = option.key || String.fromCharCode(65 + index)
  return `${key}. ${option.content}`
}

export const MAX_QUESTION_BATCH = 20

export interface GenerationBatch {
  knowledgePointIds: string[]
  count: number
}

/**
 * 按后端单次 count ∈ [1, 20] 的限制，把「覆盖全部已选考点、尽量满足指定题量」拆成若干批。
 * 目标题量：max(已选考点数, 用户指定题量)。
 */
export function planGenerationBatches(
  knowledgePointIds: string[],
  desiredCount: number,
): GenerationBatch[] {
  const unique = Array.from(new Set(knowledgePointIds.filter(Boolean)))
  if (unique.length === 0) return []
  const chunkSize = MAX_QUESTION_BATCH
  const chunks: string[][] = []
  for (let i = 0; i < unique.length; i += chunkSize) {
    chunks.push(unique.slice(i, i + chunkSize))
  }
  const target = Math.max(unique.length, desiredCount)
  const batches: GenerationBatch[] = []
  let remaining = Math.min(target, chunks.length * MAX_QUESTION_BATCH)
  for (let i = 0; i < chunks.length; i += 1) {
    const chunk = chunks[i]
    const share = Math.ceil(remaining / (chunks.length - i))
    const count = Math.min(MAX_QUESTION_BATCH, Math.max(chunk.length, share))
    remaining = Math.max(0, remaining - count)
    batches.push({ knowledgePointIds: chunk, count })
  }
  return batches
}

export interface CoverageResult {
  covered: string[]
  missing: string[]
  ratio: number
}

/** 按「题目快照携带的考点」核算实际覆盖，不把生成目标当成覆盖成功。 */
export function computeKnowledgeCoverage(
  questions: Array<Pick<QuestionItem, 'knowledge_point_id'>>,
  selectedKnowledgePointIds: string[],
): CoverageResult {
  const selected = Array.from(new Set(selectedKnowledgePointIds.filter(Boolean)))
  const coveredSet = new Set<string>()
  for (const question of questions) {
    const id = question.knowledge_point_id
    if (id && selected.includes(id)) coveredSet.add(id)
  }
  const covered = selected.filter((id) => coveredSet.has(id))
  const missing = selected.filter((id) => !coveredSet.has(id))
  const ratio = selected.length === 0 ? 1 : covered.length / selected.length
  return { covered, missing, ratio }
}

export function dedupeQuestions(questions: QuestionItem[]): QuestionItem[] {
  const seen = new Set<string>()
  const result: QuestionItem[] = []
  for (const question of questions) {
    if (!question.id || seen.has(question.id)) continue
    seen.add(question.id)
    result.push(question)
  }
  return result
}
