/**
 * ZhiLian Mini-Program Practice Draft Contracts
 * Reference: docs/sdlc/ZL-134/spec.md
 * Zero-Emoji Policy enforced.
 */

export type DraftSyncStatus = 'pending' | 'syncing' | 'synced' | 'failed';

/**
 * 单题作答草稿条目
 * 严格遵从 Storage 白名单，仅保留核心字段，禁止存入题目全文。
 */
export interface PracticeDraftItem {
  question_id: string;
  user_answer: string | string[];
  time_spent_seconds: number;
  sync_status: DraftSyncStatus;
  updated_at: number;
}

/**
 * 练习会话本地离线草稿包
 * 对应 Storage 白名单 key: practice_drafts 的单场练习记录
 *
 * 规范结构含 `items`；历史仅含 `answers` 的旧条目读取时按缺省空对象兼容。
 */
export interface PracticeDraftRecord {
  practice_id: string;
  items: Record<string, PracticeDraftItem>;
  answers: Record<string, string | string[]>;
  updated_at: number;
  /** Persisted submit idempotency key so retries reuse the same key. */
  submit_key?: string;
  /**
   * Session metadata captured at init so the home page can render the real
   * question total, title and material without guessing (BUG-DIAG-017).
   */
  total_count?: number;
  title?: string;
  material_id?: string;
  folder_id?: string;
}

/**
 * 本地 Storage practice_drafts 结构
 */
export type PracticeDraftStorage = Record<string, PracticeDraftRecord>;

/**
 * 未答题盘点计算结果
 */
export interface UnansweredCheckResult {
  total: number;
  answeredCount: number;
  unansweredCount: number;
  unansweredIndices: number[]; // 1-based 人类可读题目序号
}
