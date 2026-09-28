import type { QuestionType, WrongRecordGroup, WrongRecordItem } from '@/types'
import { adaptQuestion, type WireQuestion } from './question'

/** 后端 WrongRecordItemResponse 的 wire 形状（含 question_snapshot 字典）。 */
export interface WireWrongRecordItem {
  id: string
  folder_id?: string | null
  material_id?: string | null
  practice_id: string
  attempt_item_id: string
  question_id?: string | null
  knowledge_point_id?: string | null
  error_type?: string
  is_mastered?: boolean
  wrong_count?: number
  created_at?: string | null
  updated_at?: string | null
  user_answer?: string | null
  question_snapshot?: (WireQuestion & { stem?: string }) | null
}

/** 错题题干只来自后端下发的 question_snapshot，禁止读不存在的 question.stem。 */
export function wrongSnapshotStem(item: WrongRecordItem): string {
  const stem = item.question_snapshot?.stem
  return typeof stem === 'string' && stem.trim() ? stem : '题干快照缺失'
}

export function wrongSnapshotType(item: WrongRecordItem): QuestionType | undefined {
  return item.question_snapshot?.question_type
}

export function wrongSnapshotOptions(item: WrongRecordItem) {
  const snapshot = item.question_snapshot
  if (!snapshot) return []
  return adaptQuestion({
    question_type: (snapshot.question_type || 'short_answer') as QuestionType,
    stem: snapshot.stem || '',
    options: snapshot.options,
    answer: snapshot.answer,
    analysis: snapshot.analysis,
  }).options || []
}

/**
 * 错题分组选项：一个完整课程，或一份未分类资料。
 * 统计口径来自后端 groups（覆盖完整错题本，而非当前分页第一页）。
 */
export interface WrongGroupOption {
  key: string
  label: string
  folderId?: string
  materialId?: string
  count: number
  unclassified: boolean
}

export function buildWrongGroupOptions(groups: WrongRecordGroup[]): WrongGroupOption[] {
  return (groups || []).map((group) => {
    const folderId = group.folder_id ?? undefined
    const materialId = group.material_id ?? undefined
    if (folderId) {
      return {
        key: `folder:${folderId}`,
        label: group.folder_name || '未命名课程',
        folderId,
        count: group.count,
        unclassified: false,
      }
    }
    return {
      key: materialId ? `material:${materialId}` : 'unclassified',
      label: group.material_title || '未分类资料',
      materialId,
      count: group.count,
      unclassified: true,
    }
  })
}

/** 该分组的错题记录（客户端按 folder_id/material_id 精确匹配）。 */
export function recordsInGroup(
  items: WrongRecordItem[],
  option: WrongGroupOption,
): WrongRecordItem[] {
  return items.filter((item) => {
    if (option.folderId) return item.folder_id === option.folderId
    if (option.materialId) {
      return !item.folder_id && item.material_id === option.materialId
    }
    return !item.folder_id && !item.material_id
  })
}

export interface WrongRegenerateScope {
  folderId?: string
  materialId?: string
}

/**
 * 由错题分组解析再生题范围：必须且只能落到一个课程或一个未分类资料。
 * 跨课程错题不得混成错误归属的单课程练习。
 */
export function resolveRegenerateScope(
  option: WrongGroupOption | null,
): WrongRegenerateScope | null {
  if (!option) return null
  if (option.folderId) return { folderId: option.folderId }
  if (option.materialId) return { materialId: option.materialId }
  return null
}

export function collectUnmasteredKnowledgePointIds(items: WrongRecordItem[]): string[] {
  const ids = new Set<string>()
  for (const item of items) {
    if (!item.is_mastered && item.knowledge_point_id) ids.add(item.knowledge_point_id)
  }
  return Array.from(ids)
}
