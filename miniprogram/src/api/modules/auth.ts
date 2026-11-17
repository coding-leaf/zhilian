import { request, uploadFile } from '@/utils/request'
import type { LoginResult, UpdateUserProfilePayload, UserProfile } from '@/types'

export function apiLoginByWechat(code: string): Promise<LoginResult> {
  return request<LoginResult>({
    url: '/auth/login',
    method: 'POST',
    data: { code },
  })
}

export function apiGetUserProfile(): Promise<UserProfile> {
  return request<UserProfile>({
    url: '/users/me',
    method: 'GET',
  })
}

export function apiUpdateUserProfile(payload: UpdateUserProfilePayload): Promise<UserProfile> {
  return request<UserProfile>({
    url: '/users/me',
    method: 'PUT',
    data: payload,
  })
}

export function apiUploadAvatar(filePath: string): Promise<UserProfile> {
  return uploadFile<UserProfile>(filePath, 'file', undefined, '/users/me/avatar')
}
