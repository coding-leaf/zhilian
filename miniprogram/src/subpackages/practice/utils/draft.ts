/**
 * ZhiLian Mini-Program Practice Draft Utilities
 * Reference: docs/sdlc/ZL-134/spec.md
 * Zero-Emoji Policy enforced.
 */

import { storage } from '../../../utils/storage';
import type { PracticeDraftItem, PracticeDraftRecord, UnansweredCheckResult } from '../types/draft';

/**
 * 格式化累计作答耗时秒数为人类可读字符串
 * 规则：不足 1 小时输出 mm:ss，超过 1 小时输出 hh:mm:ss
 */
export function formatDurationSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return '00:00';
  }
  const total = Math.floor(seconds);
  const hrs = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;

  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);

  if (hrs > 0) {
    return `${pad(hrs)}:${pad(mins)}:${pad(secs)}`;
  }
  return `${pad(mins)}:${pad(secs)}`;
}

export const formatElapsedDuration = formatDurationSeconds;

/**
 * 校验指定作答内容是否已有效填写
 */
export function isAnswerFilled(answer: unknown): boolean {
  if (answer === null || answer === undefined) {
    return false;
  }
  if (typeof answer === 'string') {
    return answer.trim().length > 0;
  }
  if (Array.isArray(answer)) {
    const validItems = answer.filter((item) => typeof item === 'string' && item.trim().length > 0);
    return validItems.length > 0;
  }
  if (typeof answer === 'object' && 'user_answer' in (answer as Record<string, unknown>)) {
    return isAnswerFilled((answer as Record<string, unknown>).user_answer);
  }
  return false;
}

/**
 * 计算与盘点全部题目的作答情况与未答题目清单 (1-based index)
 */
export function checkUnansweredQuestions(
  questionIds: string[],
  answers: Record<string, unknown>,
): UnansweredCheckResult {
  const total = questionIds.length;
  let answeredCount = 0;
  const unansweredIndices: number[] = [];

  for (let i = 0; i < total; i++) {
    const qid = questionIds[i];
    const ans = answers[qid];
    if (isAnswerFilled(ans)) {
      answeredCount += 1;
    } else {
      unansweredIndices.push(i + 1);
    }
  }

  return {
    total,
    answeredCount,
    unansweredCount: total - answeredCount,
    unansweredIndices,
  };
}

export const calculateQuestionStats = checkUnansweredQuestions;

/**
 * 创建或不可变更新单题本地草稿记录
 */
export function createOrUpdateDraft(
  existing: PracticeDraftRecord | null,
  practiceId: string,
  questionId: string,
  answer: string | string[],
  duration: number,
): PracticeDraftRecord {
  const baseItems = existing?.items ? { ...existing.items } : {};
  const baseAnswers = existing?.answers ? { ...existing.answers } : {};
  const prevItem = baseItems[questionId];
  const safeDuration = Number.isFinite(duration) && duration > 0 ? duration : 0;
  const timeSpent = (prevItem?.time_spent_seconds ?? 0) + safeDuration;

  const now = Date.now();
  const normalizedAnswer = Array.isArray(answer) ? [...answer] : answer;
  baseItems[questionId] = {
    question_id: questionId,
    user_answer: normalizedAnswer,
    time_spent_seconds: timeSpent,
    sync_status: 'pending',
    updated_at: now,
  };
  baseAnswers[questionId] = normalizedAnswer;

  return {
    practice_id: practiceId,
    items: baseItems,
    answers: baseAnswers,
    updated_at: now,
    ...(existing?.submit_key ? { submit_key: existing.submit_key } : {}),
  };
}

/**
 * 将作答压入待同步队列
 */
export function enqueueUnsyncedAnswer(
  draftRecord: PracticeDraftRecord,
  questionId: string,
  answer: string | string[],
  duration: number,
): PracticeDraftRecord {
  return createOrUpdateDraft(draftRecord, draftRecord.practice_id, questionId, answer, duration);
}

/**
 * 标记特定题目在远端已同步成功
 */
export function markDraftSynced(
  existing: PracticeDraftRecord | null,
  questionIds: string[],
): PracticeDraftRecord {
  if (!existing) {
    return {
      practice_id: '',
      items: {},
      answers: {},
      updated_at: Date.now(),
    };
  }

  const updatedItems = { ...existing.items };
  for (const qid of questionIds) {
    if (updatedItems[qid]) {
      updatedItems[qid] = {
        ...updatedItems[qid],
        sync_status: 'synced',
        updated_at: Date.now(),
      };
    }
  }

  return {
    ...existing,
    items: updatedItems,
    updated_at: Date.now(),
  };
}

/**
 * 提取所有待同步或曾同步失败的草稿条目
 */
export function extractPendingSyncItems(draft: PracticeDraftRecord | null): PracticeDraftItem[] {
  if (!draft || !draft.items) {
    return [];
  }
  return Object.values(draft.items).filter(
    (item) => item.sync_status === 'pending' || item.sync_status === 'failed',
  );
}

/**
 * 将整场练习草稿保存到 Storage (key: practice_drafts)
 * 严格限制字段，绝对禁止存入题目全文。
 *
 * Storage 写入失败（如超出 20KB 上限或序列化异常）时降级为静默忽略，
 * 保证 store 内已作答状态与远端同步调度不受影响 (PRAC-004)。
 */
export function saveDraftToStorage(practiceId: string, draft: PracticeDraftRecord): void {
  try {
    const currentMap = storage.getItem('practice_drafts') ?? {};
    const nextMap: Record<string, PracticeDraftRecord> = {
      ...currentMap,
      [practiceId]: draft,
    };
    storage.setItem('practice_drafts', nextMap);
  } catch (error: unknown) {
    console.warn('[practice] draft storage write degraded', error);
  }
}

/**
 * 从 Storage 加载整场练习草稿
 */
export function loadDraftFromStorage(practiceId: string): PracticeDraftRecord | null {
  const currentMap = storage.getItem('practice_drafts');
  if (!currentMap || !currentMap[practiceId]) {
    return null;
  }
  return currentMap[practiceId];
}

/**
 * 从 Storage 清除指定练习草稿
 *
 * 写入失败时降级为静默忽略，避免交卷成功后清理草稿失败阻断跳转 (PRAC-004)。
 */
export function clearDraftFromStorage(practiceId: string): void {
  try {
    const currentMap = storage.getItem('practice_drafts');
    if (!currentMap || !currentMap[practiceId]) {
      return;
    }
    const nextMap = { ...currentMap };
    delete nextMap[practiceId];
    storage.setItem('practice_drafts', nextMap);
  } catch (error: unknown) {
    console.warn('[practice] draft storage clear degraded', error);
  }
}

/**
 * 生成强幂等键 (UUIDv4)
 * 用于交卷防重复提交
 */
export function generateIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
