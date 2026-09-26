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
import type { GenerationRequest } from '@/types/question';

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
        total_generated: 3,
        qualified_count: 3,
        pending_count: 0,
        retry_count: 0,
        qualified_questions: [],
        pending_questions: [],
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
    expect(res).toEqual(mockResponse);
  });

  it('should call fetchQuestionList with GET /api/v1/questions and query params', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        items: [
          {
            id: 'q_001',
            material_id: 'mat_001',
            version_id: 'ver_001',
            knowledge_point_id: 'kp_001',
            question_type: 'single_choice',
            stem: 'What is HTTP?',
            difficulty: 2,
          },
        ],
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
    expect(res).toEqual(mockResponse);
  });

  it('should call fetchQuestionDetail with GET /api/v1/questions/:id', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'q_001',
        material_id: 'mat_001',
        version_id: 'ver_001',
        knowledge_point_id: 'kp_001',
        question_type: 'single_choice',
        stem: 'What is HTTP?',
        difficulty: 2,
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchQuestionDetail('q_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/questions/q_001',
      method: 'GET',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call updateQuestion with PUT /api/v1/questions/:id and payload', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'q_001',
        stem: 'Updated question stem',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload = { stem: 'Updated question stem', reason: 'Typo fix' };
    const res = await updateQuestion('q_001', payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/questions/q_001',
      method: 'PUT',
      data: payload,
    });
    expect(res).toEqual(mockResponse);
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
