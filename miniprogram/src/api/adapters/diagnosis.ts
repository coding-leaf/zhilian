import type { DiagnosisReport, WeakKnowledgeItem } from '@/types'

/** 后端 DiagnosisReportResponse 的 weak_knowledge_points 条目 wire 形状。 */
export interface WireWeakKnowledgeItem {
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
