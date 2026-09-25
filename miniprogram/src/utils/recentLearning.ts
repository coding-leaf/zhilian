/**
 * 最近学习与活跃练习提取工具函数。
 *
 * 纯函数计算核：提取未完成练习草稿信息与相对时间格式化。
 * 遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import type { MaterialItem } from '@/types/material';
import type { AnswerDraft } from '@/types/practice';

export interface ActivePracticeInfo {
  practiceId: string;
  title: string;
  answeredCount: number;
  totalCount: number;
  updatedAtText: string;
}

/**
 * 格式化相对时间文本。
 */
export function formatRelativeTime(
  timestamp?: number | string | null,
  nowMs: number = Date.now(),
): string {
  if (!timestamp) return '最近';
  const timeMs = typeof timestamp === 'number' ? timestamp : new Date(timestamp).getTime();
  if (Number.isNaN(timeMs) || timeMs <= 0) return '最近';

  const diff = nowMs - timeMs;
  if (diff < 0) return '刚刚';
  if (diff < 60_000) return '刚刚';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)}天前`;

  const d = new Date(timeMs);
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * 纯函数计算核：从本地草稿字典与资料中提取最新未完成练习信息。
 */
export function extractLatestDraftPractice(
  drafts?: Record<string, AnswerDraft> | null,
  materials?: MaterialItem[] | null,
  nowMs: number = Date.now(),
): ActivePracticeInfo | null {
  if (!drafts || typeof drafts !== 'object') return null;

  const draftList = Object.values(drafts).filter(
    (d) => d && typeof d === 'object' && d.practice_id && typeof d.updated_at === 'number',
  );

  if (draftList.length === 0) return null;

  draftList.sort((a, b) => b.updated_at - a.updated_at);
  const latest = draftList[0];

  let answeredCount = 0;
  if (latest.answers && typeof latest.answers === 'object') {
    for (const key of Object.keys(latest.answers)) {
      const ans = latest.answers[key];
      if (
        ans !== undefined &&
        ans !== null &&
        ans !== '' &&
        !(Array.isArray(ans) && ans.length === 0)
      ) {
        answeredCount += 1;
      }
    }
  }

  const rawAny = latest as unknown as Record<string, unknown>;
  const totalCount =
    typeof rawAny.total_count === 'number' && rawAny.total_count > 0
      ? rawAny.total_count
      : typeof rawAny.totalCount === 'number' && rawAny.totalCount > 0
        ? rawAny.totalCount
        : Math.max(10, answeredCount);

  let title = typeof rawAny.title === 'string' && rawAny.title ? rawAny.title : '';
  if (!title && rawAny.material_id && materials) {
    const matched = materials.find((m) => m.id === rawAny.material_id);
    if (matched?.title) {
      title = `${matched.title} 专项练习`;
    }
  }
  if (!title) {
    title = '专项练习';
  }

  return {
    practiceId: latest.practice_id,
    title,
    answeredCount,
    totalCount,
    updatedAtText: formatRelativeTime(latest.updated_at, nowMs),
  };
}
