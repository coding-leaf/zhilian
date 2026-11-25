import type {
  KnowledgePointDetail,
  KnowledgeSnippet,
  KnowledgeStructuredContent,
  KnowledgeTreeNode,
  KnowledgeTreeResult,
  PointSourceListResult,
  StudyGuideComparison,
  StudyGuideContent,
  StudyGuideDerivationStep,
  StudyGuidePitfall,
  StudyGuidePrewarmResult,
  StudyGuidePrewarmStatus,
  StudyGuidePrewarmStatusResult,
  StudyGuideResult,
  StudyGuideStatus,
  StudyGuideSymbol,
  StudyGuideWorkedExample,
} from '@/types'

interface WireKnowledgeStructuredContent {
  core_summary?: unknown
  key_takeaways?: unknown
  key_formulas?: unknown
  derivation_steps?: unknown
  boundary_notes?: unknown
  common_mistakes?: unknown
}

export interface WireKnowledgeTreeNode {
  id: string
  material_id?: string
  version_id?: string
  parent_id?: string | null
  name: string
  description?: string | null
  structured_content?: WireKnowledgeStructuredContent | null
  sort_order?: number | null
  level?: number
  is_low_confidence?: boolean
  has_study_guide?: boolean
  children?: WireKnowledgeTreeNode[] | null
}

export interface WireKnowledgeTreeResult {
  material_id: string
  version_id: string
  nodes?: WireKnowledgeTreeNode[] | null
}

export interface WireKnowledgePointDetail {
  id: string
  material_id?: string
  version_id?: string
  parent_id?: string | null
  name: string
  description?: string | null
  structured_content?: WireKnowledgeStructuredContent | null
  sort_order?: number | null
  level?: number
  is_low_confidence?: boolean
  has_study_guide?: boolean
  batch_id?: string
  created_at?: string
  updated_at?: string
}

export interface WireStudyGuideSymbol {
  symbol?: unknown
  meaning?: unknown
  note?: unknown
}

export interface WireStudyGuideDerivationStep {
  step_title?: unknown
  formula?: unknown
  explanation?: unknown
}

export interface WireStudyGuideWorkedExample {
  title?: unknown
  question_type?: unknown
  problem?: unknown
  solution_idea?: unknown
  solution_steps?: unknown
  final_answer?: unknown
}

export interface WireStudyGuideComparison {
  target_concept?: unknown
  similarities?: unknown
  differences?: unknown
  exam_distinction?: unknown
}

export interface WireStudyGuidePitfall {
  mistake?: unknown
  why_wrong?: unknown
  correction?: unknown
}

export interface WireStudyGuideContent {
  schema_version?: unknown
  exam_positioning?: unknown
  core_definition?: unknown
  symbol_table?: unknown
  key_formulas?: unknown
  derivation_steps?: unknown
  worked_examples?: unknown
  comparisons?: unknown
  pitfalls?: unknown
  memory_anchors?: unknown
}

export interface WireStudyGuideResponse {
  knowledge_point_id: string
  status?: unknown
  study_guide?: WireStudyGuideContent | null
  generated_at?: string | null
}

export interface WireStudyGuidePrewarmResponse {
  material_id: string
  version_id?: string | null
  status?: unknown
  total_kps?: unknown
  ready_kps?: unknown
}

export interface WireStudyGuideStatusResponse {
  material_id: string
  version_id?: string | null
  status?: unknown
  total_kps?: unknown
  ready_kps?: unknown
  failed_kps?: unknown
  current_kp_name?: unknown
}

function normalizeString(raw: unknown): string {
  return typeof raw === 'string' ? raw.trim() : ''
}

function normalizeNonNegInt(raw: unknown): number {
  return typeof raw === 'number' && Number.isFinite(raw) && raw >= 0 ? Math.floor(raw) : 0
}

function normalizeStringArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function adaptStructuredContent(raw: unknown): KnowledgeStructuredContent | null {
  if (!raw || typeof raw !== 'object') return null
  const record = raw as WireKnowledgeStructuredContent
  return {
    core_summary: normalizeString(record.core_summary),
    key_takeaways: normalizeStringArray(record.key_takeaways),
    key_formulas: normalizeStringArray(record.key_formulas),
    derivation_steps: normalizeStringArray(record.derivation_steps),
    boundary_notes: normalizeStringArray(record.boundary_notes),
    common_mistakes: normalizeStringArray(record.common_mistakes),
  }
}

