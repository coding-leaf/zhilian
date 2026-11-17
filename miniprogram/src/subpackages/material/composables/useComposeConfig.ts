import { computed, ref } from 'vue'
import type { FolderKnowledgePointItem, QuestionType } from '@/types'
import {
  dedupeKnowledgePointOptions,
  normalizeKpName,
  type ComposeScope,
  type KnowledgePointOption,
} from '../utils/composeHelpers'

export type { ComposeScope, KnowledgePointOption }

const DEFAULT_TYPES: QuestionType[] = [
  'single_choice',
  'multiple_choice',
  'true_false',
  'short_answer',
]

/** 组卷配置状态：作用域、去重考点勾选、题型、题量与难度。 */
export function useComposeConfig() {
  const scope = ref<ComposeScope>({})
  const availableKpList = ref<KnowledgePointOption[]>([])
  const selectedKpIds = ref<string[]>([])
  const selectedTypes = ref<QuestionType[]>([...DEFAULT_TYPES])
  const questionCount = ref<number>(5)
  const difficulty = ref<number>(3)

  const plannedCount = computed(() =>
    Math.max(selectedKpIds.value.length, questionCount.value),
  )

  const isAllKpSelected = computed(
    () =>
      availableKpList.value.length > 0 &&
      selectedKpIds.value.length === availableKpList.value.length,
  )

  const setScope = (next: ComposeScope) => {
    scope.value = next
  }

  const setKnowledgePoints = (list: KnowledgePointOption[], preselectedKpId?: string) => {
    const deduped = dedupeKnowledgePointOptions(list, preselectedKpId)
    availableKpList.value = deduped
    if (preselectedKpId) {
      const matched =
        deduped.find((point) => point.id === preselectedKpId)
        || (() => {
          const target = list.find((point) => point.id === preselectedKpId)
          if (!target) return undefined
          const norm = normalizeKpName(target.name)
          return deduped.find((point) => normalizeKpName(point.name) === norm)
        })()
      if (matched) {
        selectedKpIds.value = [matched.id]
        return
      }
    }
    selectedKpIds.value = deduped.map((point) => point.id)
  }

  const flattenKnowledgePoints = (
    list: FolderKnowledgePointItem[],
    materialMeta?: { materialId?: string; materialTitle?: string },
  ): KnowledgePointOption[] =>
    list.map((point) => ({
      id: point.id,
      name: point.name,
      level: point.level,
      parent_id: point.parent_id ?? null,
      sort_order: point.sort_order ?? 0,
      material_id: materialMeta?.materialId,
      material_title: materialMeta?.materialTitle,
    }))

  const isKpSelected = (id: string) => selectedKpIds.value.includes(id)

  const toggleKp = (id: string) => {
    selectedKpIds.value = isKpSelected(id)
      ? selectedKpIds.value.filter((value) => value !== id)
      : [...selectedKpIds.value, id]
  }

  const toggleKpGroup = (groupIds: string[]) => {
    if (!groupIds.length) return
    const allSelected = groupIds.every((id) => selectedKpIds.value.includes(id))
    if (allSelected) {
      const removeSet = new Set(groupIds)
      selectedKpIds.value = selectedKpIds.value.filter((id) => !removeSet.has(id))
    } else {
      const merged = new Set([...selectedKpIds.value, ...groupIds])
      selectedKpIds.value = availableKpList.value
        .map((point) => point.id)
        .filter((id) => merged.has(id))
    }
  }

  const toggleSelectAllKp = () => {
    selectedKpIds.value = isAllKpSelected.value
      ? []
      : availableKpList.value.map((point) => point.id)
  }

  const isTypeSelected = (type: QuestionType) => selectedTypes.value.includes(type)

  const toggleType = (type: QuestionType) => {
    if (isTypeSelected(type)) {
      if (selectedTypes.value.length === 1) {
        uni.showToast({ title: '至少选择一种题型', icon: 'none' })
        return
      }
      selectedTypes.value = selectedTypes.value.filter((value) => value !== type)
      return
    }
    selectedTypes.value = [...selectedTypes.value, type]
  }

  return {
    scope,
    setScope,
    availableKpList,
    selectedKpIds,
    selectedTypes,
    questionCount,
    difficulty,
    plannedCount,
    isAllKpSelected,
    setKnowledgePoints,
    flattenKnowledgePoints,
    isKpSelected,
    toggleKp,
    toggleKpGroup,
    toggleSelectAllKp,
    isTypeSelected,
    toggleType,
  }
}
