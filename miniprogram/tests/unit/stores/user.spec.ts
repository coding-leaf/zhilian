import { describe, it, expect, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useUserStore } from '@/stores/userStore';
import { storage } from '@/utils/storage';
import { request, _resetStateForTesting } from '@/utils/request';
import * as userApi from '@/api/user';
import { AppError } from '@/utils/error';
import type { TokenPairResponse, UserProfileResponse } from '@/types/auth';

describe('UserStore', () => {
  const memoryStore: Record<string, unknown> = {};

  beforeEach(() => {
    setActivePinia(createPinia());
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
  });

  const mockTokens: TokenPairResponse = {
    access_token: 'mock-access-token-12345',
    refresh_token: 'mock-refresh-token-67890',
    token_type: 'Bearer',
    expires_in: 7200,
  };

  const mockProfile: UserProfileResponse = {
    id: 'user-001',
    nickname: 'TestUser',
    avatar_url: 'https://example.com/avatar.png',
  };

  it('should initialize with null state and unauthenticated getter', () => {
    const store = useUserStore();
    expect(store.tokens).toBeNull();
    expect(store.profile).toBeNull();
    expect(store.isAuthenticated).toBe(false);
    expect(store.userId).toBeNull();
  });

  it('should set tokens and synchronize to storage', () => {
    const store = useUserStore();
    store.setTokens(mockTokens);

    expect(store.tokens).toEqual(mockTokens);
    expect(store.isAuthenticated).toBe(true);

    const storedTokens = storage.getItem('auth_tokens');
    expect(storedTokens).toEqual(mockTokens);
  });

  it('should clear tokens and remove from storage', () => {
    const store = useUserStore();
    store.setTokens(mockTokens);
    expect(store.isAuthenticated).toBe(true);

    store.clearTokens();
    expect(store.tokens).toBeNull();
    expect(store.isAuthenticated).toBe(false);
    expect(storage.getItem('auth_tokens')).toBeNull();
  });

  it('should set and clear user profile', () => {
    const store = useUserStore();
    store.setProfile(mockProfile);

    expect(store.profile).toEqual(mockProfile);
    expect(store.userId).toBe('user-001');
    expect(store.nickname).toBe('TestUser');

    store.clearProfile();
    expect(store.profile).toBeNull();
    expect(store.userId).toBeNull();
    expect(store.nickname).toBe('');
  });

  it('should initialize state from storage on initFromStorage', () => {
    storage.setItem('auth_tokens', mockTokens);

    const store = useUserStore();
    store.initFromStorage();

    expect(store.tokens).toEqual(mockTokens);
    expect(store.isAuthenticated).toBe(true);
  });

  it('should logout completely clearing both tokens and profile', () => {
    const store = useUserStore();
    store.setTokens(mockTokens);
    store.setProfile(mockProfile);

    store.logout();

    expect(store.tokens).toBeNull();
    expect(store.profile).toBeNull();
    expect(store.isAuthenticated).toBe(false);
    expect(storage.getItem('auth_tokens')).toBeNull();
  });

  it('should hydrate profile from server when tokens exist', async () => {
    storage.setItem('auth_tokens', mockTokens);
    const fetchSpy = vi.spyOn(userApi, 'fetchUserProfile').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockProfile,
    });

    const store = useUserStore();
    const result = await store.hydrateProfile();

    expect(fetchSpy).toHaveBeenCalled();
    expect(result).toEqual(mockProfile);
    expect(store.profile).toEqual(mockProfile);
    expect(store.nickname).toBe('TestUser');
  });

  it('should return null on hydrateProfile without tokens', async () => {
    const fetchSpy = vi.spyOn(userApi, 'fetchUserProfile');
    const store = useUserStore();
    const result = await store.hydrateProfile();

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result).toBeNull();
    expect(store.profile).toBeNull();
  });

  it('should clear tokens when hydrateProfile encounters 401 unauthorized', async () => {
    storage.setItem('auth_tokens', mockTokens);
    vi.spyOn(userApi, 'fetchUserProfile').mockRejectedValue(
      new AppError(20001, '登录状态已过期，请重新登录', { status_code: 401 }),
    );

    const store = useUserStore();
    store.initFromStorage();
    expect(store.isAuthenticated).toBe(true);

    const result = await store.hydrateProfile();
    expect(result).toBeNull();
    expect(store.tokens).toBeNull();
    expect(store.isAuthenticated).toBe(false);
    expect(store.profile).toBeNull();
  });

  it('should sync in-memory tokens after silent refresh in the request layer', async () => {
    _resetStateForTesting();
    storage.setItem('auth_tokens', mockTokens);

    const store = useUserStore();
    store.initFromStorage();
    expect(store.tokens?.access_token).toBe('mock-access-token-12345');

    uni.request = vi.fn().mockImplementation((opts: UniApp.RequestOptions) => {
      if (opts.url === '/api/v1/auth/refresh') {
        return Promise.resolve({
          statusCode: 200,
          data: {
            code: 0,
            data: {
              access_token: 'refreshed_access_token',
              refresh_token: 'refreshed_refresh_token',
              token_type: 'Bearer',
              expires_in: 7200,
            },
          },
        });
      }

      if (opts.header?.['Authorization'] === 'Bearer mock-access-token-12345') {
        return Promise.resolve({
          statusCode: 401,
          data: { code: 20001, message: 'Expired' },
        });
      }

      return Promise.resolve({
        statusCode: 200,
        data: { code: 0, data: { ok: true } },
      });
    });

    await request({ url: '/api/v1/materials' });

    expect(store.tokens?.access_token).toBe('refreshed_access_token');
    expect(store.tokens?.refresh_token).toBe('refreshed_refresh_token');
    expect(storage.getItem('auth_tokens')?.access_token).toBe('refreshed_access_token');
    expect(store.isAuthenticated).toBe(true);
  });
});
