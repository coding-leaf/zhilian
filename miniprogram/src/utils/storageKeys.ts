/** 集中管理本地持久化存储键与键构造器，避免裸字符串散落各层。 */
export const STORAGE_KEYS = {
  ACCESS_TOKEN: 'access_token',
  REFRESH_TOKEN: 'refresh_token',
} as const

export const ACCESS_TOKEN_KEY = STORAGE_KEYS.ACCESS_TOKEN
export const REFRESH_TOKEN_KEY = STORAGE_KEYS.REFRESH_TOKEN

/** 按用户 + 练习隔离的本地草稿键，避免切换账号后串数据。 */
export function practiceDraftStorageKey(
  userId: string | undefined | null,
  practiceId: string,
): string {
  return `practice_draft_${userId || 'anonymous'}_${practiceId}`
}

/** 练习交卷幂等键存储位置。 */
export function practiceSubmitStorageKey(practiceId: string): string {
  return `practice_submit_key_${practiceId}`
}
