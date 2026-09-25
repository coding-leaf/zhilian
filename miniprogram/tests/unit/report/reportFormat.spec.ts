import { describe, expect, it } from 'vitest';
import {
  formatDuration,
  formatReportDuration,
  formatScoreDelta,
  getGradingStatusInfo,
  getMasteryTierInfo,
  highlightSnippetKeywords,
  splitSnippetHighlights,
} from '@/subpackages/report/utils/reportFormat';

describe('reportFormat pure utility functions', () => {
  describe('formatReportDuration / formatDuration', () => {
    it('returns 00:00 for invalid, negative, or missing inputs', () => {
      expect(formatReportDuration(null)).toBe('00:00');
      expect(formatReportDuration(undefined)).toBe('00:00');
      expect(formatReportDuration(Number.NaN)).toBe('00:00');
      expect(formatReportDuration(-10)).toBe('00:00');
      expect(formatDuration(null)).toBe('00:00');
    });

    it('formats seconds below 1 hour to mm:ss correctly', () => {
      expect(formatReportDuration(0)).toBe('00:00');
      expect(formatReportDuration(9)).toBe('00:09');
      expect(formatReportDuration(59)).toBe('00:59');
      expect(formatReportDuration(65)).toBe('01:05');
      expect(formatReportDuration(3599)).toBe('59:59');
    });

    it('formats durations >= 1 hour to HH:mm:ss correctly', () => {
      expect(formatReportDuration(3600)).toBe('01:00:00');
      expect(formatReportDuration(3665)).toBe('01:01:05');
      expect(formatReportDuration(7325)).toBe('02:02:05');
    });
  });

  describe('getMasteryTierInfo', () => {
    it('handles null, undefined, NaN, and negative values', () => {
      const res = getMasteryTierInfo(null);
      expect(res.tier).toBe('unlearned');
      expect(res.label).toBe('未学');
      expect(res.color).toBe('#64748B');

      expect(getMasteryTierInfo(undefined).tier).toBe('unlearned');
      expect(getMasteryTierInfo(Number.NaN).tier).toBe('unlearned');
      expect(getMasteryTierInfo(-0.5).tier).toBe('unlearned');
    });

    it('handles discrete 0~1 normalized score boundaries', () => {
      // < 0.40 -> unlearned
      expect(getMasteryTierInfo(0).tier).toBe('unlearned');
      expect(getMasteryTierInfo(0.399).tier).toBe('unlearned');

      // [0.40, 0.70) -> weak
      const weak = getMasteryTierInfo(0.4);
      expect(weak.tier).toBe('weak');
      expect(weak.label).toBe('需巩固');
      expect(weak.color).toBe('#B45309');
      expect(weak.bgColor).toBe('#FFFBEB');
      expect(getMasteryTierInfo(0.699).tier).toBe('weak');

      // [0.70, 0.85) -> proficient
      const prof = getMasteryTierInfo(0.7);
      expect(prof.tier).toBe('proficient');
      expect(prof.label).toBe('良好');
      expect(prof.color).toBe('#059669');
      expect(prof.bgColor).toBe('#ECFDF5');
      expect(getMasteryTierInfo(0.849).tier).toBe('proficient');

      // >= 0.85 -> mastered
      const mast = getMasteryTierInfo(0.85);
      expect(mast.tier).toBe('mastered');
      expect(mast.label).toBe('精通');
      expect(mast.color).toBe('#7C3AED');
      expect(mast.bgColor).toBe('#F5F3FF');
      expect(getMasteryTierInfo(1.0).tier).toBe('mastered');
    });

    it('handles 0~100 percentage score inputs', () => {
      expect(getMasteryTierInfo(39).tier).toBe('unlearned');
      expect(getMasteryTierInfo(50).tier).toBe('weak');
      expect(getMasteryTierInfo(75).tier).toBe('proficient');
      expect(getMasteryTierInfo(90).tier).toBe('mastered');
    });
  });

  describe('getGradingStatusInfo', () => {
    it('handles empty item or missing parameters', () => {
      const res = getGradingStatusInfo();
      expect(res.status).toBe('unanswered');
      expect(res.label).toBe('未作答');
      expect(res.color).toBe('#94A3B8');
    });

    it('identifies pending_regrade explicitly or by missing score', () => {
      const explicit = getGradingStatusInfo({ status: 'pending_regrade' });
      expect(explicit.status).toBe('pending_regrade');
      expect(explicit.label).toBe('待重新判题');
      expect(explicit.color).toBe('#F59E0B');

      const missingScore = getGradingStatusInfo({ status: 'submitted', score: null });
      expect(missingScore.status).toBe('pending_regrade');
      expect(missingScore.label).toBe('待重新判题');
    });

    it('identifies unanswered items correctly', () => {
      const unanswered = getGradingStatusInfo({ status: 'unanswered', score: null });
      expect(unanswered.status).toBe('unanswered');
      expect(unanswered.label).toBe('未作答');
    });

    it('identifies correct and wrong items against max_score threshold (60%)', () => {
      // Default max_score = 1.0
      const correctDefault = getGradingStatusInfo({ score: 0.6 });
      expect(correctDefault.status).toBe('correct');
      expect(correctDefault.label).toBe('判对');
      expect(correctDefault.color).toBe('#10B981');

      const wrongDefault = getGradingStatusInfo({ score: 0.59 });
      expect(wrongDefault.status).toBe('wrong');
      expect(wrongDefault.label).toBe('判错');
      expect(wrongDefault.color).toBe('#EF4444');

      // Custom max_score = 5.0 (60% is 3.0)
      const correctCustom = getGradingStatusInfo({ score: 3.0, max_score: 5.0 });
      expect(correctCustom.status).toBe('correct');

      const wrongCustom = getGradingStatusInfo({ score: 2.5, max_score: 5.0 });
      expect(wrongCustom.status).toBe('wrong');
    });
  });

  describe('splitSnippetHighlights / highlightSnippetKeywords', () => {
    it('returns empty array when content is empty or null', () => {
      expect(splitSnippetHighlights(null, ['test'])).toEqual([]);
      expect(splitSnippetHighlights('', ['test'])).toEqual([]);
      expect(highlightSnippetKeywords('', [])).toEqual([]);
    });

    it('returns single unhighlighted part when keywords are missing or empty', () => {
      const res = splitSnippetHighlights('Hello world', []);
      expect(res).toEqual([{ text: 'Hello world', isHighlight: false }]);

      const emptyKeywords = splitSnippetHighlights('Hello world', ['  ', '']);
      expect(emptyKeywords).toEqual([{ text: 'Hello world', isHighlight: false }]);
    });

    it('splits and highlights matched keywords safely with regex chars', () => {
      const text = '在 C++ 中，指针 int* ptr 和函数 foo() 是重要概念。';
      const keywords = ['C++', 'foo()', 'int* ptr'];

      const parts = splitSnippetHighlights(text, keywords);
      expect(parts.length).toBeGreaterThan(1);

      const highlightedTexts = parts.filter((p) => p.isHighlight).map((p) => p.text);
      expect(highlightedTexts).toContain('C++');
      expect(highlightedTexts).toContain('int* ptr');
      expect(highlightedTexts).toContain('foo()');

      // Reconstructed text must strictly equal original text
      const reconstructed = parts.map((p) => p.text).join('');
      expect(reconstructed).toBe(text);
    });

    it('prioritizes longer overlapping keywords', () => {
      const text = '二叉树后序遍历算法详解';
      const keywords = ['遍历', '后序遍历'];

      const parts = splitSnippetHighlights(text, keywords);
      const highlighted = parts.filter((p) => p.isHighlight);
      expect(highlighted.length).toBe(1);
      expect(highlighted[0].text).toBe('后序遍历');
    });
  });

  describe('formatScoreDelta', () => {
    it('handles null, undefined, and NaN inputs', () => {
      expect(formatScoreDelta(null)).toEqual({ text: '0%', isRegressed: false });
      expect(formatScoreDelta(undefined)).toEqual({ text: '0%', isRegressed: false });
      expect(formatScoreDelta(Number.NaN)).toEqual({ text: '0%', isRegressed: false });
    });

    it('determines regression when delta <= -0.05', () => {
      expect(formatScoreDelta(-0.05)).toEqual({ text: '-5%', isRegressed: true });
      expect(formatScoreDelta(-0.15)).toEqual({ text: '-15%', isRegressed: true });
      expect(formatScoreDelta(-0.049)).toEqual({ text: '-5%', isRegressed: false });
    });

    it('formats positive and neutral deltas correctly', () => {
      expect(formatScoreDelta(0)).toEqual({ text: '0%', isRegressed: false });
      expect(formatScoreDelta(0.12)).toEqual({ text: '+12%', isRegressed: false });
      expect(formatScoreDelta(15)).toEqual({ text: '+15%', isRegressed: false });
    });
  });
});
