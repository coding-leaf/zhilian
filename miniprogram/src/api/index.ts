import { request, uploadFile } from '@/utils/request'
import type {
  LoginResult,
  UserProfile,
  MaterialItem,
  QuestionItem,
  PracticeSession,
  DiagnosisReport,
} from '@/types'

// 1. 认证 API
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

// 2. 资料 API
export function apiUploadMaterial(filePath: string, title?: string): Promise<MaterialItem> {
  return uploadFile<MaterialItem>(filePath, 'file', title ? { title } : undefined)
}

export function apiGetMaterialDetail(id: string): Promise<MaterialItem> {
  return request<MaterialItem>({
    url: `/materials/${id}`,
    method: 'GET',
  })
}

export function apiGetMaterialList(): Promise<MaterialItem[]> {
  return request<MaterialItem[]>({
    url: '/materials',
    method: 'GET',
  })
}

// 3. 题目与出题 API
export interface GenerateQuestionsParams {
  material_id: string
  count?: number
  difficulty?: number
  types?: string[]
}

export function apiGenerateQuestions(params: GenerateQuestionsParams): Promise<{ task_id?: string; count: number }> {
  return request({
    url: '/questions/generate',
    method: 'POST',
    data: params,
  })
}

export function apiGetQuestionsByMaterial(materialId: string): Promise<QuestionItem[]> {
  return request<QuestionItem[]>({
    url: `/questions?material_id=${materialId}`,
    method: 'GET',
  })
}

// 4. 练习作答与交卷 API
export function apiCreatePractice(materialId: string, questionIds?: string[]): Promise<PracticeSession> {
  return request<PracticeSession>({
    url: '/practices',
    method: 'POST',
    data: {
      material_id: materialId,
      question_ids: questionIds,
    },
  })
}

export function apiGetPracticeSession(practiceId: string): Promise<PracticeSession> {
  return request<PracticeSession>({
    url: `/practices/${practiceId}`,
    method: 'GET',
  })
}

export function apiSavePracticeDraft(practiceId: string, answers: Record<string, any>): Promise<{ success: boolean }> {
  return request({
    url: `/practices/${practiceId}/answers`,
    method: 'PUT',
    data: { answers },
  })
}

export function apiSubmitPractice(practiceId: string): Promise<{ practice_id: string; status: string }> {
  return request({
    url: `/practices/${practiceId}/submit`,
    method: 'POST',
  })
}

// 5. 诊断报告 API
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