export function adaptKnowledgeTreeNode(node: WireKnowledgeTreeNode): KnowledgeTreeNode {
  return {
    id: node.id,
    material_id: node.material_id ?? '',
    version_id: node.version_id ?? '',
    parent_id: node.parent_id ?? null,
    name: node.name,
    description: node.description ?? null,
    structured_content: adaptStructuredContent(node.structured_content),
    sort_order: typeof node.sort_order === 'number' ? node.sort_order : 0,
    level: node.level ?? 1,
    is_low_confidence: Boolean(node.is_low_confidence),
    hasStudyGuide: Boolean(node.has_study_guide),
    children: (node.children ?? []).map(adaptKnowledgeTreeNode),
  }
}

export function adaptKnowledgeTree(result: WireKnowledgeTreeResult): KnowledgeTreeResult {
  return {
    material_id: result.material_id,
    version_id: result.version_id,
    nodes: (result.nodes ?? []).map(adaptKnowledgeTreeNode),
  }
}

export function adaptKnowledgePointDetail(detail: WireKnowledgePointDetail): KnowledgePointDetail {
  return {
    id: detail.id,
    material_id: detail.material_id ?? '',
    version_id: detail.version_id ?? '',
    parent_id: detail.parent_id ?? null,
    name: detail.name,
    description: detail.description ?? null,
    structured_content: adaptStructuredContent(detail.structured_content),
    sort_order: typeof detail.sort_order === 'number' ? detail.sort_order : 0,
    level: detail.level ?? 1,
    is_low_confidence: Boolean(detail.is_low_confidence),
    hasStudyGuide: Boolean(detail.has_study_guide),
    batch_id: detail.batch_id,
    created_at: detail.created_at ?? '',
    updated_at: detail.updated_at,
  }
}

function adaptSymbolTable(raw: unknown): StudyGuideSymbol[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is WireStudyGuideSymbol => Boolean(item && typeof item === 'object'))
    .map((item) => ({
      symbol: normalizeString(item.symbol),
      meaning: normalizeString(item.meaning),
      note: normalizeString(item.note),
    }))
    .filter((item) => Boolean(item.symbol || item.meaning))
}

function adaptDerivationSteps(raw: unknown): StudyGuideDerivationStep[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is WireStudyGuideDerivationStep => Boolean(item && typeof item === 'object'))
    .map((item) => ({
      step_title: normalizeString(item.step_title),
      formula: normalizeString(item.formula),
      explanation: normalizeString(item.explanation),
    }))
    .filter((item) => Boolean(item.step_title || item.formula || item.explanation))
}

function adaptWorkedExamples(raw: unknown): StudyGuideWorkedExample[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is WireStudyGuideWorkedExample => Boolean(item && typeof item === 'object'))
    .map((item) => ({
      title: normalizeString(item.title),
      question_type: normalizeString(item.question_type),
      problem: normalizeString(item.problem),
      solution_idea: normalizeString(item.solution_idea),
      solution_steps: normalizeStringArray(item.solution_steps),
      final_answer: normalizeString(item.final_answer),
    }))
    .filter((item) => Boolean(item.problem || item.title))
}

function adaptComparisons(raw: unknown): StudyGuideComparison[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is WireStudyGuideComparison => Boolean(item && typeof item === 'object'))
    .map((item) => ({
      target_concept: normalizeString(item.target_concept),
      similarities: normalizeString(item.similarities),
      differences: normalizeString(item.differences),
      exam_distinction: normalizeString(item.exam_distinction),
    }))
    .filter((item) => Boolean(item.target_concept || item.differences))
}

function adaptPitfalls(raw: unknown): StudyGuidePitfall[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is WireStudyGuidePitfall => Boolean(item && typeof item === 'object'))
    .map((item) => ({
      mistake: normalizeString(item.mistake),
      why_wrong: normalizeString(item.why_wrong),
      correction: normalizeString(item.correction),
    }))
    .filter((item) => Boolean(item.mistake || item.correction))
}

/** 考前精讲内容结构归一化：兼容部分字段缺失，确保各板块数组安全可遍历。 */
export function adaptStudyGuideContent(raw: unknown): StudyGuideContent | null {
  if (!raw || typeof raw !== 'object') return null
  const record = raw as WireStudyGuideContent
  return {
    schema_version:
      typeof record.schema_version === 'number' && Number.isFinite(record.schema_version)
        ? record.schema_version
        : 1,
    exam_positioning: normalizeString(record.exam_positioning),
    core_definition: normalizeString(record.core_definition),
    symbol_table: adaptSymbolTable(record.symbol_table),
    key_formulas: normalizeStringArray(record.key_formulas),
    derivation_steps: adaptDerivationSteps(record.derivation_steps),
    worked_examples: adaptWorkedExamples(record.worked_examples),
    comparisons: adaptComparisons(record.comparisons),
    pitfalls: adaptPitfalls(record.pitfalls),
    memory_anchors: normalizeStringArray(record.memory_anchors),
  }
}

