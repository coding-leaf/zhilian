import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as requestModule from '@/utils/request';
import {
  createPractice,
  fetchPracticeSession,
  saveAnswerDraft,
  submitPractice,
} from '@/api/practice';
import type { CreatePracticePayload } from '@/types/practice';

describe('Practice API Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('should call createPractice with POST /api/v1/practices and payload', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'prac_001',
        title: 'Network Practice',
        material_id: 'mat_001',
        status: 'in_progress',
        questions: [],
        created_at: '2026-01-01T00:00:00Z',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload: CreatePracticePayload = {
      title: 'Network Practice',
      material_id: 'mat_001',
      knowledge_point_ids: ['kp_001'],
      question_count: 5,
    };
    const res = await createPractice(payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/practices',
      method: 'POST',
      data: payload,
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call fetchPracticeSession with GET /api/v1/practices/:id', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'prac_001',
        title: 'Network Practice',
        material_id: 'mat_001',
        status: 'in_progress',
        questions: [],
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchPracticeSession('prac_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/practices/prac_001',
      method: 'GET',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call saveAnswerDraft with PUT /api/v1/practices/:id/answers and payload', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        attempt_item_id: 'att_001',
        status: 'answered',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload = {
      question_id: 'q_001',
      user_answer: 'A',
      time_spent_seconds: 15,
    };
    const res = await saveAnswerDraft('prac_001', payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/practices/prac_001/answers',
      method: 'PUT',
      data: payload,
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call submitPractice with POST /api/v1/practices/:id/submit and Idempotency-Key header', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        practice_id: 'prac_001',
        status: 'completed',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await submitPractice('prac_001', 'idem_key_uuid_123', {
      confirm_unanswered: true,
    });

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/practices/prac_001/submit',
      method: 'POST',
      data: { confirm_unanswered: true },
      headers: { 'Idempotency-Key': 'idem_key_uuid_123' },
    });
    expect(res).toEqual(mockResponse);
  });
});
