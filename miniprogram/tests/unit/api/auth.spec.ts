import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as requestModule from '@/utils/request';
import { loginByWechat, refreshToken, revokeTokens } from '@/api/auth';

describe('Auth API Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('should call loginByWechat with POST /api/v1/auth/login and skipAuth', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        access_token: 'acc_token_123',
        refresh_token: 'ref_token_123',
        token_type: 'Bearer',
        expires_in: 7200,
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload = { code: 'wechat_code_001', nickname: 'Tester' };
    const res = await loginByWechat(payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/auth/login',
      method: 'POST',
      data: payload,
      skipAuth: true,
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call refreshToken with POST /api/v1/auth/refresh and skipAuth', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        access_token: 'new_acc_token',
        refresh_token: 'new_ref_token',
        token_type: 'Bearer',
        expires_in: 7200,
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await refreshToken('old_ref_token');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/auth/refresh',
      method: 'POST',
      data: { refresh_token: 'old_ref_token' },
      skipAuth: true,
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call revokeTokens with POST /api/v1/auth/revoke', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: { success: true, message: '已成功注销所有登录凭据' },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await revokeTokens();

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/auth/revoke',
      method: 'POST',
    });
    expect(res).toEqual(mockResponse);
  });
});
