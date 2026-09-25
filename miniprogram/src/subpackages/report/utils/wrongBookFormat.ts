/**
 * ZhiLian Mini-Program Wrong Book Formatting & Pure Calculation Utilities
 * Independent pure functions with 100% branch coverage guarantee.
 * Complies with docs/DESIGN.md & spec ZL-136.
 * Zero-Emoji Policy: No emoji in strings, labels, or error messages.
 */

import type {
  ErrorTypeInfo,
  ResolvedStatusInfo,
  WrongRecordItem,
  WrongRecordQueryParams,
  ContinuePracticePayload,
} from '@/types/report';

/**
 * Map error type code to visual style tokens.
 *
 * @param errorType Error type code (conceptual, incomplete, deviation, unanswered).
 * @returns ErrorTypeInfo metadata.
 */
export function getErrorTypeInfo(errorType?: string): ErrorTypeInfo {
  switch (errorType) {
    case 'incomplete':
      return {
        type: 'incomplete',
        label: '表述不全',
        color: '#F59E0B',
        bgColor: '#FFFBEB',
        borderColor: '#FDE68A',
      };
    case 'deviation':
      return {
        type: 'deviation',
        label: '审题偏差',
        color: '#3B82F6',
        bgColor: '#EFF6FF',
        borderColor: '#BFDBFE',
      };
    case 'unanswered':
      return {
        type: 'unanswered',
        label: '未作答',
        color: '#64748B',
        bgColor: '#F1F5F9',
        borderColor: '#E2E8F0',
      };
    case 'conceptual':
    default:
      return {
        type: 'conceptual',
        label: '概念性错误',
        color: '#EF4444',
        bgColor: '#FEF2F2',
        borderColor: '#FECACA',
      };
  }
}

export const getErrorTypeMeta = getErrorTypeInfo;

/**
 * Map resolved/mastered boolean status to badge tokens.
 *
 * @param isMastered Whether question is resolved/mastered.
 * @returns ResolvedStatusInfo metadata.
 */
export function getResolvedStatusInfo(isMastered: boolean): ResolvedStatusInfo {
  if (isMastered) {
    return {
      label: '已攻克',
      color: '#10B981',
      bgColor: '#ECFDF5',
      isMastered: true,
    };
  }
  return {
    label: '待攻克',
    color: '#F59E0B',
    bgColor: '#FFFBEB',
    isMastered: false,
  };
}

/**
 * Format total wrong attempts count.
 *
 * @param count Numeric wrong attempt count.
 * @returns Human-readable label (e.g. 答错 2 次).
 */
export function formatWrongCount(count?: number | null): string {
  if (
    count === null ||
    count === undefined ||
    typeof count !== 'number' ||
    Number.isNaN(count) ||
    count <= 0
  ) {
    return '答错 1 次';
  }
  return `答错 ${Math.floor(count)} 次`;
}

/**
 * Format relative error timestamp into readable text.
 *
 * @param timestamp ISO date string or epoch timestamp.
 * @param now Reference timestamp (defaults to Date.now()).
 * @returns Friendly relative time string.
 */
export function formatRelativeErrorTime(
  timestamp?: string | number | null,
  now: number = Date.now(),
): string {
  if (timestamp === null || timestamp === undefined || timestamp === '') {
    return '刚刚';
  }

  const time = typeof timestamp === 'number' ? timestamp : new Date(timestamp).getTime();
  if (Number.isNaN(time)) {
    return '刚刚';
  }

  const diffMs = now - time;
  if (diffMs < 60_000) {
    return '刚刚';
  }
  if (diffMs < 3600_000) {
    return `${Math.floor(diffMs / 60_000)}分钟前`;
  }
  if (diffMs < 86400_000) {
    return `${Math.floor(diffMs / 3600_000)}小时前`;
  }
  if (diffMs < 30 * 86400_000) {
    return `${Math.floor(diffMs / 86400_000)}天前`;
  }

  const date = new Date(time);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * Filter wrong record items in-memory.
 *
 * @param records Array of wrong records.
 * @param filters Query filter criteria.
 * @returns Filtered records.
 */
export function filterWrongRecords(
  records: WrongRecordItem[],
  filters: WrongRecordQueryParams,
): WrongRecordItem[] {
  if (!Array.isArray(records) || records.length === 0) {
    return [];
  }

  return records.filter((item) => {
    if (filters.material_id && item.material_id && item.material_id !== filters.material_id) {
      return false;
    }
    if (filters.knowledge_point_id && item.knowledge_point_id !== filters.knowledge_point_id) {
      return false;
    }
    if (filters.error_type && item.error_type !== filters.error_type) {
      return false;
    }
    if (filters.is_mastered !== undefined && item.is_mastered !== filters.is_mastered) {
      return false;
    }
    if (filters.question_type) {
      const qType = item.question_type || item.question_snapshot?.question_type;
      if (qType !== filters.question_type) {
        return false;
      }
    }
    return true;
  });
}

/**
 * Generate standard UUID v4 string for request idempotency.
 * Format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
 *
 * @returns Valid UUID v4 string.
 */
export function generateIdempotencyKey(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Universal debounce wrapper with cancel handle.
 *
 * @param fn Callback function.
 * @param delay Debounce delay in milliseconds (default 500ms).
 * @returns Debounced executor with cancel method.
 */
export function debounce<T extends (...args: unknown[]) => unknown>(
  fn: T,
  delay: number = 500,
): ((...args: Parameters<T>) => void) & { cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;

  const debounced = (...args: Parameters<T>) => {
    if (timer !== null) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, delay);
  };

  debounced.cancel = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  return debounced;
}

/**
 * Build typed ContinuePracticePayload.
 *
 * @param params Parameter inputs.
 * @returns Structured ContinuePracticePayload.
 */
export function buildContinuePracticePayload(params: {
  materialId?: string;
  knowledgePointIds: string[];
  sourceReportId?: string;
  title?: string;
  questionCount?: number;
  sourceType?: 'weakness' | 'wrong_record';
  mode?: 'weak_points' | 'random';
  idempotencyKey?: string;
}): ContinuePracticePayload {
  return {
    material_id: params.materialId,
    knowledge_point_ids: params.knowledgePointIds,
    source_report_id: params.sourceReportId,
    title: params.title || '薄弱点强化练习',
    question_count: params.questionCount ?? 10,
    source_type: params.sourceType ?? 'weakness',
    mode: params.mode ?? 'weak_points',
    idempotency_key: params.idempotencyKey,
  };
}
