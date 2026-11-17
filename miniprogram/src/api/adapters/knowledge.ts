import type { KnowledgeSnippet, PointSourceListResult } from '@/types'

interface WireKnowledgeSnippet {
  id: string
  material_id?: string
  version_id?: string
  page_index?: number | null
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
 * 原文溯源切片归一化：对齐后端 `SnippetSourceResponse`（1-based `page_index`）。
 * 缺失或非法页码安全回退为 1，避免出现第 0 页或 undefined。
 */
export function adaptKnowledgeSnippet(snippet: WireKnowledgeSnippet): KnowledgeSnippet {
  const rawPage = snippet.page_index
  const pageIndex = typeof rawPage === 'number' && Number.isFinite(rawPage) && rawPage >= 1
    ? Math.floor(rawPage)
    : 1
  const chapterTitle = typeof snippet.chapter_title === 'string' && snippet.chapter_title.trim()
    ? snippet.chapter_title.trim()
    : null

  return {
    id: snippet.id,
    material_id: snippet.material_id,
    version_id: snippet.version_id,
    page_index: pageIndex,
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
