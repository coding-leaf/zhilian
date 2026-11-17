import { request } from '@/utils/request'
import type { DiagnosisReport } from '@/types'
import { adaptDiagnosisReport, type WireDiagnosisReport } from '../adapters'

export function apiTriggerDiagnosis(practiceId: string): Promise<DiagnosisReport> {
  return request<WireDiagnosisReport>({
    url: `/practices/${practiceId}/diagnosis`,
    method: 'POST',
  }).then(adaptDiagnosisReport)
}
