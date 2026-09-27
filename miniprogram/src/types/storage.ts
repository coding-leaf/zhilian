/**
 * ZhiLian Mini-Program Storage Whitelist Contracts
 * Strictly restricts allowed storage keys to three categories.
 */

import type { TokenPairResponse } from './auth';
import type { PracticeDraftRecord } from '../subpackages/practice/types/draft';

export const KEY_WHITELIST = ['auth_tokens', 'practice_drafts', 'user_settings'] as const;

export type StorageKey = (typeof KEY_WHITELIST)[number];

export interface UserSettings {
  theme?: 'light';
  sound_enabled?: boolean;
  font_scale?: number;
}

export interface StorageDataMap {
  auth_tokens: TokenPairResponse;
  practice_drafts: Record<string, PracticeDraftRecord>;
  user_settings: UserSettings;
}
