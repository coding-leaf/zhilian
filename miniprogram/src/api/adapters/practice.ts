/**
 * Practice response adapter.
 *
 * Single adaptation boundary between the backend practice contract
 * (`PracticeDetailResponse.items[].question_snapshot`, options `{ key, content }`)
 * and the flattened frontend `PracticeSession.questions` consumers.
 *
 * Authoritative contract: backend/app/schemas/practice.py
 * See spec: backend/quality-guidelines.md "Backend<->Frontend Response Field-Name Contract Pinning".
 */

import type { ApiResponse } from '../../types/common';
import type {
  PracticeQuestionItem,
  PracticeQuestionOption,
  PracticeSession,
  PracticeStatus,
  RawPracticeItem,
  RawPracticeQuestionOption,
  RawPracticeSession,
} from '../../types/practice';

const EMPTY_SESSION: PracticeSession = {
  id: '',
  title: '练习作答',
  material_id: '',
  status: 'idle',
  questions: [],
};

/** Normalizes backend options `{ key, content }` into frontend `{ key, text }`. */
function adaptOptions(options?: RawPracticeQuestionOption[]): PracticeQuestionOption[] {
  if (!Array.isArray(options)) {
    return [];
  }
  return options
    .filter((option): option is RawPracticeQuestionOption => !!option && typeof option === 'object')
    .map((option, index) => ({
      key:
        typeof option.key === 'string' && option.key.length > 0
          ? option.key
          : String.fromCharCode(65 + index),
      text:
        typeof option.content === 'string'
          ? option.content
          : typeof option.text === 'string'
            ? option.text
            : '',
    }));
}

/** Normalizes backend practice status values into the frontend status union. */
function adaptStatus(status?: string): PracticeStatus {
  switch (status) {
    case 'in_progress':
    case 'paused':
      return status;
    case 'completed':
    case 'partially_graded':
      return 'submitted';
    case 'not_started':
      return 'idle';
    default:
      return 'in_progress';
  }
}

/**
 * Flattens one backend attempt item (`items[]`) into a frontend question.
 *
 * @param item Raw backend `PracticeItemDetailResponse` entry.
 * @returns Frontend renderable/consumable question.
 */
export function adaptPracticeItem(item: RawPracticeItem): PracticeQuestionItem {
  const snapshot = item.question_snapshot ?? {};
  return {
    id: item.question_id ?? item.attempt_item_id ?? item.id ?? '',
    question_type: snapshot.question_type ?? 'short_answer',
    stem: snapshot.stem ?? '',
    options: adaptOptions(snapshot.options),
    order_index: item.order_index ?? 0,
    answer: snapshot.answer ?? '',
    analysis: snapshot.analysis ?? snapshot.explanation ?? '',
    difficulty: snapshot.difficulty ?? 3,
    grading_rubric: snapshot.grading_rubric ?? {},
    source_snippet_id: snapshot.source_snippet_id ?? null,
  };
}

/**
 * Adapts a raw backend practice detail payload into the frontend `PracticeSession`.
 *
 * Primary path consumes `items[].question_snapshot`. A legacy fallback keeps an
 * already-flattened `questions[]` field working for older mocks, but it is never
 * the real backend path.
 *
 * @param raw Raw backend payload (or null/undefined).
 * @returns Adapted session, or `null` when there is no payload.
 */
export function adaptPracticeSession(
  raw: RawPracticeSession | null | undefined,
): PracticeSession | null {
  if (!raw) {
    return null;
  }

  const rawItems = Array.isArray(raw.items) ? raw.items : [];
  let questions: PracticeQuestionItem[];
  if (rawItems.length > 0) {
    questions = rawItems
      .map((item) => adaptPracticeItem(item))
      .sort((a, b) => a.order_index - b.order_index);
  } else {
    const legacy = raw.questions;
    questions = Array.isArray(legacy)
      ? legacy.filter((item): item is PracticeQuestionItem => !!item && typeof item === 'object')
      : [];
  }

  return {
    id: raw.practice_id ?? raw.id ?? '',
    title: raw.title ?? '练习作答',
    material_id: raw.material_id ?? '',
    status: adaptStatus(raw.status),
    questions,
    items: rawItems,
    current_index: raw.current_index,
    time_elapsed_seconds: raw.time_elapsed_seconds,
    created_at: raw.created_at,
  };
}

/**
 * Adapts a full `ApiResponse` wrapper so API modules can return the frontend contract.
 *
 * @param res Raw backend response envelope.
 * @returns Response envelope whose `data` is a `PracticeSession`.
 */
export function adaptPracticeResponse(
  res: ApiResponse<RawPracticeSession>,
): ApiResponse<PracticeSession> {
  return {
    ...res,
    data: adaptPracticeSession(res.data) ?? { ...EMPTY_SESSION },
  };
}
