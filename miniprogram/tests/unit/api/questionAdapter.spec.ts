import { describe, expect, it } from 'vitest';
import {
  adaptGenerateResponse,
  adaptQuestionItem,
  adaptQuestionPage,
  toQuestionUpdatePayload,
} from '@/api/adapters/question';
import type { RawQuestionItem, RawQuestionGenerateResponse } from '@/types/question';

/** Real backend question payload: options are `{ key, content }`. */
const rawQuestion: RawQuestionItem = {
  id: 'q_001',
  material_id: 'mat_001',
  version_id: 'ver_001',
  knowledge_point_id: 'kp_001',
  question_type: 'single_choice',
  status: 'available',
  is_deleted: false,
  stem: '以下哪项是 Python 的不可变数据类型？',
  options: [
    { key: 'A', content: '列表 (List)' },
    { key: 'B', content: '元组 (Tuple)' },
  ],
  answer: 'B',
  analysis: '元组是不可变的',
  difficulty: 3,
  grading_rubric: {},
  source_snippet_ids: [],
  created_at: '2026-09-27T00:00:00Z',
  updated_at: '2026-09-27T00:00:00Z',
};

describe('question response adapter (real backend contract)', () => {
  it('maps backend option content to frontend text (QGEN-001)', () => {
    const question = adaptQuestionItem(rawQuestion);

    expect(question.id).toBe('q_001');
    expect(question.stem).toContain('不可变数据类型');
    expect(question.options).toHaveLength(2);
    expect(question.options?.[0]).toEqual({ key: 'A', text: '列表 (List)' });
    expect(question.options?.[1].text).toBe('元组 (Tuple)');
  });

  it('preserves already-adapted text and tolerates malformed options', () => {
    const question = adaptQuestionItem({
      ...rawQuestion,
      options: [{ key: 'A', text: '旧格式文本' }],
    });
    expect(question.options?.[0].text).toBe('旧格式文本');

    const malformed = adaptQuestionItem({ ...rawQuestion, options: undefined });
    expect(malformed.options).toEqual([]);
  });

  it('adapts a paged list payload', () => {
    const page = adaptQuestionPage({ items: [rawQuestion], total: 1, limit: 20, offset: 0 });

    expect(page.total).toBe(1);
    expect(page.items[0].options?.[0].text).toBe('列表 (List)');
  });

  it('adapts both qualified and pending questions in a generate response', () => {
    const raw: RawQuestionGenerateResponse = {
      batch_id: 'batch_001',
      material_id: 'mat_001',
      version_id: 'ver_001',
      knowledge_point_id: 'kp_001',
      knowledge_point_ids: ['kp_001'],
      total_generated: 2,
      qualified_count: 1,
      pending_count: 1,
      retry_count: 0,
      qualified_questions: [rawQuestion],
      pending_questions: [{ ...rawQuestion, id: 'q_002' }],
      quality_checks: [],
    };

    const adapted = adaptGenerateResponse(raw);

    expect(adapted.qualified_questions[0].options?.[0].text).toBe('列表 (List)');
    expect(adapted.pending_questions[0].options?.[1].text).toBe('元组 (Tuple)');
  });

  it('maps frontend option text back to backend content on update', () => {
    const payload = toQuestionUpdatePayload({
      stem: '新题干',
      options: [{ key: 'A', text: '选项正文' }],
      reason: '修正',
    });

    expect(payload.options).toEqual([{ key: 'A', content: '选项正文' }]);
    expect(payload.stem).toBe('新题干');
    expect(payload.reason).toBe('修正');
  });

  it('omits options for payloads that do not carry them', () => {
    const payload = toQuestionUpdatePayload({ stem: '新题干', reason: '修正' });
    expect(payload.options).toBeUndefined();
  });
});
