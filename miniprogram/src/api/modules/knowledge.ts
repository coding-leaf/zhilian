import { request } from '@/utils/request'
import type {
  KnowledgePointDetail,
  KnowledgeTreeResult,
  PointSourceListResult,
} from '@/types'
import { adaptPointSourceList, type WirePointSourceList } from '../adapters'

export function apiGetKnowledgeTree(materialId: string, versionId?: string): Promise<KnowledgeTreeResult> {
  let url = `/materials/${materialId}/knowledge-tree`
  if (versionId) url += `?version_id=${encodeURIComponent(versionId)}`
  return request<KnowledgeTreeResult>({
    url,
    method: 'GET',
  })
}

export function apiGetKnowledgePointDetail(id: string): Promise<KnowledgePointDetail> {
  return request<KnowledgePointDetail>({
    url: `/knowledge/${id}`,
    method: 'GET',
  })
}

export function apiGetKnowledgePointSnippets(id: string): Promise<PointSourceListResult> {
  return request<WirePointSourceList>({
    url: `/knowledge/${id}/snippets`,
    method: 'GET',
  }).then(adaptPointSourceList)
}
