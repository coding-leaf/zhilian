import { request } from '@/utils/request'
import type {
  AddCollectionItemsResult,
  CollectionQuestionListResult,
  CreateCollectionParams,
  QuestionCollection,
  QuestionCollectionListResult,
  QuestionCollectionMembership,
  SyncQuestionCollectionsResult,
  UpdateCollectionParams,
} from '@/types'
import {
  adaptCollectionQuestionList,
  adaptQuestionCollection,
  adaptQuestionCollectionList,
  type WireCollectionQuestionList,
  type WireQuestionCollection,
  type WireQuestionCollectionList,
} from '../adapters'

export function apiListCollections(folderId?: string): Promise<QuestionCollectionListResult> {
  const qs =
    folderId && folderId !== 'all' ? `?folder_id=${encodeURIComponent(folderId)}` : ''
  return request<WireQuestionCollectionList>({
    url: `/collections${qs}`,
    method: 'GET',
  }).then(adaptQuestionCollectionList)
}

export function apiCreateCollection(params: CreateCollectionParams): Promise<QuestionCollection> {
  return request<WireQuestionCollection>({
    url: '/collections',
    method: 'POST',
    data: params,
  }).then(adaptQuestionCollection)
}

export function apiUpdateCollection(
  collectionId: string,
  params: UpdateCollectionParams,
): Promise<QuestionCollection> {
  return request<WireQuestionCollection>({
    url: `/collections/${collectionId}`,
    method: 'PUT',
    data: params,
  }).then(adaptQuestionCollection)
}

export function apiDeleteCollection(collectionId: string): Promise<void> {
  return request<void>({
    url: `/collections/${collectionId}`,
    method: 'DELETE',
  })
}

export function apiListCollectionQuestions(
  collectionId: string,
  page = 1,
  pageSize = 20,
): Promise<CollectionQuestionListResult> {
  return request<WireCollectionQuestionList>({
    url: `/collections/${collectionId}/questions?page=${page}&page_size=${pageSize}`,
    method: 'GET',
  }).then(adaptCollectionQuestionList)
}

export function apiAddCollectionItems(
  collectionId: string,
  questionIds: string[],
  note?: string,
): Promise<AddCollectionItemsResult> {
  return request<AddCollectionItemsResult>({
    url: `/collections/${collectionId}/items`,
    method: 'POST',
    data: {
      question_ids: questionIds,
      ...(note !== undefined ? { note } : {}),
    },
  })
}

export function apiRemoveCollectionItem(collectionId: string, questionId: string): Promise<void> {
  return request<void>({
    url: `/collections/${collectionId}/items/${questionId}`,
    method: 'DELETE',
  })
}

export function apiGetQuestionCollections(
  questionId: string,
): Promise<QuestionCollectionMembership> {
  return request<QuestionCollectionMembership>({
    url: `/questions/${questionId}/collections`,
    method: 'GET',
  })
}

export function apiSyncQuestionCollections(
  questionId: string,
  collectionIds: string[],
): Promise<SyncQuestionCollectionsResult> {
  return request<SyncQuestionCollectionsResult>({
    url: `/questions/${questionId}/collections`,
    method: 'POST',
    data: { collection_ids: collectionIds },
  })
}
