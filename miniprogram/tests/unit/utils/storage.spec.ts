import { describe, it, expect, beforeEach } from 'vitest';
import { storage, KEY_WHITELIST } from '@/utils/storage';
import { AppError } from '@/utils/error';
import type { TokenPairResponse } from '@/types/auth';
import type { StorageKey } from '@/types/storage';

describe('Storage Whitelist Manager', () => {
  const memoryStore: Record<string, unknown> = {};

  beforeEach(() => {
    Object.keys(memoryStore).forEach((k) => delete memoryStore[k]);

    // Mock uni storage functions
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
  });

  it('should enforce the strict 3-key whitelist', () => {
    expect(KEY_WHITELIST).toEqual(['auth_tokens', 'practice_drafts', 'user_settings']);
  });

  it('should successfully set and get whitelisted items', () => {
    const tokens: TokenPairResponse = {
      access_token: 'acc-12345',
      refresh_token: 'ref-67890',
      token_type: 'Bearer',
      expires_in: 7200,
    };

    storage.setItem('auth_tokens', tokens);
    const retrieved = storage.getItem('auth_tokens');
    expect(retrieved).toEqual(tokens);

    storage.setItem('user_settings', {
      theme: 'light',
      sound_enabled: true,
      font_scale: 1.0,
    });
    expect(storage.getItem('user_settings')?.sound_enabled).toBe(true);

    storage.setItem('practice_drafts', {
      p1: { practice_id: 'p1', answers: { q1: 'A' }, updated_at: 1000 },
    });
    expect(storage.getItem('practice_drafts')?.p1.answers).toEqual({ q1: 'A' });
  });

  it('should return null when reading uninitialized or invalid keys', () => {
    expect(storage.getItem('auth_tokens')).toBeNull();
    expect(storage.getItem('unknown_key' as StorageKey)).toBeNull();
  });

  it('should throw AppError(10001, "Storage key forbidden") on unauthorized key write', () => {
    expect(() => {
      storage.setItem('forbidden_key' as StorageKey, {} as never);
    }).toThrowError(AppError);

    try {
      storage.setItem('forbidden_key' as StorageKey, {} as never);
    } catch (err) {
      const appErr = err as AppError;
      expect(appErr.code).toBe(10001);
      expect(appErr.message).toBe('Storage key forbidden');
    }
  });

  it('should throw AppError(10001, "Storage key forbidden") when payload exceeds 20KB', () => {
    const hugeString = 'x'.repeat(21 * 1024); // 21KB
    const invalidPayload = {
      access_token: hugeString,
      refresh_token: 'token',
      token_type: 'Bearer',
      expires_in: 7200,
    };

    expect(() => {
      storage.setItem('auth_tokens', invalidPayload);
    }).toThrow(AppError);

    try {
      storage.setItem('auth_tokens', invalidPayload);
    } catch (err) {
      const appErr = err as AppError;
      expect(appErr.code).toBe(10001);
      expect(appErr.message).toBe('Storage key forbidden');
    }
  });

  it('should throw AppError(10001, "Storage key forbidden") when multibyte payload exceeds 20KB in UTF-8 bytes', () => {
    const multibyte = '\u4e2d'.repeat(8000); // 8000 CJK chars -> ~24KB in UTF-8, <= 20480 UTF-16 units
    expect(multibyte.length).toBeLessThanOrEqual(20 * 1024);

    const payload = {
      access_token: multibyte,
      refresh_token: 'token',
      token_type: 'Bearer',
      expires_in: 7200,
    };

    expect(() => {
      storage.setItem('auth_tokens', payload);
    }).toThrow(AppError);

    try {
      storage.setItem('auth_tokens', payload);
    } catch (err) {
      const appErr = err as AppError;
      expect(appErr.code).toBe(10001);
      expect(appErr.message).toBe('Storage key forbidden');
    }
  });

  it('should reject objects containing sensitive full-text keys', () => {
    const leakAttempt = {
      theme: 'light',
      material_content: 'Sensitive full material text',
    };

    expect(() => {
      storage.setItem('user_settings', leakAttempt as never);
    }).toThrow(AppError);

    const questionLeakAttempt = {
      p1: {
        practice_id: 'p1',
        answers: {},
        updated_at: Date.now(),
        question_text: 'What is HTTP?',
      },
    };

    expect(() => {
      storage.setItem('practice_drafts', questionLeakAttempt as never);
    }).toThrow(AppError);
  });

  it('should remove specific item without affecting others', () => {
    storage.setItem('auth_tokens', {
      access_token: 'a',
      refresh_token: 'r',
      token_type: 'Bearer',
      expires_in: 7200,
    });
    storage.setItem('user_settings', { theme: 'light' });

    storage.removeItem('auth_tokens');
    expect(storage.getItem('auth_tokens')).toBeNull();
    expect(storage.getItem('user_settings')).toEqual({ theme: 'light' });
  });

  it('should only clear whitelisted keys leaving host keys intact', () => {
    // Simulate host storage key
    memoryStore['wx_app_version'] = '1.0.0';

    storage.setItem('auth_tokens', {
      access_token: 'a',
      refresh_token: 'r',
      token_type: 'Bearer',
      expires_in: 7200,
    });
    storage.setItem('user_settings', { theme: 'light' });

    storage.clear();

    expect(storage.getItem('auth_tokens')).toBeNull();
    expect(storage.getItem('user_settings')).toBeNull();
    // Non-whitelisted host keys remain
    expect(memoryStore['wx_app_version']).toBe('1.0.0');
  });
});
