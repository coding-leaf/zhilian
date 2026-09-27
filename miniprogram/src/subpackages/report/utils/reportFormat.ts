/**
 * ZhiLian Mini-Program Diagnostic Report Formatting & Pure Calculation Utilities
 * Independent pure functions with 100% branch coverage guarantee.
 * Complies with docs/DESIGN.md & spec ZL-135.
 * Zero-Emoji Policy: No emoji in strings, labels, or error messages.
 */

import type { MasteryTierInfo, GradingStatusInfo, SnippetHighlightPart } from '@/types/report';

/**
 * Format duration in seconds to standard timer string (mm:ss or HH:mm:ss).
 *
 * @param seconds Duration in seconds.
 * @returns Formatted time string.
 */
export function formatReportDuration(seconds?: number | null): string {
  if (
    seconds === null ||
    seconds === undefined ||
    typeof seconds !== 'number' ||
    Number.isNaN(seconds) ||
    seconds < 0
  ) {
    return '00:00';
  }

  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;

  const pad = (val: number): string => (val < 10 ? `0${val}` : `${val}`);

  if (hours > 0) {
    return `${pad(hours)}:${pad(minutes)}:${pad(secs)}`;
  }
  return `${pad(minutes)}:${pad(secs)}`;
}

export const formatDuration = formatReportDuration;

/**
 * Map mastery score or rate to one of the four discrete mastery tiers.
 * Thresholds: >=0.85 mastered, [0.70, 0.85) proficient, [0.40, 0.70) weak, <0.40 unlearned.
 *
 * @param scoreOrRate Numeric score (0.0~1.0 or 0~100).
 * @returns Mastery tier metadata.
 */
export function getMasteryTierInfo(scoreOrRate?: number | null): MasteryTierInfo {
  if (
    scoreOrRate === null ||
    scoreOrRate === undefined ||
    typeof scoreOrRate !== 'number' ||
    Number.isNaN(scoreOrRate)
  ) {
    return {
      tier: 'unlearned',
      label: '未学',
      color: '#64748B',
      bgColor: '#F1F5F9',
      fillColor: '#94A3B8',
    };
  }

  const normalized = scoreOrRate > 1 ? scoreOrRate / 100 : scoreOrRate;
  const value = Math.max(0, normalized);

  if (value >= 0.85) {
    return {
      tier: 'mastered',
      label: '精通',
      color: '#7C3AED',
      bgColor: '#F5F3FF',
      fillColor: '#8B5CF6',
    };
  }
  if (value >= 0.7) {
    return {
      tier: 'proficient',
      label: '良好',
      color: '#059669',
      bgColor: '#ECFDF5',
      fillColor: '#10B981',
    };
  }
  if (value >= 0.4) {
    return {
      tier: 'weak',
      label: '需巩固',
      color: '#B45309',
      bgColor: '#FFFBEB',
      fillColor: '#F59E0B',
    };
  }
  return {
    tier: 'unlearned',
    label: '未学',
    color: '#64748B',
    bgColor: '#F1F5F9',
    fillColor: '#94A3B8',
  };
}

/**
 * Determine grading status display info for a single practice item.
 *
 * @param item Item with status and score attributes.
 * @returns Item grading status metadata.
 */
