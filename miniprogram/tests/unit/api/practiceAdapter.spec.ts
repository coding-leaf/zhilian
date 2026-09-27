import { describe, expect, it } from 'vitest';
import { adaptPracticeItem, adaptPracticeSession } from '@/api/adapters/practice';
import type { RawPracticeItem, RawPracticeSession } from '@/types/practice';

const rawItem: RawPracticeItem = {
  attempt_item_id: 'att_001',
  id: 'att_001',
  question_id: 'q_001',
  order_index: 1,
  status: 'unanswered',
  is_answered: false,
  time_spent_seconds: 0,
  max_score: 1,
  question_snapshot: {
    stem: '以下哪项是 Python 的不可变数据类型？',
    question_type: 'single_choice',
    options: [
      { key: 'A', content: '列表 (List)' },
      { key: 'B', content: '元组 (Tuple)' },
    ],
    answer: 'B',
    analysis: '元组是不可变的',
    difficulty: 3,
  },
};

describe('practice response adapter (real backend contract)', () => {
  it('flattens items[].question_snapshot into a frontend question (PRAC-001)', () => {
    const question = adaptPracticeItem(rawItem);

    expect(question.id).toBe('q_001');
    expect(question.question_type).toBe('single_choice');
    expect(question.stem).toContain('不可变数据类型');
    expect(question.order_index).toBe(1);
    expect(question.difficulty).toBe(3);
  });

  it('maps backend option content to frontend text (PRAC-002)', () => {
    const question = adaptPracticeItem(rawItem);

    expect(question.options).toHaveLength(2);
    expect(question.options?.[0]).toEqual({ key: 'A', text: '列表 (List)' });
    expect(question.options?.[1].text).toBe('元组 (Tuple)');
  });

  it('falls back to attempt_item_id when question_id is absent', () => {
    const question = adaptPracticeItem({
      attempt_item_id: 'att_only',
      order_index: 2,
      question_snapshot: { stem: 's', question_type: 'short_answer', answer: 'a' },
    });

    expect(question.id).toBe('att_only');
  });

  it('builds a session sorted by order_index from raw items', () => {
    const raw: RawPracticeSession = {
      practice_id: 'practice_999',
      id: 'practice_999',
      title: '综合测试卷',
      material_id: 'mat_1',
      status: 'in_progress',
      items: [
        {
          ...rawItem,
          question_id: 'q_002',
          attempt_item_id: 'att_002',
          order_index: 2,
          question_snapshot: {
            stem: '第二题',
            question_type: 'true_false',
            options: [],
            answer: 'T',
          },
        },
        rawItem,
      ],
    };

    const session = adaptPracticeSession(raw);

    expect(session).not.toBeNull();
    expect(session?.id).toBe('practice_999');
    expect(session?.questions).toHaveLength(2);
    expect(session?.questions[0].id).toBe('q_001');
    expect(session?.questions[1].id).toBe('q_002');
    expect(session?.items).toHaveLength(2);
  });

  it('falls back to a legacy questions field only when items is absent', () => {
    const raw = {
      id: 'p1',
      title: 't',
      material_id: 'm',
      status: 'in_progress',
      questions: [{ id: 'q', stem: 's', question_type: 'short_answer', order_index: 1 }],
    } as RawPracticeSession;

    const session = adaptPracticeSession(raw);

    expect(session?.questions).toHaveLength(1);
    expect(session?.questions[0].id).toBe('q');
  });

  it('returns null for empty input and never throws on malformed snapshots', () => {
    expect(adaptPracticeSession(undefined)).toBeNull();
    expect(adaptPracticeSession(null)).toBeNull();

    const question = adaptPracticeItem({});
    expect(question.id).toBe('');
    expect(question.stem).toBe('');
    expect(question.options).toEqual([]);
  });
});
