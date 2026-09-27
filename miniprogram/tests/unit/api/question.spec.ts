import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as requestModule from '@/utils/request';
import {
  generateQuestions,
  fetchQuestionList,
  fetchQuestionDetail,
  updateQuestion,
  deleteQuestion,
  fetchQuestionAudit,
  fetchQuestionAuditLogs,
} from '@/api/question';
import type { GenerationRequest, QuestionUpdateRequest } from '@/types/question';

/**
 * Real backend option contract: elements are `{ key, content }`
 * (backend/app/schemas/question.py -> QuestionDetailResponse.options).
 */
const backendOptions = [
  { key: 'A', content: '访问临界资源的代码段' },
  { key: 'B', content: '一种存储设备' },
];

/** Builds a raw backend question payload (before the adapter normalizes it). */
function backendQuestion(overrides: Record<string, unknown> = {}) {
  return {
    id: 'q_001',
    material_id: 'mat_001',
    version_id: 'ver_001',
    knowledge_point_id: 'kp_001',
    question_type: 'single_choice',
    status: 'available',
    is_deleted: false,
    stem: '什么是临界区？',
    options: backendOptions,
    answer: 'A',
    analysis: '临界区指进程中访问临界资源的那段代码。',
    difficulty: 3,
    grading_rubric: {},
    source_snippet_ids: [],
    created_at: '2026-09-27T00:00:00Z',
    updated_at: '2026-09-27T00:00:00Z',
    ...overrides,
  };
}

describe('Question API Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('should call generateQuestions with POST /api/v1/questions/generate and payload', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        batch_id: 'batch_001',
        material_id: 'mat_001',
        version_id: 'ver_001',
        knowledge_point_id: 'kp_001',
        knowledge_point_ids: ['kp_001'],
        total_generated: 2,
        qualified_count: 1,
        pending_count: 1,
        retry_count: 0,
        qualified_questions: [backendQuestion()],
        pending_questions: [backendQuestion({ id: 'q_002', stem: '第二题描述内容' })],
        quality_checks: [],
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload: GenerationRequest = {
      material_id: 'mat_001',
      version_id: 'ver_001',
      knowledge_point_id: 'kp_001',
      count: 3,
      difficulty: 3,
    };
    const res = await generateQuestions(payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/questions/generate',
      method: 'POST',
      data: payload,
      timeout: 180000,
    });
    // Real backend nested option `content` is normalized to frontend `text`.
    expect(res.data.qualified_questions[0].options?.[0]).toEqual({
      key: 'A',
      text: '访问临界资源的代码段',
    });
    expect(res.data.pending_questions[0].options?.[1].text).toBe('一种存储设备');
  });

  it('should call fetchQuestionList with GET /api/v1/questions and normalize options', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        items: [backendQuestion()],
        total: 1,
        limit: 20,
        offset: 0,
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const params = {
      material_id: 'mat_001',
      knowledge_point_id: 'kp_001',
      difficulty: 2,
      page: 1,
      page_size: 20,
    };
    const res = await fetchQuestionList(params);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/questions',
      method: 'GET',
      data: params,
    });
    expect(res.data.items[0].options?.[0]).toEqual({
      key: 'A',
      text: '访问临界资源的代码段',
    });
    expect(res.data.items[0].options?.[1].text).toBe('一种存储设备');
  });

  it('should call fetchQuestionDetail with GET /api/v1/questions/:id and normalize options', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: backendQuestion(),
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchQuestionDetail('q_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/questions/q_001',
      method: 'GET',
    });
    expect(res.data.stem).toBe('什么是临界区？');
    expect(res.data.options?.[0].text).toBe('访问临界资源的代码段');
    expect(res.data.options?.[1].text).toBe('一种存储设备');
  });

  it('should send option content instead of text on updateQuestion', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: backendQuestion({ stem: '更新后的题干内容' }),
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload: QuestionUpdateRequest = {
      stem: '更新后的题干内容',
      options: [{ key: 'A', text: '选项正文' }],
      reason: '修正选项正文',
    };
    const res = await updateQuestion('q_001', payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/questions/q_001',
      method: 'PUT',
      data: {
        stem: '更新后的题干内容',
        options: [{ key: 'A', content: '选项正文' }],
        reason: '修正选项正文',
      },
    });
    // The PUT response is also adapted back into the frontend text contract.
    expect(res.data.options?.[0].text).toBe('访问临界资源的代码段');
  });

  it('should call deleteQuestion with DELETE /api/v1/questions/:id and optional reason', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: { id: 'q_001', is_deleted: true },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await deleteQuestion('q_001', 'Redundant question');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/questions/q_001',
      method: 'DELETE',
      data: { reason: 'Redundant question' },
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call fetchQuestionAudit with GET /api/v1/questions/:id/edit-logs', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        question_id: 'q_001',
        logs: [
          {
            id: 'log_001',
            question_id: 'q_001',
            action: 'EDIT',
            changed_fields: ['stem'],
            before_payload: { stem: 'old' },
            after_payload: { stem: 'new' },
            reason: 'typo',
            created_at: '2026-09-25T00:00:00Z',
          },
        ],
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchQuestionAudit('q_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/questions/q_001/edit-logs',
      method: 'GET',
    });
    expect(res).toEqual(mockResponse);

    // Also verify alias fetchQuestionAuditLogs
    const aliasRes = await fetchQuestionAuditLogs('q_001');
    expect(aliasRes).toEqual(mockResponse);
  });
});
