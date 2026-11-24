import type {
  CollectionQuestionItem,
  CollectionQuestionListResult,
  GroupedKnowledgePointCount,
  GroupedMaterialSummary,
  QuestionCollection,
  QuestionCollectionListResult,
  QuestionGroupedSummaryResult,
  QuestionType,
} from '@/types'
import { adaptQuestion } from './question'

export interface WireQuestionCollection {
  id: string
  name?: string | null
  description?: string | null
  folder_id?: string | null
  folder_name?: string | null
  color_token?: string | null
  is_pinned?: boolean | null
  sort_order?: number | null
  question_count?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export interface WireQuestionCollectionList {
  items?: WireQuestionCollection[] | null
  total?: number | null
}

export interface WireCollectionQuestionItem {
  id: string
  collection_id?: string | null
  question_id: string
  question_type?: QuestionType | null
  difficulty?: number | null
  content?: string | null
  options?: Array<{ key: string; content: string }> | null
  answer?: string | string[] | number | null
  explanation?: string | null
  kp_id?: string | null
  kp_name?: string | null
  material_id?: string | null
  material_title?: string | null
  note?: string | null
  added_at?: string | null
}

export interface WireCollectionQuestionList {
  items?: WireCollectionQuestionItem[] | null
  total?: number | null
  page?: number | null
  page_size?: number | null
}

export interface WireGroupedKnowledgePoint {
  kp_id?: string | null
  kp_name?: string | null
  question_count?: number | null
}

export interface WireGroupedMaterialSummary {
  material_id: string
  material_title?: string | null
  folder_id?: string | null
  folder_name?: string | null
  question_count?: number | null
  knowledge_points?: WireGroupedKnowledgePoint[] | null
}

export interface WireQuestionGroupedSummary {
  total_questions?: number | null
  materials?: WireGroupedMaterialSummary[] | null
}

export function adaptQuestionCollection(wire: WireQuestionCollection): QuestionCollection {
  return {
    id: wire.id,
    name: (wire.name || '').trim() || '未命名题单',
    description: wire.description ?? '',
    folder_id: wire.folder_id ?? null,
    folder_name: wire.folder_name ?? null,
    color_token: wire.color_token ?? null,
    is_pinned: Boolean(wire.is_pinned),
    sort_order: Math.max(0, wire.sort_order ?? 0),
    question_count: Math.max(0, wire.question_count ?? 0),
    created_at: wire.created_at ?? '',
    updated_at: wire.updated_at ?? '',
  }
}

export function adaptQuestionCollectionList(
  wire: WireQuestionCollectionList | null | undefined,
): QuestionCollectionListResult {
  const items = (wire?.items ?? []).map(adaptQuestionCollection)
  return {
    items,
    total: wire?.total ?? items.length,
  }
}

export function adaptCollectionQuestionItem(
  wire: WireCollectionQuestionItem,
): CollectionQuestionItem {
  const qType = (wire.question_type || 'single_choice') as QuestionType
  const adapted = adaptQuestion({
    id: wire.question_id,
    question_type: qType,
    stem: wire.content ?? '',
    options: wire.options ?? undefined,
    answer: wire.answer,
    explanation: wire.explanation ?? '',
  })
  return {
    id: wire.id,
    collection_id: wire.collection_id ?? '',
    question_id: wire.question_id,
    question_type: qType,
    difficulty: wire.difficulty ?? 2,
    content: adapted.stem,
    options: adapted.options ?? [],
    answer: wire.answer ?? null,
    explanation: adapted.explanation ?? '',
    kp_id: wire.kp_id ?? null,
    kp_name: wire.kp_name ?? null,
    material_id: wire.material_id ?? null,
    material_title: wire.material_title ?? null,
    note: wire.note ?? null,
    added_at: wire.added_at ?? '',
  }
}

export function adaptCollectionQuestionList(
  wire: WireCollectionQuestionList | null | undefined,
): CollectionQuestionListResult {
  const items = (wire?.items ?? []).map(adaptCollectionQuestionItem)
  return {
    items,
    total: wire?.total ?? items.length,
    page: wire?.page ?? 1,
    page_size: wire?.page_size ?? 20,
  }
}

function adaptGroupedKp(wire: WireGroupedKnowledgePoint): GroupedKnowledgePointCount {
  return {
    kpId: wire.kp_id ?? null,
    kpName: (wire.kp_name || '').trim() || '未关联考点',
    questionCount: Math.max(0, wire.question_count ?? 0),
  }
}

function adaptGroupedMaterial(wire: WireGroupedMaterialSummary): GroupedMaterialSummary {
  return {
    materialId: wire.material_id,
    materialTitle: (wire.material_title || '').trim() || '未命名讲义',
    folderId: wire.folder_id ?? null,
    folderName: wire.folder_name ?? null,
    questionCount: Math.max(0, wire.question_count ?? 0),
    knowledgePoints: (wire.knowledge_points ?? []).map(adaptGroupedKp),
  }
}

export function adaptQuestionGroupedSummary(
  wire: WireQuestionGroupedSummary | null | undefined,
): QuestionGroupedSummaryResult {
  const materials = (wire?.materials ?? []).map(adaptGroupedMaterial)
  const fallbackTotal = materials.reduce((sum, item) => sum + item.questionCount, 0)
  return {
    totalQuestions: wire?.total_questions ?? fallbackTotal,
    materials,
  }
}
