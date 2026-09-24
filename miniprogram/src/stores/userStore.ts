/**
 * User Store
 * Manages user authentication tokens and profile information.
 * Enforces pure state mutation without direct network API calls.
 */

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { TokenPairResponse, UserProfileResponse } from '../types/auth';
import { storage } from '../utils/storage';

export const useUserStore = defineStore('user', () => {
  // State
  const tokens = ref<TokenPairResponse | null>(null);
  const profile = ref<UserProfileResponse | null>(null);

  // Getters
  const isAuthenticated = computed(() => !!tokens.value?.access_token);
  const isLoggedIn = computed(() => isAuthenticated.value);
  const userId = computed(() => profile.value?.id ?? null);
  const nickname = computed(() => profile.value?.nickname ?? '');
  const hasValidToken = computed(() => isAuthenticated.value);

  // Actions
  function setTokens(newTokens: TokenPairResponse | null): void {
    tokens.value = newTokens;
    if (newTokens) {
      storage.setItem('auth_tokens', newTokens);
    } else {
      storage.removeItem('auth_tokens');
    }
  }

  function clearTokens(): void {
    tokens.value = null;
    storage.removeItem('auth_tokens');
  }

  function setProfile(newProfile: UserProfileResponse | null): void {
    profile.value = newProfile;
  }

  function setUserProfile(newProfile: UserProfileResponse | null): void {
    setProfile(newProfile);
  }

  function clearProfile(): void {
    profile.value = null;
  }

  function initFromStorage(): void {
    const saved = storage.getItem('auth_tokens');
    if (saved) {
      tokens.value = saved;
    }
  }

  function logout(): void {
    clearTokens();
    clearProfile();
  }

  return {
    tokens,
    profile,
    isAuthenticated,
    isLoggedIn,
    userId,
    nickname,
    hasValidToken,
    setTokens,
    clearTokens,
    setProfile,
    setUserProfile,
    clearProfile,
    initFromStorage,
    logout,
  };
});

export default useUserStore;
