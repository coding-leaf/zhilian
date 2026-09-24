/**
 * 用户管理与画像 API 网络接口模块。
 *
 * 封装用户资料查询、用户画像更新及账号注销请求。
 * 严格遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { request } from '../utils/request';
import type { ApiResponse } from '../types/common';
import type {
  UserProfileResponse,
  UpdateUserProfilePayload,
  UserActionResponse,
} from '../types/auth';

/**
 * 获取当前登录用户的个人画像资料。
 *
 * @returns 统一响应包，包含用户 ID、昵称、头像及创建时间。
 */
export function fetchUserProfile(): Promise<ApiResponse<UserProfileResponse>> {
  return request<UserProfileResponse>({
    url: '/api/v1/users/me',
    method: 'GET',
  });
}

/**
 * 更新当前登录用户的个人画像资料。
 *
 * @param payload 包含待更新的昵称或头像地址。
 * @returns 统一响应包，包含更新后的最新画像资料。
 */
export function updateUserProfile(
  payload: UpdateUserProfilePayload,
): Promise<ApiResponse<UserProfileResponse>> {
  return request<UserProfileResponse>({
    url: '/api/v1/users/me',
    method: 'PUT',
    data: payload,
  });
}

/**
 * 注销当前登录用户的账号（软删除并作废全端凭据）。
 *
 * @returns 统一响应包，包含注销成功提示信息。
 */
export function deleteAccount(): Promise<ApiResponse<UserActionResponse>> {
  return request<UserActionResponse>({
    url: '/api/v1/users/me',
    method: 'DELETE',
  });
}
