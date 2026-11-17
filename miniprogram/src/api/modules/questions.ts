import { request } from '@/utils/request'
import { LONG_REQUEST_TIMEOUT_MS } from '@/utils/requestError'
import type {
  AskCoachResponse,
  GenerateQuestionsParams,
  QuestionBankListResult,
  QuestionBankQuery,
  QuestionBatchListResult,
  QuestionBatchQuery,
  QuestionGenerateResult,
  QuestionItem,
  ScopedCoachParams,
} from '@/types'
import {
  adaptQuestion,
  adaptQuestionBankList,
  adaptQuestionBatchList,
  type WireQuestion,
  type WireQuestionBankList,
  type WireQuestionBatchList,
} from '../adapters'

export type {
  GenerateQuestionsParams,
  QuestionGenerateResult,
  QuestionBatchQuery,
  QuestionBankQuery,
  ScopedCoachParams,
}

export function apiGenerateQuestions(params: GenerateQuestionsParams): Promise<QuestionGenerateResult> {
  return request<Omit<QuestionGenerateResult, 'qualified_questions' | 'pending_questions'> & {
    qualified_questions: WireQuestion[]
    pending_questions: WireQuestion[]
  }>({
    url: '/questions/generate',
    method: 'POST',
    data: params,
    // 后端在请求路径内同步走大模型出题 + 质检重试，15 秒默认值不够。
    timeout: LONG_REQUEST_TIMEOUT_MS,
  }).then((result) => ({
    ...result,
    qualified_questions: (result.qualified_questions || []).map(adaptQuestion),
    pending_questions: (result.pending_questions || []).map(adaptQuestion),
  }))
}

export function apiGetQuestionsByMaterial(materialId: string): Promise<QuestionItem[]> {
  return request<{ items: WireQuestion[] } | WireQuestion[]>({
    url: `/questions?material_id=${materialId}`,
    method: 'GET',
  }).then((res) => {
    if (res && 'items' in res) return res.items.map(adaptQuestion)
    return ((res as WireQuestion[]) || []).map(adaptQuestion)
  })
}

/** 题库批次聚合（服务端 group by，一次请求渲染一页批次，不做前端拼装）。 */
export function apiListQuestionBatches(
  params: QuestionBatchQuery = {},
): Promise<QuestionBatchListResult> {
  const page = params.page ?? 1
  const pageSize = params.page_size ?? 20
  return request<WireQuestionBatchList>({
    url: `/questions/batches?page=${page}&page_size=${pageSize}`,
    method: 'GET',
  }).then(adaptQuestionBatchList)
}

/** 题库区块的题目列表（展开批次 / 解析整批题目 ID 共用）。 */
export function apiListQuestionBankItems(
  query: QuestionBankQuery = {},
): Promise<QuestionBankListResult> {
  const queryParts: string[] = []
  if (query.batchId) queryParts.push(`batch_id=${encodeURIComponent(query.batchId)}`)
  if (query.unbatched) queryParts.push('unbatched=true')
  if (query.reviewStatus) queryParts.push(`review_status=${query.reviewStatus}`)
  queryParts.push(`page=${query.page ?? 1}`)
  queryParts.push(`page_size=${query.page_size ?? 20}`)

  return request<WireQuestionBankList>({
    url: `/questions?${queryParts.join('&')}`,
    method: 'GET',
  }).then(adaptQuestionBankList)
}

export function apiAskQuestionCoach(
  questionId: string,
  userPrompt: string,
  userAnswer?: string,
  gradingPoints?: string[],
): Promise<AskCoachResponse> {
  return request<AskCoachResponse>({
    url: `/questions/${questionId}/ask-coach`,
    method: 'POST',
    data: {
      user_prompt: userPrompt,
      user_answer: userAnswer,
      grading_points: gradingPoints,
    },
    // 助教答疑同步等大模型生成回答。
    timeout: LONG_REQUEST_TIMEOUT_MS,
  })
}

export function apiAskScopedCoach(params: ScopedCoachParams): Promise<AskCoachResponse> {
  return request<AskCoachResponse>({
    url: '/coach/ask',
    method: 'POST',
    data: params,
    // 范围级助教同样同步等大模型。
    timeout: LONG_REQUEST_TIMEOUT_MS,
  })
}
