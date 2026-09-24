/**
 * ZhiLian Mini-Program Authentication Data Contracts
 * Defines login requests, dual-token pairs, and user profile structures.
 */

export interface WechatLoginRequest {
  code: string;
  nickname?: string;
  avatar_url?: string;
}

export interface TokenPairResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  expires_at?: number;
}

export type AuthTokens = TokenPairResponse;

export interface UserProfileResponse {
  id: string;
  nickname: string;
  avatar_url: string;
  created_at?: string;
}

export interface UpdateUserProfilePayload {
  nickname?: string;
  avatar_url?: string;
}

export interface UserActionResponse {
  success: boolean;
  message: string;
}
