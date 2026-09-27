import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as requestModule from '@/utils/request';
import {
  fetchDiagnosisReport,
  fetchMasteryOverview,
  fetchWrongBook,
  markWrongRecordMastered,
  toggleWrongRecordResolved,
  deleteWrongRecord,
  selfGradeQuestion,
  requestRegrade,
  continuePractice,
} from '@/api/diagnosis';

describe('Diagnosis API Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('should call fetchDiagnosisReport with GET /api/v1/practices/:id/diagnosis', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'rep_001',
        practice_id: 'prac_001',
        overall_score: 85,
        mastery_rate: 0.85,
        weak_points: [],
        created_at: '2026-01-01T00:00:00Z',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchDiagnosisReport('prac_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/practices/prac_001/diagnosis',
      method: 'GET',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call fetchMasteryOverview with GET /api/v1/mastery/overview and optional materialId', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        mastered_count: 5,
        proficient_count: 3,
        weak_count: 1,
        unlearned_count: 2,
        weak_points: [],
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchMasteryOverview('mat_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/mastery/overview',
      method: 'GET',
      data: { material_id: 'mat_001' },
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call fetchWrongBook with GET /api/v1/wrong-records and query params', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const params = { material_id: 'mat_001', is_mastered: false, page: 1, page_size: 20 };
    const res = await fetchWrongBook(params);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/wrong-records',
      method: 'GET',
      data: params,
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call markWrongRecordMastered with POST /api/v1/wrong-records/:id/master', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'wr_001',
        is_mastered: true,
        mastered_at: '2026-09-25T12:00:00Z',
        message: '已标记攻克',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await markWrongRecordMastered('wr_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/wrong-records/wr_001/master',
      method: 'POST',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call toggleWrongRecordResolved with optional isMastered status', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'wr_002',
        is_mastered: false,
        mastered_at: null,
        message: '已移出攻克',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await toggleWrongRecordResolved('wr_002', false);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/wrong-records/wr_002/master',
      method: 'POST',
      data: { is_mastered: false },
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call deleteWrongRecord with DELETE /api/v1/wrong-records/:id', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'wr_003',
        removed: true,
        message: '错题已移除',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await deleteWrongRecord('wr_003');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/wrong-records/wr_003',
      method: 'DELETE',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call selfGradeQuestion with POST /api/v1/grading/self-evaluate and payload', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: { grading_record_id: 'rec_001', score: 5.0 },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload = { attempt_item_id: 'att_001', score: 5.0, feedback: 'Correct' };
    const res = await selfGradeQuestion(payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/grading/self-evaluate',
      method: 'POST',
      data: payload,
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call requestRegrade with POST /api/v1/grading/regrade and payload', async () => {
    // Sync regrade contract: success terminal state plus the newly returned score
    const mockResponse = {
      code: 0,
      message: 'success',
      data: { attempt_item_id: 'att_001', status: 'success', score: 4.2 },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload = { attempt_item_id: 'att_001', reason: 'Review requested' };
    const res = await requestRegrade(payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/grading/regrade',
      method: 'POST',
      data: payload,
    });
    expect(res).toEqual(mockResponse);
    expect(res.data?.status).toBe('success');
    expect(res.data?.score).toBe(4.2);
  });

  it('should call continuePractice with POST /api/v1/practices configured for weakness mode', async () => {
    // Real backend contract: PracticeDetailResponse.items[].question_snapshot
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        practice_id: 'prac_weak_001',
        id: 'prac_weak_001',
        title: '薄弱点强化练习',
        material_id: 'mat_001',
        status: 'in_progress',
        items: [
          {
            attempt_item_id: 'att_weak_001',
            question_id: 'q_weak_001',
            order_index: 1,
            question_snapshot: {
              stem: '薄弱点强化题',
              question_type: 'single_choice',
              options: [{ key: 'A', content: '选项正文A' }],
              answer: 'A',
            },
          },
        ],
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload = {
      material_id: 'mat_001',
      knowledge_point_ids: ['kp_001', 'kp_002'],
      source_report_id: 'rep_001',
      question_count: 8,
    };
    const res = await continuePractice(payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/practices',
      method: 'POST',
      data: {
        title: '薄弱点强化练习',
        material_id: 'mat_001',
        knowledge_point_ids: ['kp_001', 'kp_002'],
        source_report_id: 'rep_001',
        source_type: 'weakness',
        mode: 'weak_points',
        question_count: 8,
      },
    });
    expect(res.data.id).toBe('prac_weak_001');
    expect(res.data.questions).toHaveLength(1);
    expect(res.data.questions[0].options?.[0]).toEqual({ key: 'A', text: '选项正文A' });
  });

  it('should call continuePractice with idempotency_key in headers and custom mode', async () => {
    // Real backend contract: PracticeDetailResponse.items[].question_snapshot
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        practice_id: 'prac_wr_002',
        id: 'prac_wr_002',
        title: '错题巩固练习',
        material_id: 'mat_002',
        status: 'in_progress',
        items: [
          {
            attempt_item_id: 'att_wr_001',
            question_id: 'q_wr_001',
            order_index: 1,
            question_snapshot: {
              stem: '错题巩固题',
              question_type: 'true_false',
              options: [],
              answer: 'T',
            },
          },
        ],
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload = {
      material_id: 'mat_002',
      knowledge_point_ids: ['kp_003'],
      source_type: 'wrong_record' as const,
      mode: 'random' as const,
      title: '错题巩固练习',
      idempotency_key: 'idem-key-1234',
      question_count: 5,
    };
    const res = await continuePractice(payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/practices',
      method: 'POST',
      headers: {
        'X-Idempotency-Key': 'idem-key-1234',
      },
      data: {
        title: '错题巩固练习',
        material_id: 'mat_002',
        knowledge_point_ids: ['kp_003'],
        source_report_id: undefined,
        source_type: 'wrong_record',
        mode: 'random',
        question_count: 5,
        idempotency_key: 'idem-key-1234',
      },
    });
    expect(res.data.id).toBe('prac_wr_002');
    expect(res.data.questions).toHaveLength(1);
    expect(res.data.questions[0].question_type).toBe('true_false');
  });
});
