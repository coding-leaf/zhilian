import { request, uploadFile } from '@/utils/request'
import { LONG_REQUEST_TIMEOUT_MS } from '@/utils/requestError'
import type {
  LoginResult,
  UserProfile,
  UpdateUserProfilePayload,
  FolderItem,
  FolderListResult,
  FolderKnowledgePointsResult,
  MaterialItem,
  MaterialListResult,
  KnowledgeTreeResult,
  KnowledgePointDetail,
  PointSourceListResult,
  QuestionItem,
  PracticeSession,
  PracticeListResult,
  PracticeSummary,
  DiagnosisReport,
  RegradeResponse,
  SelfEvaluateResponse,
  AskCoachResponse,
  WrongRecordListResult,
  QuestionType,
  AttemptResult,
} from '@/types'
import {
  adaptDiagnosisReport,
  adaptMaterial,
  adaptPractice,
  adaptQuestion,
  buildAttemptResults,
  type WireDiagnosisReport,
  type WirePracticeDetail,
  type WireQuestion,
} from './adapters'

export {
  adaptDiagnosisReport,
  adaptMaterial,
  adaptPractice,
  adaptQuestion,
  buildAttemptResults,
  computeKnowledgeCoverage,
  dedupeQuestions,
  isSubjectiveType,
  needsGradingRetry,
  planGenerationBatches,
  questionTypeLabel,
  MAX_QUESTION_BATCH,
} from './adapters'
export type { AttemptResult } from '@/types'
export type { CoverageResult, GenerationBatch } from './adapters'

// 1. 认证与用户 API
export function apiLoginByWechat(code: string): Promise<LoginResult> {
  return request<LoginResult>({
    url: '/auth/login',
    method: 'POST',
    data: { code },
  })
}

export function apiGetUserProfile(): Promise<UserProfile> {
  return request<UserProfile>({
    url: '/users/me',
    method: 'GET',
  })
}

export function apiUpdateUserProfile(payload: UpdateUserProfilePayload): Promise<UserProfile> {
  return request<UserProfile>({
    url: '/users/me',
    method: 'PUT',
    data: payload,
  })
}

// 2. 课程文件夹 API
export function apiListFolders(includeArchived = false): Promise<FolderListResult> {
  return request<FolderListResult>({
    url: `/folders?include_archived=${includeArchived}`,
    method: 'GET',
  })
}

export function apiCreateFolder(name: string): Promise<FolderItem> {
  return request<FolderItem>({
    url: '/folders',
    method: 'POST',
    data: { name },
  })
}

export function apiRenameFolder(folderId: string, name: string): Promise<FolderItem> {
  return request<FolderItem>({
    url: `/folders/${folderId}`,
    method: 'PATCH',
    data: { name },
  })
}

export function apiArchiveFolder(folderId: string): Promise<{ id: string; is_deleted: boolean }> {
  return request({
    url: `/folders/${folderId}`,
    method: 'DELETE',
  })
}

export function apiGetFolderKnowledgePoints(folderId: string): Promise<FolderKnowledgePointsResult> {
  return request<FolderKnowledgePointsResult>({
    url: `/folders/${folderId}/knowledge-points`,
    method: 'GET',
  })
}

// 3. 资料 API
export function apiUploadMaterial(
  filePath: string,
  title?: string,
  folderId?: string,
): Promise<MaterialItem> {
  const formData: Record<string, string> = {}
  if (title) formData.title = title
  if (folderId) formData.folder_id = folderId
  return uploadFile<MaterialItem>(filePath, 'file', formData).then(adaptMaterial)
}

export function apiGetMaterialDetail(id: string): Promise<MaterialItem> {
  return request<MaterialItem>({
    url: `/materials/${id}`,
    method: 'GET',
  }).then(adaptMaterial)
}

