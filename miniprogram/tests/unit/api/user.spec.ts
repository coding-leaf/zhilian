import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as requestModule from '@/utils/request';
import { fetchUserProfile, updateUserProfile, deleteAccount } from '@/api/user';

describe('User API Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('should call fetchUserProfile with GET /api/v1/users/me', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'user_uuid_001',
        nickname: 'Alice',
        avatar_url: 'https://example.com/avatar.png',
        created_at: '2026-01-01T00:00:00Z',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchUserProfile();

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/users/me',
      method: 'GET',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call updateUserProfile with PUT /api/v1/users/me and payload', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'user_uuid_001',
        nickname: 'Alice Updated',
        avatar_url: 'https://example.com/avatar2.png',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const payload = { nickname: 'Alice Updated', avatar_url: 'https://example.com/avatar2.png' };
    const res = await updateUserProfile(payload);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/users/me',
      method: 'PUT',
      data: payload,
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call deleteAccount with DELETE /api/v1/users/me', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: { success: true, message: '账号已成功注销' },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await deleteAccount();

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/users/me',
      method: 'DELETE',
    });
    expect(res).toEqual(mockResponse);
  });
});
