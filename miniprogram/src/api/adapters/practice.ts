import type {
  AttemptResult,
  GradingStatus,
  PracticeItem,
  PracticeSession,
} from '@/types'
import { adaptQuestion, isSubjectiveType, type WireQuestion } from './question'

/** 后端 PracticeDetailResponse.items[] 的 wire 形状。 */
export type WirePracticeItem = Omit<PracticeItem, 'question_snapshot'> & {
  question_snapshot: WireQuestion
}

/** 后端 PracticeDetailResponse 的 wire 形状。 */
export interface WirePracticeDetail {
  id?: string | null
  practice_id?: string | null
  title: string
  material_id?: string | null
  folder_id?: string | null
  mode?: string
  status: string
  total_count: number
  completed_count?: number
  total_score?: number | null
  max_score?: number | null
  source_type?: string
  source_report_id?: string | null
  completed_at?: string | null
  submitted_at?: string | null
  created_at?: string
  items: WirePracticeItem[]
}

/**
 * 练习详情归一化：把 items[].question_snapshot 投影为统一卷面模型。
 * 新建练习与续练共用此入口，页面/Store 只消费归一化结果。
 */
export function adaptPractice(session: WirePracticeDetail): PracticeSession {
  const practiceId = session.id || session.practice_id
  if (!practiceId) throw new Error('练习详情缺少练习标识')
  const items: PracticeItem[] = (session.items || []).map((item) => ({
    ...item,
    grading_status: (item.grading_status ?? null) as GradingStatus | null,
    question_snapshot: adaptQuestion({
      ...item.question_snapshot,
      id: item.question_id || item.question_snapshot.id || '',
    }),
  }))

  return {
    ...session,
    id: practiceId,
    practice_id: session.practice_id || practiceId,
    status: session.status as PracticeSession['status'],
    questions: items.map((item) => ({
      ...item.question_snapshot,
      id: item.question_id || item.question_snapshot.id,
    })),
    items,
    user_answers: Object.fromEntries(
      items
        .filter((item) => item.question_id && item.is_answered)
        .map((item) => [item.question_id as string, item.user_answer]),
    ),
  }
}

function resolveGradingStatus(item: PracticeItem): GradingStatus | 'grading' {
  if (!item.is_answered) return 'unanswered'
  if (item.grading_status === 'pending_regrade') return 'pending_regrade'
  if (item.grading_status === 'graded') return 'graded'
  if (typeof item.score === 'number') return 'graded'
  return 'grading'
}

/**
 * 把练习详情投影为结果页/报告页逐题视图。
 * 未判项（判题中 / 待重判 / 未作答）不参与「答错」判定，也不显示为零分。
 */
export function buildAttemptResults(session: PracticeSession | null): AttemptResult[] {
  if (!session?.items?.length) return []
  return session.items.map((item, index) => {
    const snapshot = item.question_snapshot
    const gradingStatus = resolveGradingStatus(item)
    const isGraded = gradingStatus === 'graded' && typeof item.score === 'number'
    const maxScore = typeof item.max_score === 'number' ? item.max_score : 1
    const score = typeof item.score === 'number' ? item.score : null
    const isCorrect = isGraded && score !== null ? score >= maxScore : null

    return {
      attemptItemId: item.attempt_item_id,
      questionId: item.question_id || snapshot.id,
      knowledgePointId: snapshot.knowledge_point_id,
      orderIndex: item.order_index ?? index + 1,
      type: snapshot.type,
      stem: snapshot.stem,
      options: snapshot.options || [],
      userAnswer: item.user_answer,
      correctAnswer: snapshot.answer ?? null,
      isAnswered: Boolean(item.is_answered),
      gradingStatus,
      isPending: gradingStatus === 'grading' || gradingStatus === 'pending_regrade',
      score,
      maxScore,
      isCorrect,
      hitKeywords: item.hit_keywords || [],
      missingKeywords: item.missing_keywords || [],
      gradingPoints: snapshot.grading_points || [],
      analysis: snapshot.analysis || snapshot.explanation,
      sourceQuote: item.source_snippet?.snippet_content || snapshot.source_quote,
    }
  })
}

/** 卷面进度统计：已判 / 判题中 / 待重判 / 未作答。 */
export interface PracticeProgress {
  total: number
  graded: number
  grading: number
  pendingRegrade: number
  unanswered: number
  fullyGraded: boolean
}

export function summarizeProgress(session: PracticeSession | null): PracticeProgress {
  const results = buildAttemptResults(session)
  const graded = results.filter((r) => r.gradingStatus === 'graded').length
  const grading = results.filter((r) => r.gradingStatus === 'grading').length
  const pendingRegrade = results.filter((r) => r.gradingStatus === 'pending_regrade').length
  const unanswered = results.filter((r) => !r.isAnswered).length
  const completedAt = Boolean(session?.completed_at)
  return {
    total: results.length,
    graded,
    grading,
    pendingRegrade,
    unanswered,
    fullyGraded: completedAt && grading === 0 && pendingRegrade === 0 && results.length > 0,
  }
}

/** 主观题标签（复查 / 自评入口条件）。 */
export function canGradeManually(result: AttemptResult): boolean {
  return isSubjectiveType(result.type) && Boolean(result.attemptItemId)
}

/**
 * 判题是否需要用户主动重试。
 *
 * 后端 `partially_graded` 表示「本轮判题已结束但仍有未判定题目」，成因有二：
 * 主观题 LLM 超时/降级为待重判，或判题任务终态失败被后端回写为待重判。
 * 两种情况都由 `POST /practices/{id}/regrade` 主动重试恢复；`submitted`
 * 仍处于判题进行中，不提供重试入口以避免重复派发。
 */
export function needsGradingRetry(session: PracticeSession | null): boolean {
  return session?.status === 'partially_graded'
}
