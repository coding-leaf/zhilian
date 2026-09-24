import { describe, it, expect } from 'vitest';
import {
  flattenKnowledgeTree,
  filterNodesByIds,
  calculateKnowledgeCoverage,
  validateQuestionConfig,
  computeFieldDiffs,
} from '@/subpackages/material/utils/tree';
import type { KnowledgeTreeNode } from '@/types/material';

describe('materialTreeUtils', () => {
  const sampleTree: KnowledgeTreeNode[] = [
    {
      id: 'kp-1',
      name: '操作系统概述',
      level: 1,
      children: [
        {
          id: 'kp-1-1',
          name: '进程与线程概念',
          level: 2,
          parent_id: 'kp-1',
          is_low_confidence: false,
          children: [
            {
              id: 'kp-1-1-1',
              name: '线程同步原语',
              level: 3,
              parent_id: 'kp-1-1',
              is_low_confidence: true,
            },
          ],
        },
        {
          id: 'kp-1-2',
          name: '死锁产生条件',
          level: 2,
          parent_id: 'kp-1',
        },
      ],
    },
    {
      id: 'kp-2',
      name: '内存管理',
      level: 1,
      children: [],
    },
  ];

  describe('flattenKnowledgeTree', () => {
    it('should flatten nested tree correctly into 1D array', () => {
      const flattened = flattenKnowledgeTree(sampleTree);
      expect(flattened).toHaveLength(5);
      expect(flattened.map((n) => n.id)).toEqual(['kp-1', 'kp-1-1', 'kp-1-1-1', 'kp-1-2', 'kp-2']);
    });

    it('should handle empty or null input gracefully', () => {
      expect(flattenKnowledgeTree([])).toEqual([]);
      expect(flattenKnowledgeTree(null as unknown as KnowledgeTreeNode[])).toEqual([]);
    });
  });

  describe('filterNodesByIds', () => {
    it('should filter nodes by given id array', () => {
      const filtered = filterNodesByIds(sampleTree, ['kp-1-1', 'kp-2']);
      expect(filtered).toHaveLength(2);
      expect(filtered.map((n) => n.id)).toEqual(['kp-1-1', 'kp-2']);
    });

    it('should return empty list when no id matches', () => {
      const filtered = filterNodesByIds(sampleTree, ['non-existing']);
      expect(filtered).toEqual([]);
    });
  });

  describe('calculateKnowledgeCoverage', () => {
    it('should return 0 when totalNodes is empty', () => {
      expect(calculateKnowledgeCoverage([], ['kp-1'])).toBe(0);
    });

    it('should calculate coverage correctly for partial selection', () => {
      // 5 total nodes, 2 selected -> 40%
      const coverage = calculateKnowledgeCoverage(sampleTree, ['kp-1', 'kp-2']);
      expect(coverage).toBe(40);
    });

    it('should return 100 when all nodes are selected', () => {
      const allIds = ['kp-1', 'kp-1-1', 'kp-1-1-1', 'kp-1-2', 'kp-2'];
      expect(calculateKnowledgeCoverage(sampleTree, allIds)).toBe(100);
    });

    it('should return 0 when selectedIds is empty', () => {
      expect(calculateKnowledgeCoverage(sampleTree, [])).toBe(0);
    });
  });

  describe('validateQuestionConfig', () => {
    it('should validate valid configuration successfully', () => {
      const res = validateQuestionConfig({
        count: 10,
        question_types: ['single_choice', 'multiple_choice'],
      });
      expect(res.valid).toBe(true);
      expect(res.message).toBeUndefined();
    });

    it('should reject when count is missing or NaN', () => {
      expect(validateQuestionConfig({ question_types: ['single_choice'] }).valid).toBe(false);
      expect(validateQuestionConfig({ count: NaN, question_types: ['single_choice'] }).valid).toBe(
        false,
      );
    });

    it('should reject when count is 0 or negative', () => {
      const resZero = validateQuestionConfig({
        count: 0,
        question_types: ['single_choice'],
      });
      expect(resZero.valid).toBe(false);
      expect(resZero.message).toContain('1 到 50');

      const resNeg = validateQuestionConfig({
        count: -1,
        question_types: ['single_choice'],
      });
      expect(resNeg.valid).toBe(false);
    });

    it('should accept boundary values 1 and 50', () => {
      expect(validateQuestionConfig({ count: 1, question_types: ['single_choice'] }).valid).toBe(
        true,
      );
      expect(validateQuestionConfig({ count: 50, question_types: ['single_choice'] }).valid).toBe(
        true,
      );
    });

    it('should reject when count exceeds 50', () => {
      const res = validateQuestionConfig({
        count: 51,
        question_types: ['single_choice'],
      });
      expect(res.valid).toBe(false);
      expect(res.message).toContain('1 到 50');
    });

    it('should reject when question_types is empty or undefined', () => {
      expect(validateQuestionConfig({ count: 5, question_types: [] }).valid).toBe(false);
      expect(validateQuestionConfig({ count: 5 }).valid).toBe(false);
    });
  });

  describe('computeFieldDiffs', () => {
    it('should detect primitive value changes', () => {
      const before = { stem: 'Original stem', difficulty: 2 };
      const after = { stem: 'Updated stem', difficulty: 2 };
      const diffs = computeFieldDiffs(before, after);
      expect(diffs).toEqual(['stem']);
    });

    it('should detect object and array changes', () => {
      const before = {
        options: [{ key: 'A', text: 'Option A' }],
      };
      const after = {
        options: [
          { key: 'A', text: 'Option A' },
          { key: 'B', text: 'Option B' },
        ],
      };
      const diffs = computeFieldDiffs(before, after);
      expect(diffs).toEqual(['options']);
    });

    it('should return empty list when no field changed', () => {
      const data = { stem: 'Same', difficulty: 3 };
      expect(computeFieldDiffs(data, { ...data })).toEqual([]);
    });
  });
});
