import type { QuestionItem } from '@/types'

export interface ComposeScope {
  folderId?: string
  materialId?: string
}

export interface KnowledgePointOption {
  id: string
  name: string
  level?: number
  parent_id?: string | null
  sort_order?: number
  material_id?: string
  material_title?: string
}

export interface ComposeKpGroup {
  id: string
  title: string
  points: KnowledgePointOption[]
}

export function normalizeKpName(name: string): string {
  return name.trim().replace(/[\s\-_（）()：:·]+/g, '').toLowerCase()
}

/** 按 id 与规范化名称去重考点，同时保留优先指定的预选 kp_id。 */
export function dedupeKnowledgePointOptions(
  list: readonly KnowledgePointOption[],
  preferredId?: string,
): KnowledgePointOption[] {
  const byNormName = new Map<string, KnowledgePointOption>()
  const seenIds = new Set<string>()
  const orderedKeys: string[] = []

  for (const item of list) {
    if (!item?.id || seenIds.has(item.id)) continue
    seenIds.add(item.id)
    const norm = normalizeKpName(item.name || item.id)
    const key = norm || item.id
    const existing = byNormName.get(key)
    if (!existing) {
      byNormName.set(key, item)
      orderedKeys.push(key)
    } else if (preferredId && item.id === preferredId) {
      byNormName.set(key, item)
    }
  }

  return orderedKeys
    .map((key) => byNormName.get(key))
    .filter((item): item is KnowledgePointOption => Boolean(item))
}

function sortOptionsByOrder(list: KnowledgePointOption[]): KnowledgePointOption[] {
  return list
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const diff = (a.item.sort_order ?? 0) - (b.item.sort_order ?? 0)
      return diff !== 0 ? diff : a.index - b.index
    })
    .map((entry) => entry.item)
}

/** 将考点按资料或章节分组，方便多考点自主选择与按章全选。 */
export function groupComposeKps(list: readonly KnowledgePointOption[]): ComposeKpGroup[] {
  if (!list.length) return []

  const hasMaterialGroups = list.some((item) => Boolean(item.material_title))
  if (hasMaterialGroups) {
    const byMaterial = new Map<string, ComposeKpGroup>()
    for (const item of list) {
      const key = item.material_id || item.material_title || '__material__'
      const existing = byMaterial.get(key)
      if (existing) {
        existing.points.push(item)
      } else {
        byMaterial.set(key, {
          id: key,
          title: item.material_title || '课程讲义',
          points: [item],
        })
      }
    }
    return Array.from(byMaterial.values()).map((group) => ({
      ...group,
      points: sortOptionsByOrder(group.points),
    }))
  }

  const byId = new Map<string, KnowledgePointOption>()
  for (const item of list) {
    byId.set(item.id, item)
  }

  const findChapterRootId = (item: KnowledgePointOption): string | null => {
    if ((item.level ?? 1) <= 1) return null
    const visited = new Set<string>([item.id])
    let parentId = item.parent_id
    while (parentId) {
      if (visited.has(parentId)) return null
      visited.add(parentId)
      const parent = byId.get(parentId)
      if (!parent) return null
      if ((parent.level ?? 1) === 1) return parent.id
      parentId = parent.parent_id
    }
    return null
  }

  const chapterBuckets = new Map<string, KnowledgePointOption[]>()
  const orphans: KnowledgePointOption[] = []
  for (const item of list) {
    if ((item.level ?? 1) <= 1) continue
    const rootId = findChapterRootId(item)
    if (rootId) {
      const bucket = chapterBuckets.get(rootId) ?? []
      bucket.push(item)
      chapterBuckets.set(rootId, bucket)
    } else {
      orphans.push(item)
    }
  }

  const roots = sortOptionsByOrder(list.filter((item) => (item.level ?? 1) === 1))
  const groups: ComposeKpGroup[] = []
  const flatLeaves: KnowledgePointOption[] = []

  for (const root of roots) {
    const descendants = chapterBuckets.get(root.id)
    if (descendants && descendants.length > 0) {
      groups.push({
        id: root.id,
        title: root.name,
        points: sortOptionsByOrder([root, ...descendants]),
      })
    } else {
      flatLeaves.push(root)
    }
  }

  const ungrouped = sortOptionsByOrder([...flatLeaves, ...orphans])
  if (ungrouped.length > 0) {
    groups.push({
      id: '__general__',
      title: groups.length > 0 ? '其他考点' : '全部可选考点',
      points: ungrouped,
    })
  }

  return groups
}

export function formatQuestionAnswer(question: Pick<QuestionItem, 'type' | 'answer'>): string {
  const raw = question.answer
  if (raw === null || raw === undefined || raw === '') return '暂无参考答案'
  if (Array.isArray(raw)) {
    const joined = raw.map((item) => String(item).trim()).filter(Boolean).join('、')
    return joined || '暂无参考答案'
  }
  if (typeof raw === 'number') return String(raw)

  const trimmed = String(raw).trim()
  if (!trimmed) return '暂无参考答案'

  if (question.type === 'multiple_choice' && trimmed.startsWith('[')) {
    try {
      const parsed = JSON.parse(trimmed)
      if (Array.isArray(parsed)) {
        return parsed.map((item) => String(item).trim()).filter(Boolean).join('、') || trimmed
      }
    } catch {
      // fall through
    }
  }

  if (question.type === 'fill_in_blank') {
    return trimmed
      .split(/\s*(?:;|；|&&)\s*/)
      .map((blank) => blank.replace(/\s*(?:\|\|\||\/\/\/|\|)\s*/g, ' 或 '))
      .join(' ； ')
  }

  return trimmed
}
