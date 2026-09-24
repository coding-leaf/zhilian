/**
 * 认证与授权 API 网络接口模块。
 *
 * 封装微信小程序登录换凭证、双令牌静默刷新与凭据主动吊销请求。
 * 严格遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { request } from '../utils/request';
import type { ApiResponse } from '../types/common';
import type { WechatLoginRequest, TokenPairResponse, UserActionResponse } from '../types/auth';

/**
 * 微信小程序授权登录换取双令牌。
 *
 * @param payload 包含临时授权码 code 与可选用户画像的登录请求载荷。
 * @returns 统一响应包，携带 access_token 与 refresh_token。
 */
export function loginByWechat(
  payload: WechatLoginRequest,
): Promise<ApiResponse<TokenPairResponse>> {
  return request<TokenPairResponse>({
    url: '/api/v1/auth/login',
    method: 'POST',
    data: payload,
    skipAuth: true,
  });
}

/**
 * 使用长效刷新令牌换取全新双令牌。
 *
 * @param refreshToken 当前持有的长效 refresh_token。
 * @returns 统一响应包，携带新签发的一对双令牌。
 */
export function refreshToken(refreshToken: string): Promise<ApiResponse<TokenPairResponse>> {
  return request<TokenPairResponse>({
    url: '/api/v1/auth/refresh',
    method: 'POST',
    data: { refresh_token: refreshToken },
    skipAuth: true,
  });
}

/**
 * 主动吊销当前用户在全端签发的所有历史凭据。
 *
 * @returns 统一响应包，包含操作执行结果提示。
 */
export function revokeTokens(): Promise<ApiResponse<UserActionResponse>> {
  return request<UserActionResponse>({
    url: '/api/v1/auth/revoke',
    method: 'POST',
  });
}
