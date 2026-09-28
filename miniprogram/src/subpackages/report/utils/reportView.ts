import type {
  AttemptResult,
  DiagnosisReport,
  GradingStatus,
  PracticeSession,
  QuestionType,
} from '@/types'
import { questionTypeLabel } from '@/api'
import { weakPointId, weakPointName } from '@/api/adapters/diagnosis'

export function formatAnswer(value: unknown): string {
  if (value === undefined || value === null || value === '') return '未作答'
  if (Array.isArray(value)) return value.length ? value.join('、') : '未作答'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function formatScore(score: number | null, maxScore: number): string {
  if (score === null) return `—/${maxScore}`
  return `${score}/${maxScore}`
}

export function formatPercent(rate: number): string {
  return `${Math.round(rate * 100)}%`
}

export interface ResultBadge {
  text: string
  tone: 'correct' | 'wrong' | 'pending' | 'unanswered'
}

/** 待判 / 待重判 / 未作答的题目不得显示为零分或答错。 */
export function resolveResultBadge(result: AttemptResult): ResultBadge {
  if (!result.isAnswered) return { text: '未作答', tone: 'unanswered' }
  if (result.gradingStatus === 'grading') return { text: '判题中', tone: 'pending' }
  if (result.gradingStatus === 'pending_regrade') return { text: '待重判', tone: 'pending' }
  if (result.isCorrect === null) return { text: '判题中', tone: 'pending' }
  return result.isCorrect
    ? { text: `正确 ${formatScore(result.score, result.maxScore)}`, tone: 'correct' }
    : { text: `错误 ${formatScore(result.score, result.maxScore)}`, tone: 'wrong' }
}

export function resolveGradingStatusText(status: GradingStatus | 'grading'): string {
  switch (status) {
    case 'graded': return '已判分'
    case 'pending_regrade': return '待重判'
    case 'unanswered': return '未作答'
    default: return '判题中'
  }
}

export function typeLabel(type: QuestionType | string): string {
  return questionTypeLabel(type)
}

/** 错题再生用的考点 ID：优先诊断报告薄弱点，其次逐题结果。 */
export function collectWrongKnowledgePointIds(
  report: DiagnosisReport | null,
  results: AttemptResult[],
): string[] {
  const ids = new Set<string>()
  for (const point of report?.weak_knowledge_points || []) {
    const id = weakPointId(point)
    if (id) ids.add(id)
  }
  if (ids.size === 0) {
    for (const result of results) {
      if (result.isCorrect === false && result.knowledgePointId) ids.add(result.knowledgePointId)
    }
  }
  return Array.from(ids)
}

export interface WeakPointView {
  id?: string
  name: string
  masteryRate: number
  reason: string
  suggestion: string
}

export function buildWeakPointViews(report: DiagnosisReport | null): WeakPointView[] {
  return (report?.weak_knowledge_points || []).map((point) => ({
    id: weakPointId(point),
    name: weakPointName(point),
    masteryRate: point.current_score,
    reason: point.cause_explanation || point.cause_type || '暂无归因说明',
    suggestion: point.actionable_advice || '建议针对性复习后再次练习',
  }))
}

/** 再生题范围来自练习详情本身，不再让页面猜测归属。 */
export function resolveSessionScope(session: PracticeSession | null) {
  return {
    folderId: session?.folder_id || undefined,
    materialId: session?.folder_id ? undefined : session?.material_id || undefined,
  }
}

export function isSelectableForRegrade(result: AttemptResult): boolean {
  return Boolean(result.attemptItemId) && result.isAnswered
}

export type GradingMode = 'regrade' | 'self-evaluate'
