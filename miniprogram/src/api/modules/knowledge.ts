import { request } from '@/utils/request'
import type {
  KnowledgePointDetail,
  KnowledgeTreeResult,
  PointSourceListResult,
} from '@/types'
import {
  adaptKnowledgePointDetail,
  adaptKnowledgeTree,
  adaptPointSourceList,
  type WireKnowledgePointDetail,
  type WireKnowledgeTreeResult,
  type WirePointSourceList,
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
