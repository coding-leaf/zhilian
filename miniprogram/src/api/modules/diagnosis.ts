import { request } from '@/utils/request'
import type { DiagnosisReport, UserMasteryOverview } from '@/types'
import {
  adaptDiagnosisReport,
  adaptMasteryOverview,
  type WireDiagnosisReport,
  type WireUserMasteryOverview,
} from '../adapters'

export function apiTriggerDiagnosis(practiceId: string): Promise<DiagnosisReport> {
  return request<WireDiagnosisReport>({
    url: `/practices/${practiceId}/diagnosis`,
    method: 'POST',
  }).then(adaptDiagnosisReport)
}

export function apiGetMasteryOverview(
  folderId?: string | null,
  materialId?: string | null,
): Promise<UserMasteryOverview> {
  const queryParts: string[] = []
  if (folderId && folderId !== 'all') {
    queryParts.push(`folder_id=${encodeURIComponent(folderId)}`)
  }
  if (materialId) {
    queryParts.push(`material_id=${encodeURIComponent(materialId)}`)
  }
  const qs = queryParts.length ? `?${queryParts.join('&')}` : ''
  return request<WireUserMasteryOverview>({
    url: `/mastery${qs}`,
    method: 'GET',
  }).then(adaptMasteryOverview)
}
