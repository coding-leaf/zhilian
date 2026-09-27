/**
 * Question batch grouping helpers.
 *
 * Groups a flat question list into generation batches so the list page can
 * render "course -> batch" sections and offer per-batch filtering.
 * Pure functions only; zero side effects. Zero-Emoji; lines <= 300.
 */

import type { QuestionItem } from '@/types/question';

export interface QuestionBatchGroup {
  /** Batch id shared by the group, or null for legacy questions without one. */
  batchId: string | null;
  /** Human readable group label. */
  label: string;
  items: QuestionItem[];
}

const UNKNOWN_BATCH_KEY = '__unknown__';

/**
 * Formats a batch id into a stable, human readable label.
 *
 * @param batchId Raw batch id (may be null for legacy rows).
 * @returns Display label for the batch header.
 */
export function formatBatchLabel(batchId?: string | null): string {
  if (!batchId) {
    return '历史题目';
  }
  return `批次 ${batchId.replace(/^batch_/, '')}`;
}

/**
 * Groups questions into batches while preserving the incoming order.
 *
 * @param items Flat question list (already ordered by the server).
 * @returns Ordered batch groups; legacy rows without `batch_id` share one group.
 */
export function groupQuestionsByBatch(items: QuestionItem[]): QuestionBatchGroup[] {
  const groups: QuestionBatchGroup[] = [];
  const indexByKey = new Map<string, number>();

  for (const item of items) {
    const key = item.batch_id || UNKNOWN_BATCH_KEY;
    const groupIndex = indexByKey.get(key);
    if (groupIndex === undefined) {
      indexByKey.set(key, groups.length);
      groups.push({
        batchId: item.batch_id ?? null,
        label: formatBatchLabel(item.batch_id),
        items: [item],
      });
    } else {
      groups[groupIndex].items.push(item);
    }
  }

  return groups;
}