export function apiGetMaterialList(params?: { folder_id?: string; status?: string }): Promise<MaterialItem[]> {
  let url = '/materials'
  const queryParts: string[] = []
  if (params?.folder_id) queryParts.push(`folder_id=${encodeURIComponent(params.folder_id)}`)
  if (params?.status) queryParts.push(`status=${encodeURIComponent(params.status)}`)
  if (queryParts.length > 0) url += `?${queryParts.join('&')}`

  return request<MaterialListResult | MaterialItem[]>({
    url,
    method: 'GET',
  }).then((res) => {
    if (res && 'items' in res) {
      return res.items.map(adaptMaterial)
    }
    return ((res as MaterialItem[]) || []).map(adaptMaterial)
  })
}

export function apiTriggerMaterialParse(materialId: string): Promise<{ message: string }> {
  return request({
    url: `/materials/${materialId}/parse`,
    method: 'POST',
  })
}

// 4. 知识点与知识树 API
export function apiGetKnowledgeTree(materialId: string, versionId?: string): Promise<KnowledgeTreeResult> {
  let url = `/materials/${materialId}/knowledge-tree`
  if (versionId) url += `?version_id=${encodeURIComponent(versionId)}`
  return request<KnowledgeTreeResult>({
    url,
    method: 'GET',
  })
}

export function apiGetKnowledgePointDetail(id: string): Promise<KnowledgePointDetail> {
  return request<KnowledgePointDetail>({
    url: `/knowledge/${id}`,
    method: 'GET',
  })
}

export function apiGetKnowledgePointSnippets(id: string): Promise<PointSourceListResult> {
  return request<PointSourceListResult>({
    url: `/knowledge/${id}/snippets`,
    method: 'GET',
  })
}

// 5. 题目与智能出题 API
export interface GenerateQuestionsParams {
  material_id?: string
  folder_id?: string
  knowledge_point_id?: string
  knowledge_point_ids?: string[]
  count?: number
  difficulty?: number
  question_types?: QuestionType[]
  max_retries?: number
}

