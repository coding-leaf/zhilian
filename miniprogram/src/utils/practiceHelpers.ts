import { MAX_PRACTICE_QUESTIONS } from '@/types'
import { practiceDraftStorageKey, practiceSubmitStorageKey } from './storageKeys'

/** 判断作答值是否有效非空（练习进度与答题卡统一口径）。 */
export function isAnswered(value: unknown): boolean {
  if (value === undefined || value === null || value === '') return false
  if (Array.isArray(value) && value.length === 0) return false
  return true
}

export function randomSubmitKey(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function readPracticeDraft(
  userId: string,
  practiceId: string,
): Record<string, unknown> | null {
  const localDraft = uni.getStorageSync(practiceDraftStorageKey(userId, practiceId))
  if (localDraft && typeof localDraft === 'object') {
    return { ...(localDraft as Record<string, unknown>) }
  }
  return null
}

export function writePracticeDraft(
  userId: string,
  practiceId: string,
  answers: Record<string, unknown>,
): void {
  uni.setStorageSync(practiceDraftStorageKey(userId, practiceId), answers)
}

export function getOrCreatePracticeSubmitKey(practiceId: string): string {
  const storageKey = practiceSubmitStorageKey(practiceId)
  const existing = uni.getStorageSync(storageKey)
  const submitKey = existing || randomSubmitKey()
  uni.setStorageSync(storageKey, submitKey)
  return submitKey
}

export function clearPracticeStorage(userId: string, practiceId: string): void {
  uni.removeStorageSync(practiceDraftStorageKey(userId, practiceId))
  uni.removeStorageSync(practiceSubmitStorageKey(practiceId))
}

export function clampPracticeQuestionIds(questionIds: string[]): string[] {
  return questionIds.slice(0, MAX_PRACTICE_QUESTIONS)
}

export function validateWrongRegenerateInput(
  knowledgePointIds: string[],
  scope: { folderId?: string; materialId?: string },
): void {
  if (!knowledgePointIds || knowledgePointIds.length === 0) {
    throw new Error('未提供错题知识点')
  }
  if (!scope?.folderId && !scope?.materialId) {
    throw new Error('缺少课程或资料范围，无法再生题')
  }
  if (scope.folderId && scope.materialId) {
    throw new Error('再生题范围只能指定一个课程或一份资料')
  }
}
