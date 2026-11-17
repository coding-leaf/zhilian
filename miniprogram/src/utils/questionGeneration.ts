import {
  apiCreatePractice,
  apiGenerateQuestions,
  computeKnowledgeCoverage,
  dedupeQuestions,
  planGenerationBatches,
  type CoverageResult,
} from '@/api'
import type { PracticeSession, QuestionItem, QuestionType } from '@/types'
import { clampPracticeQuestionIds, validateWrongRegenerateInput } from './practiceHelpers'

export interface BatchGenerateOptions {
  folderId?: string
  materialId?: string
  knowledgePointIds: string[]
  desiredCount: number
  questionTypes?: QuestionType[]
  difficulty?: number
}

export interface BatchGenerateOutput {
  questions: QuestionItem[]
  pending: number
  batchIds: string[]
}

/**
 * 共享多批次智能出题循环（受单批 MAX_QUESTION_BATCH=20 约束）。
 * 由智能组卷与错题再生题共同消费。
 */
export async function generateQuestionsInBatches(
  options: BatchGenerateOptions,
): Promise<BatchGenerateOutput> {
  const batches = planGenerationBatches(options.knowledgePointIds, options.desiredCount)
  const collected: QuestionItem[] = []
  const batchIds: string[] = []
  let pending = 0

  for (const batch of batches) {
    const result = await apiGenerateQuestions({
      folder_id: options.folderId,
      material_id: options.folderId ? undefined : options.materialId,
      knowledge_point_ids: batch.knowledgePointIds,
      question_types: options.questionTypes,
      count: batch.count,
      difficulty: options.difficulty ?? 3,
    })
    collected.push(...result.qualified_questions)
    if (result.batch_id) batchIds.push(result.batch_id)
    pending += result.pending_count
  }

  return {
    questions: dedupeQuestions(collected),
    pending,
    batchIds,
  }
}

export interface WrongRegenerateScope {
  folderId?: string
  materialId?: string
}

export interface WrongRegenerateOutput {
  session: PracticeSession
  coverage: CoverageResult
}

/** 基于单一课程或资料范围内的错题知识点再生练习。 */
export async function regenerateWrongPractice(
  knowledgePointIds: string[],
  scope: WrongRegenerateScope,
): Promise<WrongRegenerateOutput> {
  validateWrongRegenerateInput(knowledgePointIds, scope)

  const { questions: generated } = await generateQuestionsInBatches({
    folderId: scope.folderId,
    materialId: scope.materialId,
    knowledgePointIds,
    desiredCount: Math.max(3, knowledgePointIds.length),
    difficulty: 3,
  })
  if (generated.length === 0) {
    throw new Error('未生成可用题目，请稍后重试')
  }
  const coverage = computeKnowledgeCoverage(generated, knowledgePointIds)
  const questionIds = clampPracticeQuestionIds(generated.map((question) => question.id))

  const session = await apiCreatePractice({
    title: '错题巩固练习',
    folder_id: scope.folderId,
    material_id: scope.materialId,
    knowledge_point_ids: knowledgePointIds,
    question_ids: questionIds,
    question_count: questionIds.length,
    source_type: 'wrong_record',
  })

  return { session, coverage }
}
