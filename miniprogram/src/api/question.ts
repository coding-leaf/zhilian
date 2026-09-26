/**
 * 题目管理与生成 API 网络接口模块。
 *
 * 封装智能出题生成、题目多条件检索、题目详情、题目人工修改与软删除。
 * 严格遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { request } from '../utils/request';
import type { ApiResponse, PageResult } from '../types/common';
import type {
  QuestionItem,
  QuestionGenerateRequest,
  GenerationRequest,
  QuestionGenerateResponse,
  QuestionListQueryParams,
  QuestionUpdateRequest,
  QuestionAuditLogsResponse,
} from '../types/question';

/** 出题流水线单次请求超时（毫秒），真实生成耗时可 30s+，故放宽至 3 分钟。 */
export const GENERATE_QUESTIONS_TIMEOUT = 180000;

/**
 * 触发出题生成流水线并执行质检门禁。
 *
 * @param payload 出题生成配置参数模型。
 * @returns 统一响应包，包含出题结果与质检通过题目列表。
 */
export function generateQuestions(
  payload: QuestionGenerateRequest | GenerationRequest,
): Promise<ApiResponse<QuestionGenerateResponse>> {
  return request<QuestionGenerateResponse>({
    url: '/api/v1/questions/generate',
    method: 'POST',
    data: payload,
    timeout: GENERATE_QUESTIONS_TIMEOUT,
  });
}

/**
 * 多条件筛选并分页查询题目列表。
 *
 * @param params 过滤与分页参数（资料 ID、知识点 ID、题型、难度、状态等）。
 * @returns 统一响应包，包含题目列表及总数。
 */
export function fetchQuestionList(
  params?: QuestionListQueryParams,
): Promise<ApiResponse<PageResult<QuestionItem>>> {
  return request<PageResult<QuestionItem>>({
    url: '/api/v1/questions',
    method: 'GET',
    data: params,
  });
}

/**
 * 获取单个题目的元数据与内容详情。
 *
 * @param questionId 题目主键 ID。
 * @returns 统一响应包，包含题目题干、选项、答案与解析。
 */
export function fetchQuestionDetail(questionId: string): Promise<ApiResponse<QuestionItem>> {
  return request<QuestionItem>({
    url: `/api/v1/questions/${questionId}`,
    method: 'GET',
  });
}

/**
 * 人工更新题目内容并留存审计日志。
 *
 * @param questionId 题目主键 ID。
 * @param payload 待更新的字段与修改原因。
 * @returns 统一响应包，包含更新后的题目详情。
 */
export function updateQuestion(
  questionId: string,
  payload: QuestionUpdateRequest | (Partial<QuestionItem> & { reason?: string }),
): Promise<ApiResponse<QuestionItem>> {
  return request<QuestionItem>({
    url: `/api/v1/questions/${questionId}`,
    method: 'PUT',
    data: payload,
  });
}

/**
 * 软删除指定题目并留存审计痕迹。
 *
 * @param questionId 题目主键 ID。
 * @param reason 可选的删除原因说明。
 * @returns 统一响应包，包含软删除执行结果。
 */
export function deleteQuestion(
  questionId: string,
  reason?: string,
): Promise<ApiResponse<{ id: string; is_deleted: boolean }>> {
  return request<{ id: string; is_deleted: boolean }>({
    url: `/api/v1/questions/${questionId}`,
    method: 'DELETE',
    data: reason ? { reason } : undefined,
  });
}

/**
 * 获取指定题目的修改痕迹审计日志列表。
 *
 * @param questionId 目标题目主键 ID。
 * @returns 统一响应包，包含按时间线排序的修改痕迹。
 */
export function fetchQuestionAudit(
  questionId: string,
): Promise<ApiResponse<QuestionAuditLogsResponse>> {
  return request<QuestionAuditLogsResponse>({
    url: `/api/v1/questions/${questionId}/edit-logs`,
    method: 'GET',
  });
}

/**
 * 获取题目修改审计日志别名方法。
 */
export const fetchQuestionAuditLogs = fetchQuestionAudit;
