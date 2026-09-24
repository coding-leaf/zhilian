/**
 * 学情诊断、掌握度看板与错题闭环 API 网络接口模块。
 *
 * 封装诊断报告查询、艾宾浩斯掌握度全景、错题本检索、主观题自评、申请重判及薄弱点继续练习。
 * 严格遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { request } from '../utils/request';
import type { ApiResponse, PageResult } from '../types/common';
import type { PracticeSession } from '../types/practice';
import type {
  DiagnosisReport,
  UserMasteryOverview,
  WrongRecordItem,
  WrongRecordQueryParams,
  SelfGradePayload,
  RegradePayload,
  ContinuePracticePayload,
} from '../types/report';

/**
 * 查询指定练习会话关联的学情诊断报告。
 *
 * @param practiceId 练习主键 ID。
 * @returns 统一响应包，包含总体得分、掌握率及薄弱知识点诊断。
 */
export function fetchDiagnosisReport(practiceId: string): Promise<ApiResponse<DiagnosisReport>> {
  return request<DiagnosisReport>({
    url: `/api/v1/practices/${practiceId}/diagnosis`,
    method: 'GET',
  });
}

/**
 * 获取当前登录用户的艾宾浩斯掌握度宏观全景概览。
 *
 * @param materialId 可选的学习资料主键 ID，缺省查询全量掌握度。
 * @returns 统一响应包，包含四档掌握度统计与薄弱知识点清单。
 */
export function fetchMasteryOverview(
  materialId?: string,
): Promise<ApiResponse<UserMasteryOverview>> {
  return request<UserMasteryOverview>({
    url: '/api/v1/mastery/overview',
    method: 'GET',
    data: materialId ? { material_id: materialId } : undefined,
  });
}

/**
 * 多维条件分页检索错题本记录。
 *
 * @param params 过滤与分页参数（资料 ID、知识点 ID、错误类型、攻克状态等）。
 * @returns 统一响应包，包含错题原题快照与错误解析列表。
 */
export function fetchWrongBook(
  params?: WrongRecordQueryParams,
): Promise<ApiResponse<PageResult<WrongRecordItem>>> {
  return request<PageResult<WrongRecordItem>>({
    url: '/api/v1/wrong-records',
    method: 'GET',
    data: params,
  });
}

/**
 * 主观题用户自主评分提交。
 *
 * @param payload 包含作答项 ID、自评分数及评价反馈。
 * @returns 统一响应包，包含生成的自评记录详情。
 */
export function selfGradeQuestion(
  payload: SelfGradePayload,
): Promise<ApiResponse<{ grading_record_id: string; score: number }>> {
  return request<{ grading_record_id: string; score: number }>({
    url: '/api/v1/grading/self-evaluate',
    method: 'POST',
    data: payload,
  });
}

/**
 * 申请主观题重新判题。
 *
 * @param payload 包含作答项 ID 与重判申请原因。
 * @returns 统一响应包，包含重判受理状态。
 */
export function requestRegrade(
  payload: RegradePayload,
): Promise<ApiResponse<{ attempt_item_id: string; status: string }>> {
  return request<{ attempt_item_id: string; status: string }>({
    url: '/api/v1/grading/regrade',
    method: 'POST',
    data: payload,
  });
}

/**
 * 基于诊断报告中的薄弱知识点发起继续强化练习。
 *
 * @param payload 包含资料 ID、薄弱知识点列表及来源报告 ID。
 * @returns 统一响应包，包含新生成的强化练习会话。
 */
export function continuePractice(
  payload: ContinuePracticePayload,
): Promise<ApiResponse<PracticeSession>> {
  return request<PracticeSession>({
    url: '/api/v1/practices',
    method: 'POST',
    data: {
      title: payload.title || '薄弱点强化练习',
      material_id: payload.material_id,
      knowledge_point_ids: payload.knowledge_point_ids,
      source_report_id: payload.source_report_id,
      source_type: 'weakness',
      mode: 'weak_points',
      question_count: payload.question_count ?? 10,
    },
  });
}
