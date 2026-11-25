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
  hasStudyGuide?: boolean
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
  hasStudyGuide?: boolean
  batch_id?: string
  created_at: string
  updated_at?: string
}

export interface StudyGuideSymbol {
  symbol: string
  meaning: string
  note: string
}

export interface StudyGuideDerivationStep {
  step_title: string
  formula: string
  explanation: string
}

export interface StudyGuideWorkedExample {
  title: string
  question_type: string
  problem: string
  solution_idea: string
  solution_steps: string[]
  final_answer: string
}

export interface StudyGuideComparison {
  target_concept: string
  similarities: string
  differences: string
  exam_distinction: string
}

export interface StudyGuidePitfall {
  mistake: string
  why_wrong: string
  correction: string
}

export interface StudyGuideContent {
  schema_version: number
  exam_positioning: string
  core_definition: string
  symbol_table: StudyGuideSymbol[]
  key_formulas: string[]
  derivation_steps: StudyGuideDerivationStep[]
  worked_examples: StudyGuideWorkedExample[]
  comparisons: StudyGuideComparison[]
  pitfalls: StudyGuidePitfall[]
  memory_anchors: string[]
}

export type StudyGuideStatus = 'empty' | 'generating' | 'ready'

export interface StudyGuideResult {
  knowledge_point_id: string
  status: StudyGuideStatus
  study_guide: StudyGuideContent | null
  generated_at: string | null
}

export type StudyGuidePrewarmStatus =
  | 'idle'
  | 'queued'
  | 'running'
  | 'completed'
  | 'partial_failed'

export interface StudyGuidePrewarmResult {
  material_id: string
  version_id: string
  status: 'queued' | 'running' | 'completed'
  total_kps: number
  ready_kps: number
}

export interface StudyGuidePrewarmStatusResult {
  material_id: string
  version_id: string
  status: StudyGuidePrewarmStatus
  total_kps: number
  ready_kps: number
  failed_kps: number
  current_kp_name: string | null
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
