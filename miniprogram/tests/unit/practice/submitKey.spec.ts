import { describe, expect, it, beforeEach, vi } from 'vitest';
import { getOrCreateSubmitKey, clearSubmitKey } from '@/subpackages/practice/utils/submitKey';
import {
  createOrUpdateDraft,
  saveDraftToStorage,
  loadDraftFromStorage,
} from '@/subpackages/practice/utils/draft';
import { storage } from '@/utils/storage';
import { AppError } from '@/utils/error';

const UUID_V4_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe('Practice Submit Key Utilities (submitKey.ts)', () => {
  const memoryStore: Record<string, unknown> = {};

  beforeEach(() => {
    Object.keys(memoryStore).forEach((k) => delete memoryStore[k]);

    uni.getStorageSync = ((key: string) =>
      memoryStore[key] ?? null) as unknown as typeof uni.getStorageSync;
    uni.setStorageSync = (key: string, data: unknown) => {
      memoryStore[key] = data;
    };
    uni.removeStorageSync = (key: string) => {
      delete memoryStore[key];
    };
    uni.clearStorageSync = () => {
      Object.keys(memoryStore).forEach((k) => delete memoryStore[k]);
    };

    storage.clear();
    vi.restoreAllMocks();
  });

  it('reuses the same key for the same practice within a session (PRAC-003)', () => {
    const first = getOrCreateSubmitKey('p_1');
    const second = getOrCreateSubmitKey('p_1');

    expect(first).toBe(second);
    expect(first).toMatch(UUID_V4_REGEX);
  });

  it('generates distinct keys for distinct practices', () => {
    expect(getOrCreateSubmitKey('p_1')).not.toBe(getOrCreateSubmitKey('p_2'));
  });

  it('persists the key into the practice draft record', () => {
    saveDraftToStorage('p_1', createOrUpdateDraft(null, 'p_1', 'q_1', 'A', 5));

    const key = getOrCreateSubmitKey('p_1');

    expect(loadDraftFromStorage('p_1')?.submit_key).toBe(key);
  });

  it('persists the key even before any answer draft exists (PRAC-003)', () => {
    expect(loadDraftFromStorage('p_no_draft')).toBeNull();

    const key = getOrCreateSubmitKey('p_no_draft');

    expect(loadDraftFromStorage('p_no_draft')?.submit_key).toBe(key);
  });

  it('clears the key and regenerates a fresh one afterwards', () => {
    saveDraftToStorage('p_1', createOrUpdateDraft(null, 'p_1', 'q_1', 'A', 5));
    const key = getOrCreateSubmitKey('p_1');

    clearSubmitKey('p_1');

    expect(loadDraftFromStorage('p_1')?.submit_key).toBeUndefined();
    expect(getOrCreateSubmitKey('p_1')).not.toBe(key);
  });

  it('degrades to in-memory reuse when the storage write fails (PRAC-004)', () => {
    saveDraftToStorage('p_1', createOrUpdateDraft(null, 'p_1', 'q_1', 'A', 5));
    vi.spyOn(storage, 'setItem').mockImplementation(() => {
      throw new AppError(10001, 'Storage key forbidden');
    });

    const first = getOrCreateSubmitKey('p_1');
    const second = getOrCreateSubmitKey('p_1');

    expect(first).toBe(second);
  });
});
