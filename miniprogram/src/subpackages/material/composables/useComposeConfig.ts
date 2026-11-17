import { computed, ref } from 'vue'
import { MAX_PRACTICE_QUESTIONS, type FolderKnowledgePointItem, type QuestionType } from '@/types'
import {
  dedupeKnowledgePointOptions,
  groupComposeKps,
  normalizeKpName,
  sampleKnowledgePointIds,
  selectLeafComposePoints,
  type ComposeMode,
  type ComposeScope,
  type KnowledgePointOption,
} from '../utils/composeHelpers'

export type { ComposeMode, ComposeScope, KnowledgePointOption }

const DEFAULT_TYPES: QuestionType[] = [
  'single_choice',
  'multiple_choice',
  'true_false',
  'short_answer',
]

/** 组卷配置状态：作用域、去重考点勾选、组卷策略、题型、题量与难度。 */
export function useComposeConfig() {
  const scope = ref<ComposeScope>({})
  const rawKpList = ref<KnowledgePointOption[]>([])
  const availableKpList = ref<KnowledgePointOption[]>([])
  const selectedKpIds = ref<string[]>([])
  const selectedTypes = ref<QuestionType[]>([...DEFAULT_TYPES])
  const questionCount = ref<number>(5)
  const difficulty = ref<number>(3)
  const composeMode = ref<ComposeMode>('smart_sample')

  const kpGroups = computed(() => {
    const allowedIds = new Set(availableKpList.value.map((point) => point.id))
    const source = rawKpList.value.length > 0 ? rawKpList.value : availableKpList.value
    return groupComposeKps(source)
      .map((group) => ({
        ...group,
        points: group.points.filter((point) => allowedIds.has(point.id)),
      }))
      .filter((group) => group.points.length > 0)
  })

  const effectiveKpIds = computed<string[]>(() => {
    if (
      composeMode.value === 'smart_sample'
      && selectedKpIds.value.length > questionCount.value
    ) {
      return sampleKnowledgePointIds(kpGroups.value, selectedKpIds.value, questionCount.value)
    }
    return selectedKpIds.value
  })

  const plannedCount = computed(() => {
    if (composeMode.value === 'full_coverage') {
      return Math.max(selectedKpIds.value.length, questionCount.value)
    }
    return questionCount.value
  })

  const exceedsPracticeLimit = computed(
    () =>
      composeMode.value === 'full_coverage'
      && selectedKpIds.value.length > MAX_PRACTICE_QUESTIONS,
  )

  const isAllKpSelected = computed(
    () =>
      availableKpList.value.length > 0 &&
      selectedKpIds.value.length === availableKpList.value.length,
  )

  const setScope = (next: ComposeScope) => {
    scope.value = next
  }

  const setComposeMode = (mode: ComposeMode) => {
    composeMode.value = mode
  }

  const setKnowledgePoints = (list: KnowledgePointOption[], preselectedKpId?: string) => {
    rawKpList.value = list
    const leafList = selectLeafComposePoints(list)
    const deduped = dedupeKnowledgePointOptions(leafList, preselectedKpId)
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
      const childIds = deduped
        .filter((point) => point.parent_id === preselectedKpId)
        .map((point) => point.id)
      if (childIds.length > 0) {
        selectedKpIds.value = childIds
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
    kpGroups,
    selectedKpIds,
    effectiveKpIds,
    composeMode,
    setComposeMode,
    selectedTypes,
    questionCount,
    difficulty,
    plannedCount,
    exceedsPracticeLimit,
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