export interface QuestionGenerateResult {
  batch_id: string
  total_generated: number
  qualified_count: number
  pending_count: number
  qualified_questions: QuestionItem[]
  pending_questions: QuestionItem[]
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

export interface ScopedCoachParams {
  folder_id?: string
  material_id?: string
  knowledge_point_id?: string
  user_prompt: string
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

// 6. 练习作答与交卷 API
export interface CreatePracticeParams {
  title?: string
  material_id?: string
  folder_id?: string
  knowledge_point_ids?: string[]
  question_ids?: string[]
  question_count?: number
  question_types?: QuestionType[]
  difficulty?: number
  mode?: string
  source_type?: string
  source_report_id?: string
}

export function apiCreatePractice(params: CreatePracticeParams | string, questionIds?: string[]): Promise<PracticeSession> {
  const payload: CreatePracticeParams = typeof params === 'string'
    ? { material_id: params, question_ids: questionIds }
    : params
  return request<{ id: string }>({
    url: '/practices',
    method: 'POST',
    data: payload,
  }).then((created) => apiGetPracticeSession(created.id))
}

export function apiGetPracticeSession(practiceId: string): Promise<PracticeSession> {
  return request<WirePracticeDetail>({
    url: `/practices/${practiceId}`,
    method: 'GET',
  }).then(adaptPractice)
}

export function apiListPractices(params?: {
  status?: string
  material_id?: string
  offset?: number
  limit?: number
}): Promise<PracticeListResult> {
  const queryParts: string[] = []
  if (params?.status) queryParts.push(`status=${encodeURIComponent(params.status)}`)
  if (params?.material_id) queryParts.push(`material_id=${encodeURIComponent(params.material_id)}`)
  if (params?.offset !== undefined) queryParts.push(`offset=${params.offset}`)
  if (params?.limit !== undefined) queryParts.push(`limit=${params.limit}`)
  const qs = queryParts.length ? `?${queryParts.join('&')}` : ''
  return request<PracticeListResult>({ url: `/practices${qs}`, method: 'GET' })
}

export type { PracticeSummary }

export function apiSavePracticeDraft(
  practiceId: string,
  questionId: string,
  userAnswer: unknown,
  timeSpentSeconds = 0,
): Promise<{ success: boolean }> {
  return request({
    url: `/practices/${practiceId}/answers`,
    method: 'PUT',
    data: {
      question_id: questionId,
      user_answer: userAnswer,
      time_spent_seconds: timeSpentSeconds,
    },
  })
}

export function apiSubmitPractice(
  practiceId: string,
  confirmUnanswered = true,
  idempotencyKey = practiceId,
): Promise<{ practice_id: string; status: string; task_id?: string }> {
  return request({
    url: `/practices/${practiceId}/submit`,
    method: 'POST',
    header: {
      'Idempotency-Key': idempotencyKey,
    },
    data: {
      confirm_unanswered: confirmUnanswered,
    },
  })
}

/**
 * 主动重试未完成的整卷判题。
 * 后端仅在练习处于 `partially_graded`（待重判/判题任务终态失败）时受理，
 * 重复触发会被状态锁拒绝，不会重复派发判题任务。
 */
export function apiRetryPracticeGrading(
  practiceId: string,
): Promise<{ practice_id: string; status: string; message: string }> {
  return request({
    url: `/practices/${practiceId}/regrade`,
    method: 'POST',
  })
}

// 7. 判题与复查 API
export function apiSelfEvaluate(
  attemptItemId: string,
  score: number,
  feedback?: string,
  isCorrect?: boolean,
): Promise<SelfEvaluateResponse> {
  return request<SelfEvaluateResponse>({
    url: '/grading/self-evaluate',
    method: 'POST',
    data: {
      attempt_item_id: attemptItemId,
      score,
      feedback,
      is_correct: isCorrect,
    },
  })
}

export function apiRegradeAttempt(attemptItemId: string, reason: string): Promise<RegradeResponse> {
  return request<RegradeResponse>({
    url: '/grading/regrade',
    method: 'POST',
    data: {
      attempt_item_id: attemptItemId,
      reason,
    },
    // 后端 regrade_attempt 同步调大模型重判，超时需放宽。
    timeout: LONG_REQUEST_TIMEOUT_MS,
  })
}

// 8. 诊断报告与错题 API
export function apiTriggerDiagnosis(practiceId: string): Promise<DiagnosisReport> {
  return request<WireDiagnosisReport>({
    url: `/practices/${practiceId}/diagnosis`,
    method: 'POST',
  }).then(adaptDiagnosisReport)
}

export function apiGetDiagnosisReport(practiceId: string): Promise<DiagnosisReport> {
  return request<WireDiagnosisReport>({
    url: `/practices/${practiceId}/diagnosis`,
    method: 'GET',
  }).then(adaptDiagnosisReport)
}

export function apiListWrongRecords(params?: {
  folder_id?: string
  unclassified?: boolean
  material_id?: string
  knowledge_point_id?: string
  is_mastered?: boolean
  page?: number
  page_size?: number
}): Promise<WrongRecordListResult> {
  const queryParts: string[] = []
  if (params?.folder_id) queryParts.push(`folder_id=${encodeURIComponent(params.folder_id)}`)
  if (params?.unclassified !== undefined) queryParts.push(`unclassified=${params.unclassified}`)
  if (params?.material_id) queryParts.push(`material_id=${encodeURIComponent(params.material_id)}`)
  if (params?.knowledge_point_id) queryParts.push(`knowledge_point_id=${encodeURIComponent(params.knowledge_point_id)}`)
  if (params?.is_mastered !== undefined) queryParts.push(`is_mastered=${params.is_mastered}`)
  if (params?.page) queryParts.push(`page=${params.page}`)
  if (params?.page_size) queryParts.push(`page_size=${params.page_size}`)

  const qs = queryParts.length ? `?${queryParts.join('&')}` : ''
  return request<WrongRecordListResult>({
    url: `/wrong-records${qs}`,
    method: 'GET',
  })
}
