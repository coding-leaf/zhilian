import { describe, expect, it } from 'vitest';
import {
  formatBatchLabel,
  groupQuestionsByBatch,
} from '@/subpackages/material/utils/questionBatch';
import type { QuestionItem } from '@/types/question';

function makeQuestion(id: string, batchId?: string | null): QuestionItem {
  return {
    id,
    material_id: 'mat_1',
    version_id: 'ver_1',
    knowledge_point_id: 'kp_1',
    question_type: 'single_choice',
    stem: `题目 ${id}`,
    difficulty: 3,
    batch_id: batchId ?? null,
  };
}

describe('questionBatch utils', () => {
  it('formats batch labels with a fallback for legacy rows', () => {
    expect(formatBatchLabel('batch_abc123')).toBe('批次 abc123');
    expect(formatBatchLabel(null)).toBe('历史题目');
    expect(formatBatchLabel(undefined)).toBe('历史题目');
  });

  it('groups questions by batch while preserving order', () => {
    const groups = groupQuestionsByBatch([
      makeQuestion('q1', 'batch_a'),
      makeQuestion('q2', 'batch_b'),
      makeQuestion('q3', 'batch_a'),
    ]);

    expect(groups.map((group) => group.batchId)).toEqual(['batch_a', 'batch_b']);
    expect(groups[0].items.map((item) => item.id)).toEqual(['q1', 'q3']);
    expect(groups[1].items.map((item) => item.id)).toEqual(['q2']);
  });

  it('places legacy questions without batch id into one group', () => {
    const groups = groupQuestionsByBatch([makeQuestion('q1'), makeQuestion('q2', null)]);
    expect(groups).toHaveLength(1);
    expect(groups[0].batchId).toBeNull();
    expect(groups[0].label).toBe('历史题目');
    expect(groups[0].items).toHaveLength(2);
  });

  it('returns an empty array for an empty list', () => {
    expect(groupQuestionsByBatch([])).toEqual([]);
  });
});
