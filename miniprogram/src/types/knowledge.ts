export interface KnowledgeStructuredContent {
  core_summary: string
  key_takeaways: string[]
  key_formulas: string[]
  derivation_steps?: string[]
  boundary_notes: string[]
  common_mistakes?: string[]
}

export interface KnowledgeTreeNode {
  id: string
  material_id: string
  version_id: string
  parent_id?: string | null
  name: string
  description?: string | null
  structured_content?: KnowledgeStructuredContent | null
  sort_order?: number
  level: number
  is_low_confidence?: boolean
  children?: KnowledgeTreeNode[]
}

export interface KnowledgeTreeResult {
  material_id: string
  version_id: string
  nodes: KnowledgeTreeNode[]
}

export interface KnowledgePointDetail {
  id: string
  material_id: string
  version_id: string
  parent_id?: string | null
  name: string
  description?: string | null
  structured_content?: KnowledgeStructuredContent | null
  sort_order?: number
  level: number
  is_low_confidence?: boolean
  batch_id?: string
  created_at: string
  updated_at?: string
}

export interface KnowledgeSnippet {
  id: string
  material_id?: string
  version_id?: string
  page_index: number
  pageEnd?: number | null
  snippet_index?: number
  chapter_title?: string | null
  content: string
  char_length?: number
}

export interface PointSourceListResult {
  knowledge_point_id: string
  snippets: KnowledgeSnippet[]
}
