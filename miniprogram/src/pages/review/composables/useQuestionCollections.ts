import { ref } from 'vue'
import { MAX_PRACTICE_QUESTIONS, apiCreatePractice } from '@/api'
import {
  apiCreateCollection,
  apiDeleteCollection,
  apiListCollectionQuestions,
  apiListCollections,
  apiRemoveCollectionItem,
  apiUpdateCollection,
} from '@/api/modules/collections'
import type { CollectionQuestionItem, QuestionCollection } from '@/types'
import { extractUserErrorMessage, safeShowToast } from '@/utils/loadingGuard'

const PAGE_SIZE = 20

function confirmDeleteCollection(name: string): Promise<boolean> {
  return new Promise((resolve) => {
    uni.showModal({
      title: '删除题单',
      content: `确定删除「${name}」吗？仅删除题单，不删除题目。`,
      success: (res: { confirm?: boolean }) => resolve(Boolean(res?.confirm)),
      fail: () => resolve(false),
    })
  })
}

export function useQuestionCollections(folderIdGetter: () => string = () => 'all') {
  const collections = ref<QuestionCollection[]>([])
  const isLoading = ref(false)
  const loadError = ref('')
  const expandedIds = ref<string[]>([])
  const questionsByCollection = ref<Map<string, CollectionQuestionItem[]>>(new Map())
  const questionTotals = ref<Map<string, number>>(new Map())
  const questionPages = ref<Map<string, number>>(new Map())
  const loadingQuestionIds = ref<string[]>([])
  const questionErrors = ref<Map<string, string>>(new Map())
  const isSaving = ref(false)
  const startingCollectionId = ref('')
  const removingKey = ref('')
  let currentEpoch = 0

  const isExpanded = (id: string) => expandedIds.value.includes(id)
  const questionsFor = (id: string) => questionsByCollection.value.get(id) ?? []
  const totalFor = (id: string) => questionTotals.value.get(id) ?? 0
  const isLoadingQuestions = (id: string) => loadingQuestionIds.value.includes(id)
  const questionError = (id: string) => questionErrors.value.get(id) ?? ''
  const hasMoreQuestions = (id: string) => questionsFor(id).length < totalFor(id)

  const setQuestionError = (id: string, msg: string) => {
    const next = new Map(questionErrors.value)
    if (msg) next.set(id, msg)
    else next.delete(id)
    questionErrors.value = next
  }

  const loadCollections = async () => {
    const epoch = currentEpoch
    const folderId = folderIdGetter()
    isLoading.value = true
    loadError.value = ''
    try {
      const res = await apiListCollections(folderId)
      if (epoch !== currentEpoch) return
      collections.value = res.items || []
    } catch (err) {
      if (epoch !== currentEpoch) return
      loadError.value = extractUserErrorMessage(err, '题单加载失败，请重试')
    } finally {
      if (epoch === currentEpoch) isLoading.value = false
    }
  }

  const createCollection = async (rawName: string): Promise<QuestionCollection | null> => {
    const name = rawName.trim()
    if (!name || isSaving.value) return null
    isSaving.value = true
    try {
      const folderId = folderIdGetter()
      const scopedFolderId =
        folderId && folderId !== 'all' && folderId !== '__none__' ? folderId : undefined
      const created = await apiCreateCollection({
        name,
        ...(scopedFolderId ? { folder_id: scopedFolderId } : {}),
      })
      collections.value = [created, ...collections.value]
      safeShowToast('已新建题单', 'success')
      return created
    } catch (err) {
      safeShowToast(extractUserErrorMessage(err, '新建题单失败'))
      return null
    } finally {
      isSaving.value = false
    }
  }

  const renameCollection = async (
    collectionId: string,
    rawName: string,
  ): Promise<QuestionCollection | null> => {
    const name = rawName.trim()
    if (!name || isSaving.value) return null
    isSaving.value = true
    try {
      const updated = await apiUpdateCollection(collectionId, { name })
      collections.value = collections.value.map((item) =>
        item.id === collectionId ? updated : item,
      )
      safeShowToast('已重命名', 'success')
      return updated
    } catch (err) {
      safeShowToast(extractUserErrorMessage(err, '重命名失败'))
      return null
    } finally {
      isSaving.value = false
    }
  }

  const deleteCollection = async (collection: QuestionCollection): Promise<boolean> => {
    const confirmed = await confirmDeleteCollection(collection.name)
    if (!confirmed) return false
    try {
      await apiDeleteCollection(collection.id)
      collections.value = collections.value.filter((item) => item.id !== collection.id)
      expandedIds.value = expandedIds.value.filter((id) => id !== collection.id)
      const nextMap = new Map(questionsByCollection.value)
      nextMap.delete(collection.id)
      questionsByCollection.value = nextMap
      safeShowToast('已删除题单', 'success')
      return true
    } catch (err) {
      safeShowToast(extractUserErrorMessage(err, '删除题单失败'))
      return false
    }
  }

  const loadCollectionQuestions = async (collectionId: string, page = 1) => {
    if (loadingQuestionIds.value.includes(collectionId)) return
    const epoch = currentEpoch
    loadingQuestionIds.value = [...loadingQuestionIds.value, collectionId]
    setQuestionError(collectionId, '')
    try {
      const res = await apiListCollectionQuestions(collectionId, page, PAGE_SIZE)
      if (epoch !== currentEpoch) return
      const existing = page === 1 ? [] : (questionsByCollection.value.get(collectionId) ?? [])
      const seen = new Set(existing.map((q) => q.question_id))
      const merged = [...existing, ...(res.items || []).filter((q) => !seen.has(q.question_id))]
      questionsByCollection.value = new Map(questionsByCollection.value).set(collectionId, merged)
      questionTotals.value = new Map(questionTotals.value).set(collectionId, res.total)
      questionPages.value = new Map(questionPages.value).set(collectionId, page)
    } catch (err) {
      if (epoch !== currentEpoch) return
      setQuestionError(collectionId, extractUserErrorMessage(err, '题目加载失败，请重试'))
    } finally {
      loadingQuestionIds.value = loadingQuestionIds.value.filter((id) => id !== collectionId)
    }
  }

  const toggleExpandCollection = async (collectionId: string) => {
    if (isExpanded(collectionId)) {
      expandedIds.value = expandedIds.value.filter((id) => id !== collectionId)
      return
    }
    expandedIds.value = [...expandedIds.value, collectionId]
    if (!questionsByCollection.value.has(collectionId)) {
      await loadCollectionQuestions(collectionId, 1)
    }
  }

  const loadMoreCollectionQuestions = async (collectionId: string) => {
    const nextPage = (questionPages.value.get(collectionId) ?? 1) + 1
    await loadCollectionQuestions(collectionId, nextPage)
  }

  const removeQuestionFromCollection = async (collectionId: string, questionId: string) => {
    const key = `${collectionId}:${questionId}`
    if (removingKey.value === key) return
    removingKey.value = key
    try {
      await apiRemoveCollectionItem(collectionId, questionId)
      const remaining = (questionsByCollection.value.get(collectionId) ?? []).filter(
        (item) => item.question_id !== questionId,
      )
      questionsByCollection.value = new Map(questionsByCollection.value).set(collectionId, remaining)
      const nextTotal = Math.max(0, (questionTotals.value.get(collectionId) ?? 1) - 1)
      questionTotals.value = new Map(questionTotals.value).set(collectionId, nextTotal)
      collections.value = collections.value.map((col) =>
        col.id === collectionId
          ? { ...col, question_count: Math.max(0, col.question_count - 1) }
          : col,
      )
      safeShowToast('已移出题单', 'success')
    } catch (err) {
      safeShowToast(extractUserErrorMessage(err, '移出失败'))
    } finally {
      removingKey.value = ''
    }
  }

  const startCollectionPractice = async (collection: QuestionCollection) => {
    if (startingCollectionId.value || collection.question_count <= 0) return
    startingCollectionId.value = collection.id
    try {
      const count = Math.min(MAX_PRACTICE_QUESTIONS, collection.question_count)
      const session = await apiCreatePractice({
        title: `题单练习 · ${collection.name}`,
        collection_id: collection.id,
        question_count: count,
      })
      if (!session?.id) {
        safeShowToast('创建练习失败，请重试')
        return
      }
      uni.navigateTo({
        url: `/subpackages/practice/pages/session/index?practice_id=${session.id}`,
        fail: () => safeShowToast('打开练习失败，请重试'),
      })
    } catch (err) {
      safeShowToast(extractUserErrorMessage(err, '整单开练失败'))
    } finally {
      startingCollectionId.value = ''
    }
  }

  const resetCollectionsState = () => {
    currentEpoch += 1
    collections.value = []
    loadError.value = ''
    isLoading.value = false
    expandedIds.value = []
    questionsByCollection.value = new Map()
    questionTotals.value = new Map()
    questionPages.value = new Map()
    loadingQuestionIds.value = []
    questionErrors.value = new Map()
  }

  return {
    collections,
    isLoading,
    loadError,
    isSaving,
    startingCollectionId,
    removingKey,
    isExpanded,
    questionsFor,
    isLoadingQuestions,
    questionError,
    hasMoreQuestions,
    loadCollections,
    createCollection,
    renameCollection,
    deleteCollection,
    toggleExpandCollection,
    loadCollectionQuestions,
    loadMoreCollectionQuestions,
    removeQuestionFromCollection,
    startCollectionPractice,
    resetCollectionsState,
  }
}
