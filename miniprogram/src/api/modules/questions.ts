import { request } from '@/utils/request'
import { LONG_REQUEST_TIMEOUT_MS } from '@/utils/requestError'
import type {
  AskCoachHistoryItem,
  AskCoachParams,
  AskCoachResponse,
  GenerateQuestionsParams,
  PollingRequestOptions,
  QuestionBankListResult,
  QuestionBankQuery,
  QuestionBatchListResult,
  QuestionBatchQuery,
  QuestionGenerateResult,
  QuestionGenerationJob,
  QuestionGenerationJobListResult,
  QuestionGenerationJobQuery,
  QuestionItem,
  ScopedCoachParams,
} from '@/types'
import {
  adaptQuestion,
  adaptQuestionBankList,
  adaptQuestionBatchList,
  adaptQuestionGenerationJob,
  adaptQuestionGenerationJobList,
  type WireQuestion,
  type WireQuestionBankList,
  type WireQuestionBatchList,
  type WireQuestionGenerationJob,
} from '../adapters'

export type {
  AskCoachHistoryItem,
  AskCoachParams,
  GenerateQuestionsParams,
  QuestionGenerateResult,
  QuestionBatchQuery,
  QuestionBankQuery,
  QuestionGenerationJob,
  QuestionGenerationJobQuery,
  QuestionGenerationJobListResult,
  ScopedCoachParams,
}

/** @deprecated 请改用 `apiCreateQuestionJob` 异步出题任务。 */
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

export function apiCreateQuestionJob(
  params: GenerateQuestionsParams,
): Promise<QuestionGenerationJob> {
  return request<WireQuestionGenerationJob>({
    url: '/questions/jobs',
    method: 'POST',
    data: params,
  }).then(adaptQuestionGenerationJob)
}

export function apiListQuestionJobs(
  query: QuestionGenerationJobQuery = {},
  requestOptions?: PollingRequestOptions,
): Promise<QuestionGenerationJobListResult> {
  const queryParts: string[] = []
  if (query.active_only !== undefined) queryParts.push(`active_only=${query.active_only}`)
  if (query.material_id) queryParts.push(`material_id=${encodeURIComponent(query.material_id)}`)
  if (query.folder_id) queryParts.push(`folder_id=${encodeURIComponent(query.folder_id)}`)
  const qs = queryParts.length ? `?${queryParts.join('&')}` : ''
  return request<{ items?: WireQuestionGenerationJob[] | null; total?: number | null } | WireQuestionGenerationJob[]>({
    url: `/questions/jobs${qs}`,
    method: 'GET',
    ...(requestOptions?.silentToast !== undefined ? { silentToast: requestOptions.silentToast } : {}),
  }).then(adaptQuestionGenerationJobList)
}

export function apiGetQuestionJob(
  jobId: string,
  requestOptions?: PollingRequestOptions,
): Promise<QuestionGenerationJob> {
  return request<WireQuestionGenerationJob>({
    url: `/questions/jobs/${jobId}`,
    method: 'GET',
    ...(requestOptions?.silentToast !== undefined ? { silentToast: requestOptions.silentToast } : {}),
  }).then(adaptQuestionGenerationJob)
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

export interface AskQuestionCoachOptions {
  threadId?: string
  history?: AskCoachHistoryItem[]
}

export function apiAskQuestionCoach(
  questionId: string,
  userPrompt: string,
  userAnswer?: string,
  gradingPoints?: string[],
  options?: AskQuestionCoachOptions,
): Promise<AskCoachResponse> {
  const payload: AskCoachParams = {
    user_prompt: userPrompt,
    user_answer: userAnswer,
    grading_points: gradingPoints,
  }
  if (options?.threadId) {
    payload.thread_id = options.threadId
  }
  if (options?.history && options.history.length > 0) {
    payload.history = options.history
  }

  return request<AskCoachResponse>({
    url: `/questions/${questionId}/ask-coach`,
    method: 'POST',
    data: payload,
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