export function adaptStudyGuideResult(raw: WireStudyGuideResponse): StudyGuideResult {
  const studyGuide = adaptStudyGuideContent(raw.study_guide)
  const rawStatus = normalizeString(raw.status)
  let status: StudyGuideStatus = 'empty'
  if (rawStatus === 'ready' || rawStatus === 'generating' || rawStatus === 'empty') {
    status = rawStatus
  } else if (studyGuide) {
    status = 'ready'
  }
  const generatedAt = normalizeString(raw.generated_at)
  return {
    knowledge_point_id: raw.knowledge_point_id,
    status,
    study_guide: studyGuide,
    generated_at: generatedAt || null,
  }
}

export function adaptStudyGuidePrewarmResult(
  raw: WireStudyGuidePrewarmResponse,
): StudyGuidePrewarmResult {
  const rawStatus = normalizeString(raw.status)
  const status: StudyGuidePrewarmResult['status'] =
    rawStatus === 'running' || rawStatus === 'completed' ? rawStatus : 'queued'
  return {
    material_id: raw.material_id,
    version_id: normalizeString(raw.version_id),
    status,
    total_kps: normalizeNonNegInt(raw.total_kps),
    ready_kps: normalizeNonNegInt(raw.ready_kps),
  }
}

export function adaptStudyGuidePrewarmStatus(
  raw: WireStudyGuideStatusResponse,
): StudyGuidePrewarmStatusResult {
  const rawStatus = normalizeString(raw.status)
  const validStatuses: StudyGuidePrewarmStatus[] = [
    'idle',
    'queued',
    'running',
    'completed',
    'partial_failed',
  ]
  const status: StudyGuidePrewarmStatus = validStatuses.includes(rawStatus as StudyGuidePrewarmStatus)
    ? (rawStatus as StudyGuidePrewarmStatus)
    : 'idle'
  const currentKpName = normalizeString(raw.current_kp_name)
  return {
    material_id: raw.material_id,
    version_id: normalizeString(raw.version_id),
    status,
    total_kps: normalizeNonNegInt(raw.total_kps),
    ready_kps: normalizeNonNegInt(raw.ready_kps),
    failed_kps: normalizeNonNegInt(raw.failed_kps),
    current_kp_name: currentKpName || null,
  }
}

export interface WireKnowledgeSnippet {
  id: string
  material_id?: string
  version_id?: string
  page_index?: number | null
  page_end?: number | null
  snippet_index?: number
  chapter_title?: string | null
  content?: string | null
  char_length?: number
}

export interface WirePointSourceList {
  knowledge_point_id: string
  snippets?: WireKnowledgeSnippet[] | null
}

/**
 * 原文溯源切片归一化：对齐后端 `SnippetSourceResponse`（1-based `page_index` 与可选 `page_end`）。
 * 缺失或非法页码安全回退为 1，避免出现第 0 页或 undefined。
 */
export function adaptKnowledgeSnippet(snippet: WireKnowledgeSnippet): KnowledgeSnippet {
  const rawPage = snippet.page_index
  const pageIndex = typeof rawPage === 'number' && Number.isFinite(rawPage) && rawPage >= 1
    ? Math.floor(rawPage)
    : 1
  const rawPageEnd = snippet.page_end
  const parsedPageEnd = typeof rawPageEnd === 'number' && Number.isFinite(rawPageEnd) && rawPageEnd >= 1
    ? Math.floor(rawPageEnd)
    : null
  const pageEnd = parsedPageEnd !== null && parsedPageEnd > pageIndex ? parsedPageEnd : null
  const chapterTitle = typeof snippet.chapter_title === 'string' && snippet.chapter_title.trim()
    ? snippet.chapter_title.trim()
    : null

  return {
    id: snippet.id,
    material_id: snippet.material_id,
    version_id: snippet.version_id,
    page_index: pageIndex,
    pageEnd,
    snippet_index: snippet.snippet_index,
    chapter_title: chapterTitle,
    content: snippet.content ?? '',
    char_length: snippet.char_length,
  }
}

export function adaptPointSourceList(result: WirePointSourceList): PointSourceListResult {
  return {
    knowledge_point_id: result.knowledge_point_id,
    snippets: (result.snippets ?? []).map(adaptKnowledgeSnippet),
  }
}
