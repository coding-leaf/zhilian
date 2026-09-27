/**
 * Question response/payload adapter.
 *
 * Single adaptation boundary between the backend question contract and the
 * frontend `{ key, text }` option consumers (QuestionCard / edit / audit).
 *
 * Authoritative contract: backend/app/schemas/question.py
 *   - `QuestionDetailResponse.options` elements are `{ key, content }`.
 *   - `QuestionUpdateRequest.options` elements are `{ key, content }`.
 * See spec: backend/quality-guidelines.md
 *   "Backend<->Frontend Response Field-Name Contract Pinning".
 */

import type { ApiResponse, PageResult } from '../../types/common';
import type {
  QuestionGenerateResponse,
  QuestionItem,
  QuestionOption,
  QuestionUpdateRequest,
  RawQuestionGenerateResponse,
  RawQuestionItem,
  RawQuestionOption,
  RawQuestionUpdatePayload,
} from '../../types/question';

/** Union accepted by `updateQuestion` at the API boundary. */
export type QuestionUpdatePayloadInput =
  QuestionUpdateRequest | (Partial<QuestionItem> & { reason?: string });

/** Normalizes backend options `{ key, content }` into frontend `{ key, text }`. */
function adaptOptions(options?: RawQuestionOption[]): QuestionOption[] {
  if (!Array.isArray(options)) {
    return [];
  }
  return options
    .filter((option): option is RawQuestionOption => !!option && typeof option === 'object')
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

/**
 * Normalizes one raw backend question into the frontend consumable shape.
 *
 * @param raw Raw backend `QuestionDetailResponse` payload.
 * @returns Frontend question whose options use the `text` field.
 */
export function adaptQuestionItem(raw: RawQuestionItem): QuestionItem {
  return {
    id: raw.id ?? '',
    material_id: raw.material_id ?? '',
    version_id: raw.version_id ?? '',
    knowledge_point_id: raw.knowledge_point_id ?? '',
    source_snippet_id: raw.source_snippet_id ?? null,
    question_type: (raw.question_type ?? 'short_answer') as QuestionItem['question_type'],
    status: raw.status,
    is_deleted: raw.is_deleted,
    stem: raw.stem ?? '',
    options: adaptOptions(raw.options),
    answer: raw.answer,
    analysis: raw.analysis,
    difficulty: raw.difficulty ?? 3,
    grading_rubric: raw.grading_rubric,
    source_snippet_ids: raw.source_snippet_ids,
    reason: raw.reason,
    created_at: raw.created_at,
    updated_at: raw.updated_at,
  };
}

/**
 * Adapts a paged question list payload.
 *
 * @param raw Raw backend `QuestionListResponse` payload.
 * @returns Paged payload whose items use the frontend option contract.
 */
export function adaptQuestionPage(raw: PageResult<RawQuestionItem>): PageResult<QuestionItem> {
  const items = Array.isArray(raw?.items) ? raw.items : [];
  return { ...raw, items: items.map((item) => adaptQuestionItem(item)) };
}

/**
 * Adapts a generate response, normalizing both qualified and pending questions.
 *
 * @param raw Raw backend `QuestionGenerateResponse` payload.
 * @returns Generate response whose nested questions use the frontend option contract.
 */
export function adaptGenerateResponse(raw: RawQuestionGenerateResponse): QuestionGenerateResponse {
  const qualified = Array.isArray(raw?.qualified_questions) ? raw.qualified_questions : [];
  const pending = Array.isArray(raw?.pending_questions) ? raw.pending_questions : [];
  return {
    ...raw,
    qualified_questions: qualified.map((item) => adaptQuestionItem(item)),
    pending_questions: pending.map((item) => adaptQuestionItem(item)),
  };
}

/**
 * Maps frontend option `text` back to the backend `content` contract before an update.
 *
 * @param payload Frontend update request (or partial question).
 * @returns Backend-shaped update payload whose options use `content`.
 */
export function toQuestionUpdatePayload(
  payload: QuestionUpdatePayloadInput,
): RawQuestionUpdatePayload {
  const { options, ...rest } = payload;
  if (!Array.isArray(options)) {
    return { ...rest };
  }
  return {
    ...rest,
    options: options.map((option) => ({
      key: option.key,
      content: option.content ?? option.text ?? '',
    })),
  };
}

/**
 * Adapts a full `ApiResponse` wrapper for a single question.
 *
 * @param res Raw backend response envelope.
 * @returns Response envelope whose `data` is a frontend `QuestionItem`.
 */
export function adaptQuestionResponse(
  res: ApiResponse<RawQuestionItem>,
): ApiResponse<QuestionItem> {
  return {
    ...res,
    data: adaptQuestionItem(res.data),
  };
}
