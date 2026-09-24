/**
 * ZhiLian Mini-Program Test Setup
 * Global mock stubs for uni runtime environment
 */

import { vi } from 'vitest';

// Global Uni-app Lifecycle Mocks
vi.mock('@dcloudio/uni-app', () => ({
  onLaunch: vi.fn((fn: () => void) => fn && fn()),
  onShow: vi.fn((fn: () => void) => fn && fn()),
  onHide: vi.fn((fn: () => void) => fn && fn()),
  onLoad: vi.fn((fn: () => void) => fn && fn()),
  onReady: vi.fn((fn: () => void) => fn && fn()),
  onUnload: vi.fn((fn: () => void) => fn && fn()),
  onPullDownRefresh: vi.fn((fn: () => void) => fn && fn()),
  onReachBottom: vi.fn((fn: () => void) => fn && fn()),
}));

// Basic Uni mock stub
(globalThis as unknown as { uni: Record<string, unknown> }).uni = {
  getStorageSync: () => null,
  setStorageSync: () => {},
  removeStorageSync: () => {},
  clearStorageSync: () => {},
  request: () => Promise.resolve({ statusCode: 200, data: {} }),
  showToast: () => {},
  showModal: () => {},
  reLaunch: () => {},
  navigateTo: () => {},
  switchTab: () => {},
  redirectTo: () => {},
  navigateBack: () => {},
  stopPullDownRefresh: () => {},
};
