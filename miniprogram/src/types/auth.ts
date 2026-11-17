export interface UserProfile {
  id: string
  nickname: string
  avatar_url?: string
  phone?: string
  created_at?: string
  updated_at?: string
}

export interface UpdateUserProfilePayload {
  nickname?: string
  avatar_url?: string
}

export interface LoginResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in?: number
  user?: UserProfile
}
