import type {
  KnowledgeMasteryLevel,
  KnowledgeStructuredContent,
  KnowledgeTreeNode,
  UserMasteryOverview,
} from '@/types'

export type MasteryBadgeTone = 'unlearned' | 'weak' | 'basic' | 'proficient'

export interface MasteryEntry {
  score: number
  level: KnowledgeMasteryLevel
  practiceCount: number
}

export interface MasteryBadge {
  text: string
  tone: MasteryBadgeTone
}

export interface ChapterStudyGroup {
  id: string
  title: string
  chapterNode: KnowledgeTreeNode | null
  points: KnowledgeTreeNode[]
}

const PREVIEW_SYMBOL_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\\propto/g, '∝'],
  [/\\prod/g, '∏'],
  [/\\sum/g, '∑'],
  [/\\times/g, '×'],
  [/\\cdot/g, '·'],
  [/\\div/g, '÷'],
  [/\\pm/g, '±'],
  [/\\leq?/g, '≤'],
  [/\\geq?/g, '≥'],
  [/\\neq?/g, '≠'],
  [/\\approx/g, '≈'],
  [/\\in\b/g, '∈'],
  [/\\to\b|\\rightarrow/g, '→'],
  [/\\alpha/g, 'α'],
  [/\\beta/g, 'β'],
  [/\\gamma/g, 'γ'],
  [/\\theta/g, 'θ'],
  [/\\lambda/g, 'λ'],
  [/\\mu/g, 'μ'],
  [/\\sigma/g, 'σ'],
  [/\\Sigma/g, 'Σ'],
  [/\\pi/g, 'π'],
  [/\\Delta/g, 'Δ'],
]

export function buildMasteryMap(
  overview: UserMasteryOverview | null | undefined,
): Record<string, MasteryEntry> {
  const map: Record<string, MasteryEntry> = {}
  if (!overview) return map

  const collect = (items?: UserMasteryOverview['points']) => {
    if (!Array.isArray(items)) return
    for (const item of items) {
      if (!item?.knowledge_point_id) continue
      map[item.knowledge_point_id] = {
        score: typeof item.mastery_score === 'number' ? item.mastery_score : 0,
        level: item.level || 'unlearned',
        practiceCount: Math.max(0, item.practice_count ?? 0),
      }
    }
  }

  collect(overview.weak_knowledge_points)
  collect(overview.weak_points)
  collect(overview.points)
  return map
}

export function resolveMasteryBadge(entry?: MasteryEntry | number | null): MasteryBadge {
  if (entry === null || entry === undefined) {
    return { text: '未练', tone: 'unlearned' }
  }
  if (typeof entry === 'number') {
    if (!Number.isFinite(entry) || entry < 0) return { text: '未练', tone: 'unlearned' }
    const pct = Math.round(Math.max(0, Math.min(1, entry)) * 100)
    if (pct < 40) return { text: `薄弱 ${pct}%`, tone: 'weak' }
    if (pct < 80) return { text: `基本掌握 ${pct}%`, tone: 'basic' }
    return { text: `熟练 ${pct}%`, tone: 'proficient' }
  }

  if (entry.level === 'unlearned' || (entry.practiceCount === 0 && entry.score <= 0)) {
    return { text: '未练', tone: 'unlearned' }
  }

  const pct = Math.round(Math.max(0, Math.min(1, entry.score)) * 100)
  if (pct < 40) return { text: `薄弱 ${pct}%`, tone: 'weak' }
  if (pct < 80) return { text: `基本掌握 ${pct}%`, tone: 'basic' }
  return { text: `熟练 ${pct}%`, tone: 'proficient' }
}

export function hasStructuredContent(
  sc: KnowledgeStructuredContent | null | undefined,
): sc is KnowledgeStructuredContent {
  if (!sc) return false
  return Boolean(
    sc.core_summary?.trim()
    || sc.key_takeaways?.length
    || sc.key_formulas?.length
    || sc.derivation_steps?.length
    || sc.boundary_notes?.length
    || sc.common_mistakes?.length,
  )
}

export function formatSnippetPageRange(
  pageIndex: number | null | undefined,
  pageEnd?: number | null,
): string {
  const start = typeof pageIndex === 'number' && Number.isFinite(pageIndex) && pageIndex >= 1
    ? Math.floor(pageIndex)
    : 1
  if (typeof pageEnd === 'number' && Number.isFinite(pageEnd) && Math.floor(pageEnd) > start) {
    return `第 ${start}–${Math.floor(pageEnd)} 页`
  }
  return `第 ${start} 页`
}

function hasUnclosedMath(prefix: string): boolean {
  let inDisplay = false
  let inInline = false
  for (let i = 0; i < prefix.length; i += 1) {
    if (prefix[i] === '\\') {
      i += 1
      continue
    }
    if (prefix[i] === '$') {
      if (prefix.startsWith('$$', i)) {
        if (!inInline) inDisplay = !inDisplay
        i += 1
      } else if (!inDisplay) {
        inInline = !inInline
      }
    }
  }
  return inDisplay || inInline
}

