import type {
  DiagnosisReport,
  KnowledgeMasteryLevel,
  KnowledgeMasterySummary,
  UserMasteryOverview,
  WeakKnowledgeItem,
} from '@/types'

/** 后端 DiagnosisReportResponse 的 weak_knowledge_points 条目 wire 形状。 */
interface WireWeakKnowledgeItem {
  knowledge_point_id?: string | null
  knowledge_name?: string | null
  knowledge_id?: string | null
  knowledge_title?: string | null
  current_score?: number
  previous_score?: number | null
  score_delta?: number
  priority?: number | string | null
  cause_type?: string | null
  cause_explanation?: string | null
  actionable_advice?: string | null
  associated_mistakes?: Array<{ question_id: string; is_negation_inversion: boolean }>
}

export interface WireDiagnosisReport {
  id: string
  practice_id: string
  mastery_before?: number | null
  mastery_after?: number | null
  knowledge_evaluations?: DiagnosisReport['knowledge_evaluations']
  weak_knowledge_points?: WireWeakKnowledgeItem[]
  regressed_knowledge_points?: WireWeakKnowledgeItem[]
  analysis_causes?: DiagnosisReport['analysis_causes']
  actionable_suggestions?: DiagnosisReport['actionable_suggestions']
  root_causes?: string[]
  suggestions?: string[]
  summary?: string | null
  unanswered_count?: number
  wrong_count?: number
  pending_regrade_count?: number
  total_questions?: number
  score_rate?: number
  is_structure_degraded?: boolean
  created_at?: string | null
}

function adaptWeakItem(item: WireWeakKnowledgeItem): WeakKnowledgeItem {
  return {
    knowledge_point_id: item.knowledge_point_id ?? item.knowledge_id ?? null,
    knowledge_id: item.knowledge_id ?? item.knowledge_point_id ?? null,
    knowledge_name: item.knowledge_name ?? item.knowledge_title ?? null,
    knowledge_title: item.knowledge_title ?? item.knowledge_name ?? null,
    current_score: item.current_score ?? 0,
    previous_score: item.previous_score ?? null,
    score_delta: item.score_delta ?? 0,
    priority: item.priority ?? null,
    cause_type: item.cause_type ?? null,
    cause_explanation: item.cause_explanation ?? null,
    actionable_advice: item.actionable_advice ?? null,
    associated_mistakes: item.associated_mistakes ?? [],
  }
}

/**
 * 诊断报告归一化：只消费后端真实字段，缺失的可选聚合字段补安全默认值。
 * 禁止再假定 score / accuracy / details / weaknesses 等不存在的字段。
 */
export function adaptDiagnosisReport(report: WireDiagnosisReport): DiagnosisReport {
  return {
    id: report.id,
    practice_id: report.practice_id,
    mastery_before: report.mastery_before ?? null,
    mastery_after: report.mastery_after ?? null,
    knowledge_evaluations: report.knowledge_evaluations ?? [],
    weak_knowledge_points: (report.weak_knowledge_points ?? []).map(adaptWeakItem),
    regressed_knowledge_points: (report.regressed_knowledge_points ?? []).map(adaptWeakItem),
    analysis_causes: report.analysis_causes ?? [],
    actionable_suggestions: report.actionable_suggestions ?? [],
    root_causes: report.root_causes ?? [],
    suggestions: report.suggestions ?? [],
    summary: report.summary ?? null,
    unanswered_count: report.unanswered_count ?? 0,
    wrong_count: report.wrong_count ?? 0,
    pending_regrade_count: report.pending_regrade_count ?? 0,
    total_questions: report.total_questions ?? 0,
    score_rate: report.score_rate ?? 0,
    is_structure_degraded: report.is_structure_degraded ?? false,
    created_at: report.created_at ?? null,
  }
}

export function weakPointName(item: WeakKnowledgeItem): string {
  return item.knowledge_name || item.knowledge_title || '未命名考点'
}

export function weakPointId(item: WeakKnowledgeItem): string | undefined {
  return item.knowledge_point_id ?? item.knowledge_id ?? undefined
}

export interface WireKnowledgeMasterySummary {
  knowledge_point_id: string
  knowledge_name?: string | null
  mastery_score?: number | null
  level?: string | null
  practice_count?: number | null
  correct_count?: number | null
  last_practiced_at?: string | null
}

export interface WireUserMasteryOverview {
  material_id?: string | null
  total_points?: number | null
  total_knowledge_points?: number | null
  mastered_count?: number | null
  proficient_count?: number | null
  learning_count?: number | null
  basic_count?: number | null
  weak_count?: number | null
  unlearned_count?: number | null
  overall_score?: number | null
  overall_mastery_score?: number | null
  points?: WireKnowledgeMasterySummary[] | null
  weak_knowledge_points?: WireKnowledgeMasterySummary[] | null
  weak_points?: WireKnowledgeMasterySummary[] | null
}

const MASTERY_LEVELS: KnowledgeMasteryLevel[] = ['unlearned', 'weak', 'basic', 'proficient']

function normalizeMasteryLevel(raw: string | null | undefined): KnowledgeMasteryLevel {
  const lower = String(raw ?? '').toLowerCase()
  if ((MASTERY_LEVELS as string[]).includes(lower)) {
    return lower as KnowledgeMasteryLevel
  }
  return 'unlearned'
}

export function adaptMasterySummary(item: WireKnowledgeMasterySummary): KnowledgeMasterySummary {
  return {
    knowledge_point_id: item.knowledge_point_id,
    knowledge_name: item.knowledge_name || '未命名考点',
    mastery_score: typeof item.mastery_score === 'number' ? item.mastery_score : 0,
    level: normalizeMasteryLevel(item.level),
    practice_count: Math.max(0, item.practice_count ?? 0),
    correct_count: Math.max(0, item.correct_count ?? 0),
    last_practiced_at: item.last_practiced_at ?? null,
  }
}

export function adaptMasteryOverview(raw: WireUserMasteryOverview): UserMasteryOverview {
  const points = (raw.points ?? []).map(adaptMasterySummary)
  const rawWeak = raw.weak_knowledge_points ?? raw.weak_points ?? []
  const weakList = rawWeak.map(adaptMasterySummary)
  const totalPoints = Math.max(0, raw.total_points ?? raw.total_knowledge_points ?? points.length)
  const masteredCount = Math.max(0, raw.mastered_count ?? raw.proficient_count ?? 0)
  const learningCount = Math.max(0, raw.learning_count ?? raw.basic_count ?? 0)
  const weakCount = Math.max(0, raw.weak_count ?? 0)
  const unlearnedCount = Math.max(
    0,
    raw.unlearned_count ?? Math.max(0, totalPoints - masteredCount - learningCount - weakCount),
  )
  const overallScore =
    typeof raw.overall_score === 'number'
      ? raw.overall_score
      : typeof raw.overall_mastery_score === 'number'
        ? raw.overall_mastery_score
        : 0

  return {
    material_id: raw.material_id ?? null,
    total_points: totalPoints,
    total_knowledge_points: totalPoints,
    mastered_count: masteredCount,
    proficient_count: masteredCount,
    learning_count: learningCount,
    basic_count: learningCount,
    weak_count: weakCount,
    unlearned_count: unlearnedCount,
    overall_score: overallScore,
    overall_mastery_score: overallScore,
    points,
    weak_knowledge_points: weakList,
    weak_points: weakList,
  }
}
