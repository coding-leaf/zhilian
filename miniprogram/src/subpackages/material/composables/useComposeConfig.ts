import { computed, ref } from 'vue'
import type { FolderKnowledgePointItem, QuestionType } from '@/types'

export interface ComposeScope {
  folderId?: string
  materialId?: string
}

export interface KnowledgePointOption {
  id: string
  name: string
}

const DEFAULT_TYPES: QuestionType[] = [
  'single_choice',
  'multiple_choice',
  'true_false',
  'short_answer',
]

/** 组卷配置状态：作用域、考点勾选、题型、题量与难度。 */
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

  const setKnowledgePoints = (list: KnowledgePointOption[]) => {
    availableKpList.value = list
    selectedKpIds.value = list.map((point) => point.id)
  }

  const flattenKnowledgePoints = (list: FolderKnowledgePointItem[]): KnowledgePointOption[] =>
    list.map((point) => ({ id: point.id, name: point.name }))

  const isKpSelected = (id: string) => selectedKpIds.value.includes(id)

  const toggleKp = (id: string) => {
    selectedKpIds.value = isKpSelected(id)
      ? selectedKpIds.value.filter((value) => value !== id)
      : [...selectedKpIds.value, id]
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
    toggleSelectAllKp,
    isTypeSelected,
    toggleType,
  }
}
