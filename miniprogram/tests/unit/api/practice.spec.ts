import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as requestModule from '@/utils/request';
import {
  createPractice,
  fetchPracticeSession,
  saveAnswerDraft,
  submitPractice,
} from '@/api/practice';
import type { CreatePracticePayload, PracticeQuestionItem } from '@/types/practice';

/**
 * Real backend response fixture (`PracticeDetailResponse`), authoritative contract.
 *
 * The list field is `items`, each entry nests `question_snapshot`; option bodies
 * use the `{ key, content }` shape. See backend/app/schemas/practice.py.
 */
const rawPracticeDetail = {
  practice_id: 'prac_001',
  id: 'prac_001',
  title: 'Network Practice',
  material_id: 'mat_001',
  status: 'in_progress',
  total_count: 1,
  items: [
    {
      attempt_item_id: 'att_001',
      id: 'att_001',
      question_id: 'q_001',
      order_index: 1,
      status: 'unanswered',
      is_answered: false,
      time_spent_seconds: 0,
      max_score: 1,
      question_snapshot: {
        stem: 'TCP 建立连接需要几次握手？',
        question_type: 'single_choice',
        options: [
          { key: 'A', content: '1次' },
          { key: 'B', content: '2次' },
          { key: 'C', content: '3次' },
        ],
        answer: 'C',
        analysis: 'TCP通过三次握手建立连接',
        difficulty: 3,
      },
    },
  ],
};

describe('Practice API Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('should call createPractice with POST /api/v1/practices and adapt items into questions', async () => {
    const requestSpy = vi
      .spyOn(requestModule, 'request')
      .mockResolvedValue({ code: 0, message: 'success', data: rawPracticeDetail });

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
    expect(res.data.id).toBe('prac_001');
    expect(res.data.questions).toHaveLength(1);
    const first = res.data.questions[0] as PracticeQuestionItem;
    expect(first.question_type).toBe('single_choice');
    expect(first.stem).toContain('几次握手');
    expect(first.options?.[0]).toEqual({ key: 'A', text: '1次' });
  });

  it('should call fetchPracticeSession with GET /api/v1/practices/:id and adapt items', async () => {
    const requestSpy = vi
      .spyOn(requestModule, 'request')
      .mockResolvedValue({ code: 0, message: 'success', data: rawPracticeDetail });

    const res = await fetchPracticeSession('prac_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/practices/prac_001',
      method: 'GET',
    });
    expect(res.data.questions).toHaveLength(1);
    const first = res.data.questions[0] as PracticeQuestionItem;
    expect(first.id).toBe('q_001');
    expect(first.options?.[2].text).toBe('3次');
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
