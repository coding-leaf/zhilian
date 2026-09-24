import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useUserStore } from '@/stores/userStore';
import { storage } from '@/utils/storage';
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
});
