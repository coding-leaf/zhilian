import type { PracticeStatus, PracticeSummary, WrongRecordItem } from '@/types'
import { collectUnmasteredKnowledgePointIds, type WrongGroupOption } from '@/api/adapters/wrong'

const RESUMEABLE: PracticeStatus[] = ['not_started', 'in_progress', 'paused']

export function isResumeable(practice: PracticeSummary): boolean {
  return RESUMEABLE.includes(practice.status)
}

export function practiceStatusText(practice: PracticeSummary): string {
  switch (practice.status) {
    case 'not_started': return '未开始'
    case 'in_progress': return '作答中'
    case 'paused': return '已暂停'
    case 'submitted': return '判题中'
    case 'partially_graded': return '待重判'
    case 'completed': return '已完成'
    case 'timeout': return '已超时'
    default: return '进行中'
  }
}

export function practiceActionText(practice: PracticeSummary): string {
  return isResumeable(practice) ? '继续作答' : '查看结果'
}

export function practiceQuestionLabel(practice: PracticeSummary): string {
  const count = practice.question_count || practice.total_count || 0
  return `${count} 题`
}

/** 单个分组内所有未攻克错题的考点集合。 */
export function groupKnowledgePointIds(
  records: WrongRecordItem[],
  option: WrongGroupOption | null,
): string[] {
  if (!option) return []
  const unmastered = records.filter((record) => !record.is_mastered)
  return collectUnmasteredKnowledgePointIds(unmastered)
}

export function groupCounts(records: WrongRecordItem[]) {
  const mastered = records.filter((record) => record.is_mastered).length
  return { mastered, pending: records.length - mastered }
}

/** 单条错题的再生范围：优先课程归属，其次未分类资料归属。 */
export function recordRegenerateScope(record: WrongRecordItem): {
  folderId?: string
  materialId?: string
} {
  if (record.folder_id) return { folderId: record.folder_id }
  if (record.material_id) return { materialId: record.material_id }
  return {}
}

export function hasScope(scope: { folderId?: string; materialId?: string }): boolean {
  return Boolean(scope.folderId || scope.materialId)
}
