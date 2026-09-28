import { request, uploadFile } from '@/utils/request'
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
  DiagnosisReport,
  RegradeResponse,
  SelfEvaluateResponse,
  AskCoachResponse,
  WrongRecordListResult,
} from '@/types'

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
  folderId?: string
): Promise<MaterialItem> {
  const formData: Record<string, string> = {}
  if (title) formData.title = title
  if (folderId) formData.folder_id = folderId
  return uploadFile<MaterialItem>(filePath, 'file', formData)
}

export function apiGetMaterialDetail(id: string): Promise<MaterialItem> {
  return request<MaterialItem>({
    url: `/materials/${id}`,
    method: 'GET',
  })
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
      return res.items
    }
    return (res as MaterialItem[]) || []
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
  question_types?: string[]
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
  return request<QuestionGenerateResult>({
    url: '/questions/generate',
    method: 'POST',
    data: params,
  })
}

export function apiGetQuestionsByMaterial(materialId: string): Promise<QuestionItem[]> {
  return request<{ items: QuestionItem[] } | QuestionItem[]>({
    url: `/questions?material_id=${materialId}`,
    method: 'GET',
  }).then((res) => {
    if (res && 'items' in res) return res.items
    return (res as QuestionItem[]) || []
  })
}

export function apiAskQuestionCoach(
  questionId: string,
  userPrompt: string,
  userAnswer?: string,
  gradingPoints?: string[]
): Promise<AskCoachResponse> {
  return request<AskCoachResponse>({
    url: `/questions/${questionId}/ask-coach`,
    method: 'POST',
    data: {
      user_prompt: userPrompt,
      user_answer: userAnswer,
      grading_points: gradingPoints,
    },
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
  question_types?: string[]
  difficulty?: number
  mode?: string
  source_type?: string
  source_report_id?: string
}

export function apiCreatePractice(params: CreatePracticeParams | string, questionIds?: string[]): Promise<PracticeSession> {
  const payload = typeof params === 'string'
    ? { material_id: params, question_ids: questionIds }
    : params
  return request<PracticeSession>({
    url: '/practices',
    method: 'POST',
    data: payload,
  })
}

export function apiGetPracticeSession(practiceId: string): Promise<PracticeSession> {
  return request<PracticeSession>({
    url: `/practices/${practiceId}`,
    method: 'GET',
  })
}

export function apiSavePracticeDraft(
  practiceId: string,
  questionId: string,
  userAnswer: any,
  timeSpentSeconds = 0
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
  confirmUnanswered = true
): Promise<{ practice_id: string; status: string; task_id?: string }> {
  // 生成客户端幂等键 (UUIDv4 格式)
  const idempotencyKey = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })

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

// 7. 判题与复查 API
export function apiSelfEvaluate(
  attemptItemId: string,
  score: number,
  feedback?: string,
  isCorrect?: boolean
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
  })
}

// 8. 诊断报告与错题 API
export function apiTriggerDiagnosis(practiceId: string): Promise<DiagnosisReport> {
  return request<DiagnosisReport>({
    url: `/practices/${practiceId}/diagnosis`,
    method: 'POST',
  })
}

export function apiGetDiagnosisReport(practiceId: string): Promise<DiagnosisReport> {
  return request<DiagnosisReport>({
    url: `/practices/${practiceId}/diagnosis`,
    method: 'GET',
  })
}

export function apiListWrongRecords(params?: {
  material_id?: string
  knowledge_point_id?: string
  is_mastered?: boolean
  page?: number
  page_size?: number
}): Promise<WrongRecordListResult> {
  const queryParts: string[] = []
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
