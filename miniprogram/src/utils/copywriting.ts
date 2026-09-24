/**
 * 面向用户的零度自然文案转换与计算工具函数库。
 *
 * 严格遵循 docs/DESIGN.md 零度自然文案字典与零表情包原则：
 * - 绝不呈现“乱码率21%”、“BM25”、“置信度”等底层算法术语；
 * - 统一转换为面向用户的清晰、温和引导文案。
 */

import type { MaterialStatus } from '../types/material';

/**
 * 标签徽章样式元数据
 */
export interface MaterialStatusTagInfo {
  text: string;
  type: 'primary' | 'success' | 'warning' | 'danger' | 'info';
}

/**
 * 将 OCR 质检异常原因转换为符合规范的自然文案。
 *
 * @param pageNo 异常页码（从 1 开始）。
 * @param issueType 异常类型标识符。
 * @param rawText 底层异常文本或算法原始描述（已做绝密隔离，严禁外露）。
 * @returns 规范的自然文案（例如“第 4 页文字模糊，需重新拍摄”）。
 */
export function formatOcrIssue(pageNo: number, issueType: string, rawText?: string): string {
  const context = `${issueType || ''} ${rawText || ''}`.toLowerCase().trim();

  if (context.includes('blank') || context.includes('empty') || context.includes('空白')) {
    return `第 ${pageNo} 页内容空白，需重新拍摄`;
  }

  if (
    context.includes('dark') ||
    context.includes('shadow') ||
    context.includes('暗') ||
    context.includes('阴影')
  ) {
    return `第 ${pageNo} 页光线过暗，需重新拍摄`;
  }

  if (
    context.includes('glare') ||
    context.includes('overexposed') ||
    context.includes('光') ||
    context.includes('曝')
  ) {
    return `第 ${pageNo} 页反光过强，需重新拍摄`;
  }

  if (context.includes('skew') || context.includes('tilt') || context.includes('斜')) {
    return `第 ${pageNo} 页拍摄倾斜，需重新拍摄`;
  }

  if (
    context.includes('cut') ||
    context.includes('incomplete') ||
    context.includes('缺') ||
    context.includes('截')
  ) {
    return `第 ${pageNo} 页边缘缺失，需重新拍摄`;
  }

  // 默认统一映射为文字模糊需重新拍摄（绝不包含乱码率等字眼）
  return `第 ${pageNo} 页文字模糊，需重新拍摄`;
}

/**
 * 兼容 formatPageUnqualifiedReason 别名调用。
 *
 * @param pageIndex 页码序号。
 * @param rawReason 原始异常描述。
 * @returns 零度自然文案。
 */
export function formatPageUnqualifiedReason(pageIndex: number, rawReason?: string | null): string {
  return formatOcrIssue(pageIndex, rawReason || 'blur');
}

/**
 * 将资料生命周期状态代码映射为面向用户的零度自然文本。
 *
 * @param status 资料状态代码。
 * @returns 中文自然文案。
 */
export function formatMaterialStatus(status: MaterialStatus): string {
  const normalized = String(status || '').toUpperCase();

  switch (normalized) {
    case 'PENDING':
      return '待解析';
    case 'PARSING':
      return '解析中';
    case 'RETAKE_REQUIRED':
      return '待重新拍摄';
    case 'READY':
    case 'COMPLETED':
      return '已完成';
    case 'FAILED':
      return '解析异常';
    default:
      return '待解析';
  }
}

/**
 * 解析资料状态对应的 wd-tag 样式与文本。
 *
 * @param status 资料状态代码。
 * @returns 包含文案与 tag 类型的元数据对象。
 */
export function resolveMaterialStatusTag(status: MaterialStatus): MaterialStatusTagInfo {
  const normalized = String(status || '').toUpperCase();

  switch (normalized) {
    case 'PENDING':
      return { text: '待解析', type: 'info' };
    case 'PARSING':
      return { text: '解析中', type: 'primary' };
    case 'RETAKE_REQUIRED':
      return { text: '待重新拍摄', type: 'warning' };
    case 'READY':
    case 'COMPLETED':
      return { text: '已完成', type: 'success' };
    case 'FAILED':
      return { text: '解析异常', type: 'danger' };
    default:
      return { text: '待解析', type: 'info' };
  }
}

/**
 * 计算剩余单页重拍次数（默认上限为 3 次）。
 *
 * @param reshootCount 当前已重拍次数。
 * @returns 剩余允许重拍次数，最小为 0。
 */
export function computeRemainingReshoots(reshootCount: number): number {
  const used = Math.max(0, reshootCount || 0);
  return Math.max(0, 3 - used);
}
