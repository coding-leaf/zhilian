import type { QuestionItem } from '@/types'

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
