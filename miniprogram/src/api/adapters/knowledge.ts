import type {
  KnowledgePointDetail,
  KnowledgeSnippet,
  KnowledgeStructuredContent,
  KnowledgeTreeNode,
  KnowledgeTreeResult,
  PointSourceListResult,
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
  batch_id?: string
  created_at?: string
  updated_at?: string
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
    core_summary: typeof record.core_summary === 'string' ? record.core_summary.trim() : '',
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
    batch_id: detail.batch_id,
    created_at: detail.created_at ?? '',
    updated_at: detail.updated_at,
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