export function getGradingStatusInfo(item?: {
  grading_status?: string | null;
  status?: string;
  score?: number | null;
  max_score?: number;
}): GradingStatusInfo {
  if (!item) {
    return {
      status: 'unanswered',
      label: '未作答',
      color: '#94A3B8',
      bgColor: '#F1F5F9',
      borderColor: '#CBD5E1',
      textColor: '#64748B',
    };
  }

  // 1. Authoritative grading_status from backend (takes precedence over legacy status/score)
  if (item.grading_status === 'pending_regrade') {
    return {
      status: 'pending_regrade',
      label: '待重新判题',
      color: '#F59E0B',
      bgColor: '#FFFBEB',
      borderColor: '#FDE68A',
      textColor: '#92400E',
    };
  }

  if (item.grading_status === 'unanswered') {
    return {
      status: 'unanswered',
      label: '未作答',
      color: '#94A3B8',
      bgColor: '#F1F5F9',
      borderColor: '#CBD5E1',
      textColor: '#64748B',
    };
  }

  // 2. Legacy fallback is only allowed when grading_status is absent entirely.
  //    When grading_status === 'graded', the legacy `status` field is stale for real
  //    ORM items (always "unanswered"/"answered") and must not override the verdict.
  const hasExplicitStatus = item.grading_status !== null && item.grading_status !== undefined;

  if (!hasExplicitStatus && item.status === 'pending_regrade') {
    return {
      status: 'pending_regrade',
      label: '待重新判题',
      color: '#F59E0B',
      bgColor: '#FFFBEB',
      borderColor: '#FDE68A',
      textColor: '#92400E',
    };
  }

  // 3. Unanswered items (legacy fallback only)
  if (!hasExplicitStatus && item.status === 'unanswered') {
    return {
      status: 'unanswered',
      label: '未作答',
      color: '#94A3B8',
      bgColor: '#F1F5F9',
      borderColor: '#CBD5E1',
      textColor: '#64748B',
    };
  }

  // 4. Submitted but missing score
  if (item.score === null || item.score === undefined) {
    return {
      status: 'pending_regrade',
      label: '待重新判题',
      color: '#F59E0B',
      bgColor: '#FFFBEB',
      borderColor: '#FDE68A',
      textColor: '#92400E',
    };
  }

  // 5. Number score evaluated
  const maxScore = typeof item.max_score === 'number' && item.max_score > 0 ? item.max_score : 1.0;
  if (item.score >= maxScore * 0.6) {
    return {
      status: 'correct',
      label: '判对',
      color: '#10B981',
      bgColor: '#ECFDF5',
      borderColor: '#A7F3D0',
      textColor: '#065F46',
    };
  }

  return {
    status: 'wrong',
    label: '判错',
    color: '#EF4444',
    bgColor: '#FEF2F2',
    borderColor: '#FECACA',
    textColor: '#991B1B',
  };
}

/**
 * Safely split content into plain text and highlight segments using regex escaping.
 * Completely immune to XSS or HTML injection vulnerabilities.
 *
 * @param content Full snippet content text.
 * @param keywords Keywords to highlight.
 * @returns List of highlight parts.
 */
export function splitSnippetHighlights(
  content?: string | null,
  keywords?: string[] | null,
): SnippetHighlightPart[] {
  if (!content) {
    return [];
  }

  if (!keywords || keywords.length === 0) {
    return [{ text: content, isHighlight: false }];
  }

  // Sanitize and filter non-empty unique keywords
  const validKeywords = Array.from(
    new Set(keywords.map((k) => (typeof k === 'string' ? k.trim() : '')).filter(Boolean)),
  );

  if (validKeywords.length === 0) {
    return [{ text: content, isHighlight: false }];
  }

  // Escape special regex characters
  const escaped = validKeywords.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  // Match longer keywords first
  escaped.sort((a, b) => b.length - a.length);

  const regex = new RegExp(`(${escaped.join('|')})`, 'g');
  const parts: SnippetHighlightPart[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({
        text: content.slice(lastIndex, match.index),
        isHighlight: false,
      });
    }
    parts.push({
      text: match[0],
      isHighlight: true,
    });
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < content.length) {
    parts.push({
      text: content.slice(lastIndex),
      isHighlight: false,
    });
  }

  return parts;
}

export const highlightSnippetKeywords = splitSnippetHighlights;

/**
 * Format score delta and judge significant regression.
 * A score delta <= -0.05 is regarded as significant regression.
 *
 * @param delta Score change delta.
 * @returns Formatted delta string and regression boolean flag.
 */
export function formatScoreDelta(delta?: number | null): { text: string; isRegressed: boolean } {
  if (delta === null || delta === undefined || typeof delta !== 'number' || Number.isNaN(delta)) {
    return { text: '0%', isRegressed: false };
  }

  const isRegressed = delta <= -0.05;
  const isNormalized = Math.abs(delta) <= 1.0;
  const percent = isNormalized ? Math.round(delta * 100) : Math.round(delta);

  const prefix = percent > 0 ? '+' : '';
  const text = `${prefix}${percent}%`;

  return { text, isRegressed };
}
