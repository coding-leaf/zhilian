import { describe, it, expect, beforeEach, vi } from 'vitest';
import { request, _resetStateForTesting, setTokenRefreshListener } from '@/utils/request';
import { storage } from '@/utils/storage';
import { AppError } from '@/utils/error';
import type { TokenPairResponse } from '@/types/auth';

describe('Unified Network Request Client', () => {
  const memoryStore: Record<string, unknown> = {};

  beforeEach(() => {
    _resetStateForTesting();
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
    uni.reLaunch = vi.fn();
  });

  it('should successfully perform request and attach Bearer token', async () => {
    storage.setItem('auth_tokens', {
      access_token: 'valid_access_token',
      refresh_token: 'valid_refresh_token',
      token_type: 'Bearer',
      expires_in: 7200,
    });

    let capturedHeaders: Record<string, string> = {};
    uni.request = vi.fn().mockImplementation((opts: UniApp.RequestOptions) => {
      capturedHeaders = (opts.header || {}) as Record<string, string>;
      return Promise.resolve({
        statusCode: 200,
        data: { code: 0, message: 'ok', data: { id: 'item-1' } },
      });
    });

    const res = await request<{ id: string }>({
      url: '/api/v1/items',
      method: 'GET',
    });

    expect(res.code).toBe(0);
    expect(res.data).toEqual({ id: 'item-1' });
    expect(capturedHeaders['Authorization']).toBe('Bearer valid_access_token');
    expect(capturedHeaders['Content-Type']).toBe('application/json');
  });

  it('should omit Authorization header when skipAuth is true', async () => {
    storage.setItem('auth_tokens', {
      access_token: 'valid_access_token',
      refresh_token: 'valid_refresh_token',
      token_type: 'Bearer',
      expires_in: 7200,
    });

    let capturedHeaders: Record<string, string> = {};
    uni.request = vi.fn().mockImplementation((opts: UniApp.RequestOptions) => {
      capturedHeaders = (opts.header || {}) as Record<string, string>;
      return Promise.resolve({
        statusCode: 200,
        data: { token: 'public-data' },
      });
    });

    const res = await request({
      url: '/api/v1/public',
      skipAuth: true,
    });

    expect(res.code).toBe(0);
    expect(capturedHeaders['Authorization']).toBeUndefined();
  });

  it('should intercept non-2xx HTTP status and throw AppError', async () => {
    uni.request = vi.fn().mockResolvedValue({
      statusCode: 403,
      data: { code: 20002, message: '无权访问此内容' },
    });

    await expect(request({ url: '/api/v1/secret' })).rejects.toThrow(AppError);

    try {
      await request({ url: '/api/v1/secret' });
    } catch (err) {
      const appErr = err as AppError;
      expect(appErr.code).toBe(20002);
      expect(appErr.message).toBe('无权访问此内容');
      expect(appErr.status_code).toBe(403);
    }
  });

  it('should intercept business error code with HTTP 200 and throw AppError', async () => {
    uni.request = vi.fn().mockResolvedValue({
      statusCode: 200,
      data: { code: 40001, message: '资料清晰度不足或内容过少，请重新拍摄' },
    });

    await expect(request({ url: '/api/v1/materials/parse' })).rejects.toThrow(AppError);

    try {
      await request({ url: '/api/v1/materials/parse' });
    } catch (err) {
      const appErr = err as AppError;
      expect(appErr.code).toBe(40001);
      expect(appErr.message).toBe('资料清晰度不足或内容过少，请重新拍摄');
    }
  });

  it('should catch network failure and throw network AppError', async () => {
    uni.request = vi.fn().mockRejectedValue(new Error('Network disconnected'));

    await expect(request({ url: '/api/v1/items' })).rejects.toThrow(AppError);

    try {
      await request({ url: '/api/v1/items' });
    } catch (err) {
      const appErr = err as AppError;
      expect(appErr.code).toBe(-1);
      expect(appErr.message).toBe('网络连接异常，请检查网络设置');
    }
  });

  it('should reject with 20001 and redirect to login when 401 occurs without refresh_token', async () => {
    uni.request = vi.fn().mockResolvedValue({
      statusCode: 401,
      data: { code: 20001, message: 'Token expired' },
    });

    await expect(request({ url: '/api/v1/user/profile' })).rejects.toThrow(AppError);
    expect(uni.reLaunch).toHaveBeenCalledWith({ url: '/pages/auth/login' });
    expect(storage.getItem('auth_tokens')).toBeNull();
  });

  it('should throw raw backend error on anonymous 401 without redirect or token clear', async () => {
    storage.setItem('auth_tokens', {
      access_token: 'stale_access_token',
      refresh_token: 'stale_refresh_token',
      token_type: 'Bearer',
      expires_in: 7200,
    });

    uni.request = vi.fn().mockResolvedValue({
      statusCode: 401,
      data: { code: 20001, message: '用户账号已被停用' },
    });

    try {
      await request({
        url: '/api/v1/auth/login',
        method: 'POST',
        data: { code: 'dev_code' },
        skipAuth: true,
      });
      throw new Error('Expected request to reject');
    } catch (err) {
      const appErr = err as AppError;
      expect(appErr).toBeInstanceOf(AppError);
      expect(appErr.code).toBe(20001);
      expect(appErr.message).toBe('用户账号已被停用');
      expect(appErr.status_code).toBe(401);
    }

    expect(uni.reLaunch).not.toHaveBeenCalled();
    expect(storage.getItem('auth_tokens')).not.toBeNull();
  });

  it('should surface business 20001 on anonymous endpoint without redirect', async () => {
    storage.setItem('auth_tokens', {
      access_token: 'stale_access_token',
      refresh_token: 'stale_refresh_token',
      token_type: 'Bearer',
      expires_in: 7200,
    });

    uni.request = vi.fn().mockResolvedValue({
      statusCode: 200,
      data: { code: 20001, message: '登录凭证无效，请重新授权' },
    });

    try {
      await request({
        url: '/api/v1/auth/login',
        method: 'POST',
        data: { code: 'dev_code' },
        skipAuth: true,
      });
      throw new Error('Expected request to reject');
    } catch (err) {
      const appErr = err as AppError;
      expect(appErr).toBeInstanceOf(AppError);
      expect(appErr.code).toBe(20001);
      expect(appErr.message).toBe('登录凭证无效，请重新授权');
    }

    expect(uni.reLaunch).not.toHaveBeenCalled();
    expect(storage.getItem('auth_tokens')).not.toBeNull();
  });

  it('should perform silent refresh on 401 and replay failed request', async () => {
    const initialTokens: TokenPairResponse = {
      access_token: 'old_access_token',
      refresh_token: 'valid_refresh_token',
      token_type: 'Bearer',
      expires_in: 7200,
    };
    storage.setItem('auth_tokens', initialTokens);

    let callCount = 0;
    uni.request = vi.fn().mockImplementation((opts: UniApp.RequestOptions) => {
      callCount++;
      if (opts.url === '/api/v1/auth/refresh') {
        return Promise.resolve({
          statusCode: 200,
          data: {
            code: 0,
            data: {
              access_token: 'new_access_token',
              refresh_token: 'new_refresh_token',
              token_type: 'Bearer',
              expires_in: 7200,
            },
          },
        });
      }

      // First call fails with 401; second call with new token succeeds
      if (opts.header?.['Authorization'] === 'Bearer old_access_token') {
        return Promise.resolve({
          statusCode: 401,
          data: { code: 20001, message: 'Token expired' },
        });
      }

      if (opts.header?.['Authorization'] === 'Bearer new_access_token') {
        return Promise.resolve({
          statusCode: 200,
          data: { code: 0, data: { status: 'success' } },
        });
      }

      return Promise.reject(new Error('Unexpected call'));
    });

    const res = await request<{ status: string }>({ url: '/api/v1/practices' });
    expect(res.data).toEqual({ status: 'success' });

    // Assert tokens were refreshed in storage
    const updatedTokens = storage.getItem('auth_tokens');
    expect(updatedTokens?.access_token).toBe('new_access_token');
    expect(updatedTokens?.refresh_token).toBe('new_refresh_token');
    expect(callCount).toBe(3); // 1st try (401), refresh, retry (200)
  });

  it('should notify the registered token refresh listener after silent refresh', async () => {
    const listener = vi.fn();
    setTokenRefreshListener(listener);

    const initialTokens: TokenPairResponse = {
      access_token: 'listener_old_access',
      refresh_token: 'listener_refresh',
      token_type: 'Bearer',
      expires_in: 7200,
    };
    storage.setItem('auth_tokens', initialTokens);

    uni.request = vi.fn().mockImplementation((opts: UniApp.RequestOptions) => {
      if (opts.url === '/api/v1/auth/refresh') {
        return Promise.resolve({
          statusCode: 200,
          data: {
            code: 0,
            data: {
              access_token: 'listener_new_access',
              refresh_token: 'listener_new_refresh',
              token_type: 'Bearer',
              expires_in: 7200,
            },
          },
        });
      }

      if (opts.header?.['Authorization'] === 'Bearer listener_old_access') {
        return Promise.resolve({
          statusCode: 401,
          data: { code: 20001, message: 'Expired' },
        });
      }

      return Promise.resolve({
        statusCode: 200,
        data: { code: 0, data: { status: 'success' } },
      });
    });

    await request({ url: '/api/v1/listener' });

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({ access_token: 'listener_new_access' }),
    );
  });

  it('should break the refresh loop after one retry when replayed request keeps returning 401', async () => {
    const initialTokens: TokenPairResponse = {
      access_token: 'loop_old_access',
      refresh_token: 'loop_refresh',
      token_type: 'Bearer',
      expires_in: 7200,
    };
    storage.setItem('auth_tokens', initialTokens);

    let refreshCallCount = 0;
    uni.request = vi.fn().mockImplementation((opts: UniApp.RequestOptions) => {
      if (opts.url === '/api/v1/auth/refresh') {
        refreshCallCount++;
        return Promise.resolve({
          statusCode: 200,
          data: {
            code: 0,
            data: {
              access_token: 'loop_rotated_access',
              refresh_token: 'loop_rotated_refresh',
              token_type: 'Bearer',
              expires_in: 7200,
            },
          },
        });
      }

      return Promise.resolve({
        statusCode: 401,
        data: { code: 20001, message: 'Unauthorized' },
      });
    });

    await expect(request({ url: '/api/v1/business' })).rejects.toThrow(AppError);

    expect(refreshCallCount).toBe(1);
    expect(storage.getItem('auth_tokens')).toBeNull();
    expect(uni.reLaunch).toHaveBeenCalledWith({ url: '/pages/auth/login' });
  });

  it('should queue concurrent requests during refresh and replay all upon success', async () => {
    const initialTokens: TokenPairResponse = {
      access_token: 'old_token',
      refresh_token: 'refresh_me',
      token_type: 'Bearer',
      expires_in: 7200,
    };
    storage.setItem('auth_tokens', initialTokens);

    let refreshCallCount = 0;
    uni.request = vi.fn().mockImplementation((opts: UniApp.RequestOptions) => {
      if (opts.url === '/api/v1/auth/refresh') {
        refreshCallCount++;
        return new Promise((resolve) => {
          setTimeout(() => {
            resolve({
              statusCode: 200,
              data: {
                access_token: 'brand_new_token',
                refresh_token: 'brand_new_refresh',
                token_type: 'Bearer',
                expires_in: 7200,
              },
            });
          }, 30);
        });
      }

      if (opts.header?.['Authorization'] === 'Bearer old_token') {
        return Promise.resolve({
          statusCode: 401,
          data: { code: 20001, message: 'Expired' },
        });
      }

      if (opts.header?.['Authorization'] === 'Bearer brand_new_token') {
        return Promise.resolve({
          statusCode: 200,
          data: { code: 0, data: { path: opts.url } },
        });
      }

      return Promise.reject(new Error('Unknown'));
    });

    // Fire two requests concurrently
    const [res1, res2] = await Promise.all([
      request<{ path: string }>({ url: '/api/v1/profile' }),
      request<{ path: string }>({ url: '/api/v1/materials' }),
    ]);

    expect(res1.data.path).toBe('/api/v1/profile');
    expect(res2.data.path).toBe('/api/v1/materials');
    expect(refreshCallCount).toBe(1); // Only ONE refresh token request was executed
  });

  it('should clear tokens and reject all queued requests if refresh fails', async () => {
    const initialTokens: TokenPairResponse = {
      access_token: 'bad_token',
      refresh_token: 'expired_refresh',
      token_type: 'Bearer',
      expires_in: 7200,
    };
    storage.setItem('auth_tokens', initialTokens);

    uni.request = vi.fn().mockImplementation((opts: UniApp.RequestOptions) => {
      if (opts.url === '/api/v1/auth/refresh') {
        return Promise.resolve({
          statusCode: 401,
          data: { code: 20001, message: 'Refresh token expired' },
        });
      }

      return Promise.resolve({
        statusCode: 401,
        data: { code: 20001, message: 'Unauthorized' },
      });
    });

    const p1 = request({ url: '/api/v1/r1' });
    const p2 = request({ url: '/api/v1/r2' });

    await expect(p1).rejects.toThrow(AppError);
    await expect(p2).rejects.toThrow(AppError);

    expect(storage.getItem('auth_tokens')).toBeNull();
    expect(uni.reLaunch).toHaveBeenCalledWith({ url: '/pages/auth/login' });
  });
});
