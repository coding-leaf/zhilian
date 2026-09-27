/**
 * Practice Submit Idempotency Key Utilities
 *
 * Guarantees a single idempotency key per practice session so timeout/network
 * retries replay the same submission instead of minting a new key (PRAC-003).
 *
 * The key is persisted alongside the practice draft record (the only whitelisted
 * storage slot that fits) with an in-memory fallback so it still works when the
 * storage write degrades (PRAC-004).
 */

import { generateIdempotencyKey, loadDraftFromStorage, saveDraftToStorage } from './draft';
import type { PracticeDraftRecord } from '../types/draft';

const memorySubmitKeys = new Map<string, string>();

/** Minimal draft record used only to persist the submit key before any answer exists. */
function createEmptyDraft(practiceId: string): PracticeDraftRecord {
  return {
    practice_id: practiceId,
    items: {},
    answers: {},
    updated_at: Date.now(),
  };
}

/**
 * Returns the stable submit key for a practice, creating and persisting it on first use.
 *
 * @param practiceId Practice primary key.
 * @returns Reused or newly generated idempotency key.
 */
export function getOrCreateSubmitKey(practiceId: string): string {
  if (!practiceId) {
    return generateIdempotencyKey();
  }

  const draft = loadDraftFromStorage(practiceId);
  const existing = draft?.submit_key ?? memorySubmitKeys.get(practiceId);
  if (existing) {
    memorySubmitKeys.set(practiceId, existing);
    if (draft?.submit_key !== existing) {
      saveDraftToStorage(practiceId, {
        ...(draft ?? createEmptyDraft(practiceId)),
        submit_key: existing,
        updated_at: Date.now(),
      });
    }
    return existing;
  }

  const created = generateIdempotencyKey();
  memorySubmitKeys.set(practiceId, created);
  saveDraftToStorage(practiceId, {
    ...(draft ?? createEmptyDraft(practiceId)),
    submit_key: created,
    updated_at: Date.now(),
  });
  return created;
}

/**
 * Clears the submit key after a confirmed success or an explicit terminal state.
 *
 * @param practiceId Practice primary key.
 */
export function clearSubmitKey(practiceId: string): void {
  memorySubmitKeys.delete(practiceId);
  if (!practiceId) {
    return;
  }

  const draft = loadDraftFromStorage(practiceId);
  if (!draft?.submit_key) {
    return;
  }
  const nextDraft = { ...draft };
  delete nextDraft.submit_key;
  saveDraftToStorage(practiceId, { ...nextDraft, updated_at: Date.now() });
}
