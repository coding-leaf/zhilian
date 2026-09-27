/**
 * 题目管理与生成 API 网络接口模块。
 *
 * 封装智能出题生成、题目多条件检索、题目详情、题目人工修改与软删除。
 * 严格遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { request } from '../utils/request';
import {
  adaptGenerateResponse,
  adaptQuestionPage,
  adaptQuestionResponse,
  toQuestionUpdatePayload,
  type QuestionUpdatePayloadInput,
} from './adapters/question';
import type { ApiResponse, PageResult } from '../types/common';
import type {
  QuestionItem,
  QuestionGenerateRequest,
  GenerationRequest,
  QuestionGenerateResponse,
  QuestionListQueryParams,
  QuestionAuditLogsResponse,
  RawQuestionGenerateResponse,
  RawQuestionItem,
} from '../types/question';

/** 出题流水线单次请求超时（毫秒），真实生成耗时可 30s+，故放宽至 3 分钟。 */
export const GENERATE_QUESTIONS_TIMEOUT = 180000;

/**
 * 触发出题生成流水线并执行质检门禁。
 *
 * @param payload 出题生成配置参数模型。
 * @returns 统一响应包，包含出题结果与质检通过题目列表。
 */
export async function generateQuestions(
  payload: QuestionGenerateRequest | GenerationRequest,
): Promise<ApiResponse<QuestionGenerateResponse>> {
  const res = await request<RawQuestionGenerateResponse>({
    url: '/api/v1/questions/generate',
    method: 'POST',
    data: payload,
    timeout: GENERATE_QUESTIONS_TIMEOUT,
  });
  return { ...res, data: adaptGenerateResponse(res.data) };
}

/**
 * 多条件筛选并分页查询题目列表。
 *
 * @param params 过滤与分页参数（资料 ID、知识点 ID、题型、难度、状态等）。
 * @returns 统一响应包，包含题目列表及总数。
 */
export async function fetchQuestionList(
  params?: QuestionListQueryParams,
): Promise<ApiResponse<PageResult<QuestionItem>>> {
  const res = await request<PageResult<RawQuestionItem>>({
    url: '/api/v1/questions',
    method: 'GET',
    data: params,
  });
  return { ...res, data: adaptQuestionPage(res.data) };
}

/**
 * 获取单个题目的元数据与内容详情。
 *
 * @param questionId 题目主键 ID。
 * @returns 统一响应包，包含题目题干、选项、答案与解析。
 */
export async function fetchQuestionDetail(questionId: string): Promise<ApiResponse<QuestionItem>> {
  const res = await request<RawQuestionItem>({
    url: `/api/v1/questions/${questionId}`,
    method: 'GET',
  });
  return adaptQuestionResponse(res);
}

/**
 * 人工更新题目内容并留存审计日志。
 *
 * @param questionId 题目主键 ID。
 * @param payload 待更新的字段与修改原因。
 * @returns 统一响应包，包含更新后的题目详情。
 */
export async function updateQuestion(
  questionId: string,
  payload: QuestionUpdatePayloadInput,
): Promise<ApiResponse<QuestionItem>> {
  const res = await request<RawQuestionItem>({
    url: `/api/v1/questions/${questionId}`,
    method: 'PUT',
    data: toQuestionUpdatePayload(payload),
  });
  return adaptQuestionResponse(res);
}

/**
 * 软删除指定题目并留存审计痕迹。
 *
 * 删除原因以 Query Parameter 传递（与后端 `reason: Query` 契约一致）；
 * DELETE 请求不携带请求体，避免 body 被代理/路由忽略导致审计原因丢失。
 *
 * @param questionId 题目主键 ID。
 * @param reason 可选的删除原因说明。
 * @returns 统一响应包，包含软删除执行结果。
 */
export function deleteQuestion(
  questionId: string,
  reason?: string,
): Promise<ApiResponse<{ id: string; is_deleted: boolean }>> {
  const query = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  return request<{ id: string; is_deleted: boolean }>({
    url: `/api/v1/questions/${questionId}${query}`,
    method: 'DELETE',
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
