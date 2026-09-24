import { describe, it, expect } from 'vitest';
import {
  formatOcrIssue,
  formatMaterialStatus,
  formatPageUnqualifiedReason,
  computeRemainingReshoots,
  resolveMaterialStatusTag,
} from '@/utils/copywriting';

describe('Copywriting Utils Module', () => {
  describe('formatOcrIssue', () => {
    it('should format blur issue with zero-degree phrasing', () => {
      const text = formatOcrIssue(4, 'blur');
      expect(text).toBe('第 4 页文字模糊，需重新拍摄');
    });

    it('should format blank issue with natural phrasing', () => {
      const text = formatOcrIssue(2, 'blank');
      expect(text).toBe('第 2 页内容空白，需重新拍摄');
    });

    it('should format dark lighting issue', () => {
      const text = formatOcrIssue(3, 'dark');
      expect(text).toBe('第 3 页光线过暗，需重新拍摄');
    });

    it('should format glare issue', () => {
      const text = formatOcrIssue(5, 'glare');
      expect(text).toBe('第 5 页反光过强，需重新拍摄');
    });

    it('should format skewed image issue', () => {
      const text = formatOcrIssue(1, 'skew');
      expect(text).toBe('第 1 页拍摄倾斜，需重新拍摄');
    });

    it('should format cut_off image issue', () => {
      const text = formatOcrIssue(6, 'cut_off');
      expect(text).toBe('第 6 页边缘缺失，需重新拍摄');
    });

    it('should never expose technical algorithm terms even if rawText contains them', () => {
      const forbiddenTerms = ['乱码率', 'BM25', '置信度', '算法', '模型', 'OCR'];
      const rawText = 'OCR识别失败，乱码率21%，模型置信度0.45低于阈值';
      const text = formatOcrIssue(4, 'blur', rawText);

      expect(text).toBe('第 4 页文字模糊，需重新拍摄');
      forbiddenTerms.forEach((term) => {
        expect(text).not.toContain(term);
      });
    });

    it('should fallback to blurred text reason for unknown issue types', () => {
      const text = formatOcrIssue(7, 'unknown_issue_code');
      expect(text).toBe('第 7 页文字模糊，需重新拍摄');
    });

    it('should support formatPageUnqualifiedReason alias', () => {
      expect(formatPageUnqualifiedReason(4, 'blur')).toBe('第 4 页文字模糊，需重新拍摄');
      expect(formatPageUnqualifiedReason(2, 'blank')).toBe('第 2 页内容空白，需重新拍摄');
    });
  });

  describe('formatMaterialStatus', () => {
    it('should format pending status', () => {
      expect(formatMaterialStatus('pending')).toBe('待解析');
      expect(formatMaterialStatus('PENDING')).toBe('待解析');
    });

    it('should format parsing status', () => {
      expect(formatMaterialStatus('parsing')).toBe('解析中');
      expect(formatMaterialStatus('PARSING')).toBe('解析中');
    });

    it('should format retake_required status', () => {
      expect(formatMaterialStatus('retake_required')).toBe('待重新拍摄');
      expect(formatMaterialStatus('RETAKE_REQUIRED')).toBe('待重新拍摄');
    });

    it('should format ready and completed status', () => {
      expect(formatMaterialStatus('ready')).toBe('已完成');
      expect(formatMaterialStatus('READY')).toBe('已完成');
      expect(formatMaterialStatus('completed')).toBe('已完成');
      expect(formatMaterialStatus('COMPLETED')).toBe('已完成');
    });

    it('should format failed status', () => {
      expect(formatMaterialStatus('failed')).toBe('解析异常');
      expect(formatMaterialStatus('FAILED')).toBe('解析异常');
    });
  });

  describe('resolveMaterialStatusTag', () => {
    it('should resolve correct tag metadata for all statuses', () => {
      expect(resolveMaterialStatusTag('pending')).toEqual({ text: '待解析', type: 'info' });
      expect(resolveMaterialStatusTag('parsing')).toEqual({ text: '解析中', type: 'primary' });
      expect(resolveMaterialStatusTag('retake_required')).toEqual({
        text: '待重新拍摄',
        type: 'warning',
      });
      expect(resolveMaterialStatusTag('completed')).toEqual({
        text: '已完成',
        type: 'success',
      });
      expect(resolveMaterialStatusTag('failed')).toEqual({
        text: '解析异常',
        type: 'danger',
      });
    });
  });

  describe('computeRemainingReshoots', () => {
    it('should calculate remaining reshoots correctly', () => {
      expect(computeRemainingReshoots(0)).toBe(3);
      expect(computeRemainingReshoots(1)).toBe(2);
      expect(computeRemainingReshoots(2)).toBe(1);
      expect(computeRemainingReshoots(3)).toBe(0);
      expect(computeRemainingReshoots(4)).toBe(0);
    });
  });
});
