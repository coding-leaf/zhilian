/**
 * 练习会话与作答调度 API 网络接口模块。
 *
 * 封装练习创建组卷、会话查询、作答草稿实时暂存与强幂等交卷提交。
 * 严格遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { request } from '../utils/request';
import type { ApiResponse } from '../types/common';
import type { PracticeSession, CreatePracticePayload, SaveAnswerPayload } from '../types/practice';

/**
 * 创建练习会话并执行智能组卷。
 *
 * @param payload 包含资料 ID、知识点列表与题量模式等出题配置。
 * @returns 统一响应包，包含已创建的练习详情与卷面题目快照。
 */
export function createPractice(
  payload: CreatePracticePayload,
): Promise<ApiResponse<PracticeSession>> {
  return request<PracticeSession>({
    url: '/api/v1/practices',
    method: 'POST',
    data: payload,
  });
}

/**
 * 查询指定练习会话详情及其卷面题目作答快照。
 *
 * @param practiceId 练习主键 ID。
 * @returns 统一响应包，包含练习信息与题目列表。
 */
export function fetchPracticeSession(practiceId: string): Promise<ApiResponse<PracticeSession>> {
  return request<PracticeSession>({
    url: `/api/v1/practices/${practiceId}`,
    method: 'GET',
  });
}

/**
 * 做题过程中逐题草稿暂存与作答耗时累加。
 *
 * @param practiceId 练习主键 ID。
 * @param payload 题目 ID、作答内容及单题耗时秒数。
 * @returns 统一响应包，包含暂存状态与作答记录详情。
 */
export function saveAnswerDraft(
  practiceId: string,
  payload: SaveAnswerPayload,
): Promise<ApiResponse<{ attempt_item_id: string; status: string }>> {
  return request<{ attempt_item_id: string; status: string }>({
    url: `/api/v1/practices/${practiceId}/answers`,
    method: 'PUT',
    data: payload,
  });
}

/**
 * 提交练习交卷，携带强幂等键防止重复提交并调度判题。
 *
 * @param practiceId 练习主键 ID。
 * @param idempotencyKey 客户端生成的唯一幂等键 UUIDv4。
 * @param payload 可选的交卷确认选项（如确认提交包含未作答题目）。
 * @returns 统一响应包，包含交卷受理与调度结果。
 */
export function submitPractice(
  practiceId: string,
  idempotencyKey: string,
  payload?: { confirm_unanswered?: boolean },
): Promise<ApiResponse<{ practice_id: string; status: string }>> {
  return request<{ practice_id: string; status: string }>({
    url: `/api/v1/practices/${practiceId}/submit`,
    method: 'POST',
    data: payload,
    headers: {
      'Idempotency-Key': idempotencyKey,
    },
  });
}