export function trimSnippetExcerpt(
  raw: string | null | undefined,
  maxChars = 240,
): { text: string; truncated: boolean } {
  const content = (raw ?? '').trim()
  if (!content || maxChars <= 0 || content.length <= maxChars) {
    return { text: content, truncated: false }
  }
  const limit = Math.max(1, maxChars - 1)
  const minCut = Math.floor(limit * 0.4)
  const findSafeCut = (lo: number, chars: string): number | null => {
    for (let i = limit - 1; i >= lo; i -= 1) {
      if (chars.includes(content[i]) && !hasUnclosedMath(content.slice(0, i + 1))) {
        return i + 1
      }
    }
    return null
  }
  let cut = findSafeCut(minCut, '。！？!?\n')
    ?? findSafeCut(minCut, '，；、,;')
    ?? findSafeCut(0, '。！？!?\n')
  if (cut === null) {
    cut = limit
    while (cut > 0 && hasUnclosedMath(content.slice(0, cut))) {
      cut -= 1
    }
    if (cut === 0) cut = limit
  }
  return { text: `${content.slice(0, cut).trimEnd()}…`, truncated: true }
}

export function stripInlineMarkdownAndMath(raw: string | null | undefined): string {
  if (!raw) return ''
  let text = raw.replace(/\r\n/g, ' ').replace(/\n+/g, ' ')
  text = text.replace(/\$\$/g, '').replace(/\$/g, '')
  text = text.replace(/\\\(|\\\)|\\\[|\\\]/g, '')
  text = text.replace(/\\(?:text|mathrm|mathbf|mathit|mathcal|operatorname|boldsymbol)\{([^}]*)\}/g, '$1')
  text = text.replace(/\\(?:d|t)?frac\{([^}]*)\}\{([^}]*)\}/g, '($1)/($2)')
  text = text.replace(/\\sqrt\{([^}]*)\}/g, '√($1)')
  text = text.replace(/\\(?:left|right|quad|qquad|limits|nolimits)\b/g, '')
  for (const [pattern, symbol] of PREVIEW_SYMBOL_REPLACEMENTS) {
    text = text.replace(pattern, symbol)
  }
  text = text.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/__([^_]+)__/g, '$1')
  text = text.replace(/`([^`]+)`/g, '$1')
  text = text.replace(/^\s*#{1,4}\s+/g, '')
  text = text.replace(/[_^{}]/g, (ch) => (ch === '{' || ch === '}' ? '' : ch))
  return text.replace(/\s+/g, ' ').trim()
}

export function formatKpSummaryPreview(
  node: Pick<KnowledgeTreeNode, 'structured_content' | 'description'>,
): string {
  const raw = node.structured_content?.core_summary?.trim() || node.description || ''
  return stripInlineMarkdownAndMath(raw)
}

function sortNodesByOrder(list: KnowledgeTreeNode[]): KnowledgeTreeNode[] {
  return list
    .map((node, index) => ({ node, index }))
    .sort((a, b) => {
      const orderDiff = (a.node.sort_order ?? 0) - (b.node.sort_order ?? 0)
      return orderDiff !== 0 ? orderDiff : a.index - b.index
    })
    .map((entry) => entry.node)
}

export function flattenTreeWithParents(
  nodes: readonly KnowledgeTreeNode[] | null | undefined,
  fallbackParentId: string | null = null,
): KnowledgeTreeNode[] {
  if (!nodes?.length) return []
  const result: KnowledgeTreeNode[] = []
  const traverse = (list: readonly KnowledgeTreeNode[], parentId: string | null) => {
    for (const node of list) {
      const normalized = node.parent_id ? node : { ...node, parent_id: parentId }
      result.push(normalized)
      if (node.children?.length) {
        traverse(node.children, node.id)
      }
    }
  }
  traverse(nodes, fallbackParentId)
  return result
}

export function groupKnowledgePointsByChapter(
  nodes: readonly KnowledgeTreeNode[],
): ChapterStudyGroup[] {
  if (!nodes.length) return []

  const nodeMap = new Map<string, KnowledgeTreeNode>()
  for (const node of nodes) {
    nodeMap.set(node.id, node)
  }

  const findChapterRootId = (node: KnowledgeTreeNode): string | null => {
    const visited = new Set<string>([node.id])
    let parentId = node.parent_id
    while (parentId) {
      if (visited.has(parentId)) return null
      visited.add(parentId)
      const parent = nodeMap.get(parentId)
      if (!parent) return null
      if (parent.level === 1) return parent.id
      parentId = parent.parent_id
    }
    return null
  }

  const childrenByChapter = new Map<string, KnowledgeTreeNode[]>()
  const orphanChildren: KnowledgeTreeNode[] = []

  for (const node of nodes) {
    if (node.level <= 1) continue
    const rootId = findChapterRootId(node)
    if (rootId) {
      const bucket = childrenByChapter.get(rootId) ?? []
      bucket.push(node)
      childrenByChapter.set(rootId, bucket)
    } else {
      orphanChildren.push(node)
    }
  }

  const roots = sortNodesByOrder(nodes.filter((node) => node.level === 1))
  const groups: ChapterStudyGroup[] = []
  const flatLeaves: KnowledgeTreeNode[] = []

  for (const root of roots) {
    const descendants = childrenByChapter.get(root.id)
    if (descendants && descendants.length > 0) {
      groups.push({
        id: root.id,
        title: root.name,
        chapterNode: root,
        points: sortNodesByOrder(descendants),
      })
    } else {
      flatLeaves.push(root)
    }
  }

  const ungrouped = sortNodesByOrder([...flatLeaves, ...orphanChildren])
  if (ungrouped.length > 0) {
    groups.push({
      id: '__general__',
      title: groups.length > 0 ? '其他核心考点' : '讲义核心考点',
      chapterNode: null,
      points: ungrouped,
    })
  }

  return groups
}
