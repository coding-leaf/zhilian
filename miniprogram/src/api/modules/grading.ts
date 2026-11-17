import { request } from '@/utils/request'
import { LONG_REQUEST_TIMEOUT_MS } from '@/utils/requestError'
import type { RegradeResponse, SelfEvaluateResponse } from '@/types'

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
