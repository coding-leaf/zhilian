import { request } from '@/utils/request'
import {
  MAX_PRACTICE_QUESTIONS,
  type CreatePracticeParams,
  type PracticeListQuery,
  type PracticeListResult,
  type PracticeSession,
  type PracticeSummary,
} from '@/types'
import { adaptPractice, type WirePracticeDetail } from '../adapters'

export { MAX_PRACTICE_QUESTIONS }
export type { CreatePracticeParams, PracticeSummary }

export function apiCreatePractice(params: CreatePracticeParams): Promise<PracticeSession> {
  return request<WirePracticeDetail>({
    url: '/practices',
    method: 'POST',
    data: params,
  }).then(adaptPractice)
}

export function apiGetPracticeSession(practiceId: string): Promise<PracticeSession> {
  return request<WirePracticeDetail>({
    url: `/practices/${practiceId}`,
    method: 'GET',
  }).then(adaptPractice)
}

export function apiListPractices(params?: PracticeListQuery): Promise<PracticeListResult> {
  const queryParts: string[] = []
  if (params?.status) queryParts.push(`status=${encodeURIComponent(params.status)}`)
  if (params?.material_id) queryParts.push(`material_id=${encodeURIComponent(params.material_id)}`)
  if (params?.offset !== undefined) queryParts.push(`offset=${params.offset}`)
  if (params?.limit !== undefined) queryParts.push(`limit=${params.limit}`)
  const qs = queryParts.length ? `?${queryParts.join('&')}` : ''
  return request<PracticeListResult>({ url: `/practices${qs}`, method: 'GET' })
}

export function apiSavePracticeDraft(
  practiceId: string,
  questionId: string,
  userAnswer: unknown,
  timeSpentSeconds = 0,
  options?: { silentToast?: boolean },
): Promise<{ success: boolean }> {
  return request({
    url: `/practices/${practiceId}/answers`,
    method: 'PUT',
    silentToast: options?.silentToast ?? true,
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
