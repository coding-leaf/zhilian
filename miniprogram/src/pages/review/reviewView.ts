import type {
  KnowledgeMasteryLevel,
  KnowledgeMasterySummary,
  PracticeStatus,
  PracticeSummary,
  UserMasteryOverview,
  WrongRecordItem,
} from '@/types'
import {
  collectUnmasteredKnowledgePointIds,
  isManualWrongRecord,
  wrongSnapshotKnowledgePointName,
  type WrongGroupOption,
} from '@/api/adapters/wrong'

export type ReviewSegment = 'mastery' | 'wrong' | 'practices' | 'bank'

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

export function practiceActionButtonText(practice: PracticeSummary): string {
  if (isResumeable(practice)) return '继续作答'
  if (practice.status === 'completed') return '查看解析报告'
  return '查看结果'
}

export function practiceQuestionLabel(practice: PracticeSummary): string {
  const count = practice.question_count || practice.total_count || 0
  return `${count} 题`
}

export function practiceAccuracyBadge(practice: PracticeSummary): string {
  if (typeof practice.score_rate === 'number') {
    return `正确率 ${Math.round(Math.max(0, Math.min(1, practice.score_rate)) * 100)}%`
  }
  if (
    typeof practice.total_score === 'number'
    && typeof practice.max_score === 'number'
    && practice.max_score > 0
  ) {
    const pct = Math.round((practice.total_score / practice.max_score) * 100)
    return `${practice.total_score}/${practice.max_score} · ${pct}%`
  }
  return ''
}

export function formatShortDateTime(iso?: string | null): string {
  if (!iso) return '近期'
  const datePart = iso.slice(0, 10)
  const timeMatch = /[T\s](\d{2}:\d{2})/.exec(iso)
  return timeMatch ? `${datePart} ${timeMatch[1]}` : datePart
}

const MASTERY_PRIORITY: Record<KnowledgeMasteryLevel, number> = {
  weak: 0,
  basic: 1,
  unlearned: 2,
  proficient: 3,
}

export function masteryLevelLabel(level: KnowledgeMasteryLevel | string): string {
  switch (level) {
    case 'weak': return '薄弱'
    case 'basic': return '基本掌握'
    case 'unlearned': return '未练'
    case 'proficient': return '熟练'
    default: return '未练'
  }
}

export function sortMasteryPoints(points: KnowledgeMasterySummary[]): KnowledgeMasterySummary[] {
  return [...points].sort((a, b) => {
    const pA = MASTERY_PRIORITY[a.level] ?? 9
    const pB = MASTERY_PRIORITY[b.level] ?? 9
    if (pA !== pB) return pA - pB
    if (a.mastery_score !== b.mastery_score) return a.mastery_score - b.mastery_score
    return a.knowledge_point_id.localeCompare(b.knowledge_point_id)
  })
}

export function mergeMasteryPoints(overview: UserMasteryOverview | null): KnowledgeMasterySummary[] {
  if (!overview) return []
  const byId = new Map<string, KnowledgeMasterySummary>()
  const sources = [
    ...(overview.points || []),
    ...(overview.weak_knowledge_points || []),
    ...(overview.weak_points || []),
  ]
  for (const point of sources) {
    if (!point.knowledge_point_id) continue
    const existing = byId.get(point.knowledge_point_id)
    if (!existing || point.practice_count > existing.practice_count) {
      byId.set(point.knowledge_point_id, point)
    }
  }
  return sortMasteryPoints(Array.from(byId.values()))
}

export function computePracticedPointCount(overview: UserMasteryOverview | null): number {
  if (!overview) return 0
  return Math.max(0, overview.total_knowledge_points - overview.unlearned_count)
}

export function formatMasteryPercent(score: number): string {
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`
}

export function formatPointAccuracy(point: KnowledgeMasterySummary): string {
  if (point.practice_count <= 0) return '暂无作答'
  const pct = Math.round((point.correct_count / point.practice_count) * 100)
  return `正确率 ${pct}% (${point.correct_count}/${point.practice_count})`
}

/** 错题卡片考点标签：优先真实知识点名，缺失时兜底「综合考点」，绝不复读题型名。 */
export function wrongKnowledgePointLabel(record: WrongRecordItem): string {
  return wrongSnapshotKnowledgePointName(record) || '综合考点'
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
