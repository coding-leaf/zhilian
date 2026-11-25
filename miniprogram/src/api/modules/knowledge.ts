import { request } from '@/utils/request'
import { LONG_REQUEST_TIMEOUT_MS } from '@/utils/requestError'
import type {
  KnowledgePointDetail,
  KnowledgeTreeResult,
  PointSourceListResult,
  PollingRequestOptions,
  StudyGuideResult,
} from '@/types'
import {
  adaptKnowledgePointDetail,
  adaptKnowledgeTree,
  adaptPointSourceList,
  adaptStudyGuideResult,
  type WireKnowledgePointDetail,
  type WireKnowledgeTreeResult,
  type WirePointSourceList,
  type WireStudyGuideResponse,
} from '../adapters'

export function apiGetKnowledgeTree(materialId: string, versionId?: string): Promise<KnowledgeTreeResult> {
  let url = `/materials/${materialId}/knowledge-tree`
  if (versionId) url += `?version_id=${encodeURIComponent(versionId)}`
  return request<WireKnowledgeTreeResult>({
    url,
    method: 'GET',
  }).then(adaptKnowledgeTree)
}

export function apiGetKnowledgePointDetail(id: string): Promise<KnowledgePointDetail> {
  return request<WireKnowledgePointDetail>({
    url: `/knowledge/${id}`,
    method: 'GET',
  }).then(adaptKnowledgePointDetail)
}

export function apiGetKnowledgePointSnippets(id: string): Promise<PointSourceListResult> {
  return request<WirePointSourceList>({
    url: `/knowledge/${id}/snippets`,
    method: 'GET',
  }).then(adaptPointSourceList)
}

export function apiGetKnowledgeStudyGuide(
  kpId: string,
  requestOptions?: PollingRequestOptions,
): Promise<StudyGuideResult> {
  return request<WireStudyGuideResponse>({
    url: `/knowledge/${kpId}/study-guide`,
    method: 'GET',
    ...(requestOptions?.silentToast !== undefined ? { silentToast: requestOptions.silentToast } : {}),
  }).then(adaptStudyGuideResult)
}

export function apiGenerateKnowledgeStudyGuide(
  kpId: string,
  force = false,
): Promise<StudyGuideResult> {
  return request<WireStudyGuideResponse>({
    url: `/knowledge/${kpId}/study-guide/generate`,
    method: 'POST',
    data: force ? { force: true } : {},
    timeout: LONG_REQUEST_TIMEOUT_MS,
  }).then(adaptStudyGuideResult)
}
