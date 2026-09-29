import type { PracticeStatus, PracticeSummary, WrongRecordItem } from '@/types'
import {
  collectUnmasteredKnowledgePointIds,
  isManualWrongRecord,
  type WrongGroupOption,
} from '@/api/adapters/wrong'

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

/**
 * 题库题目行「记入错题 / 取消标记」的动作分道。
 *
 * | 记录来源 | 判据 | 动作 |
 * | --- | --- | --- |
 * | 无记录 | `record == null` | `mark` 记入错题 |
 * | 手工 | `practice_id == null` | `delete` 取消标记（删记录） |
 * | 判题 | `practice_id` 非空且未掌握 | `master` 引导「已掌握」，**不删** |
 * | 判题且已掌握 | 同上且 `is_mastered` | `none` 无动作 |
 *
 * 判题来源的记录是真实作答历史，删掉它会让「已消灭错题」等统计失去依据；
 * 「已掌握」正是为该处境设计的语义。
 */
export type WrongMarkAction = 'mark' | 'delete' | 'master' | 'none'

export function resolveWrongMarkAction(record: WrongRecordItem | null): WrongMarkAction {
  if (!record) return 'mark'
  if (isManualWrongRecord(record)) return 'delete'
  if (!record.is_mastered) return 'master'
  return 'none'
}

/** 题目行动作位的文案，按分道结果穷尽取值（新增动作必须在这里显式表态）。 */
export function wrongMarkLabel(record: WrongRecordItem | null): string {
  switch (resolveWrongMarkAction(record)) {
    case 'mark':
      return '记入错题'
    case 'delete':
      return '取消标记'
    case 'master':
      return '已标记'
    case 'none':
      return '已掌握'
  }
}
