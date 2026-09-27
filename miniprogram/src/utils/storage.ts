/**
 * ZhiLian Mini-Program Storage Whitelist Manager
 * Strictly enforces a 3-key storage whitelist and prevents sensitive content leakage.
 */

import { AppError } from './error';
import { KEY_WHITELIST, type StorageKey, type StorageDataMap } from '../types/storage';

export { KEY_WHITELIST, type StorageKey, type StorageDataMap };

const MAX_STORAGE_BYTES = 20 * 1024; // 20KB threshold

const FORBIDDEN_CONTENT_KEYS = [
  'material_content',
  'raw_text',
  'full_content',
  'question_text',
  'reference_answer',
  'snippets',
];

/**
 * Calculates the real UTF-8 encoded byte length of a string.
 *
 * Uses the standard TextEncoder when available (UniApp/modern runtimes) and
 * falls back to a manual code-point walk on runtimes without it.
 */
function calculateUtf8Bytes(value: string): number {
  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(value).length;
  }

  let bytes = 0;
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code < 0x80) {
      bytes += 1;
    } else if (code < 0x800) {
      bytes += 2;
    } else if (code >= 0xd800 && code <= 0xdbff) {
      // High surrogate of a surrogate pair -> 4 bytes UTF-8
      bytes += 4;
      i++;
    } else {
      bytes += 3;
    }
  }
  return bytes;
}

/**
 * Recursively scans an object for forbidden content keys to prevent storage leakage.
 */
function containsForbiddenContent(target: unknown): boolean {
  if (!target || typeof target !== 'object') {
    return false;
  }

  if (Array.isArray(target)) {
    return target.some((item) => containsForbiddenContent(item));
  }

  const obj = target as Record<string, unknown>;
  for (const key of Object.keys(obj)) {
    if (FORBIDDEN_CONTENT_KEYS.includes(key)) {
      return true;
    }
    const val = obj[key];
    if (val && typeof val === 'object') {
      if (containsForbiddenContent(val)) {
        return true;
      }
    }
  }

  return false;
}

/**
 * Validates storage key and payload size/content safety.
 *
 * @throws AppError(10001, 'Storage key forbidden') if validation fails.
 */
export function validateStoragePayload(key: string, value: unknown): void {
  // 1. Whitelist key check
  if (!KEY_WHITELIST.includes(key as StorageKey)) {
    throw new AppError(10001, 'Storage key forbidden');
  }

  // 2. Payload serialization and size check
  let serialized = '';
  if (typeof value === 'string') {
    serialized = value;
  } else {
    try {
      serialized = JSON.stringify(value) ?? '';
    } catch {
      throw new AppError(10001, 'Storage key forbidden');
    }
  }

  if (calculateUtf8Bytes(serialized) > MAX_STORAGE_BYTES) {
    throw new AppError(10001, 'Storage key forbidden');
  }

  // 3. Sensitive content leak detection
  if (containsForbiddenContent(value)) {
    throw new AppError(10001, 'Storage key forbidden');
  }
}

/**
 * Safely writes data to local storage under whitelist control.
 */
export function setItem<K extends StorageKey>(key: K, value: StorageDataMap[K]): void {
  validateStoragePayload(key, value);
  uni.setStorageSync(key, value);
}

/**
 * Reads whitelisted data from local storage.
 */
export function getItem<K extends StorageKey>(key: K): StorageDataMap[K] | null {
  if (!KEY_WHITELIST.includes(key as StorageKey)) {
    return null;
  }
  const data = uni.getStorageSync(key);
  if (data === undefined || data === null || data === '') {
    return null;
  }
  return data as StorageDataMap[K];
}

/**
 * Removes a specific key from local storage.
 */
export function removeItem(key: StorageKey): void {
  uni.removeStorageSync(key);
}

/**
 * Clears only the whitelisted storage keys without wiping host application data.
 */
export function clear(): void {
  KEY_WHITELIST.forEach((k) => {
    uni.removeStorageSync(k);
  });
}

export const clearWhitelistStorage = clear;

export const storage = {
  getItem,
  setItem,
  removeItem,
  clear,
  clearWhitelistStorage,
};

export default storage;
