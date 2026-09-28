import type { MaterialItem } from '@/types'

type MaterialState = Pick<MaterialItem, 'status' | 'parse_status'> | null | undefined

const activeStages = new Set([
  'queued', 'parsing_doc', 'ocr_processing', 'extracting_knowledge',
  'auditing_knowledge', 'embedding_generation',
])

export function canStartMaterialParse(material: MaterialState): boolean {
  return material?.status === 'pending' &&
    (!material.parse_status || material.parse_status === 'not_started')
}

export function isMaterialParsing(material: MaterialState): boolean {
  if (!material || ['ready', 'failed', 'retake_required'].includes(material.status)) return false
  return material.status === 'parsing' || activeStages.has(material.parse_status || '')
}

export function materialStatusText(material: MaterialState): string {
  if (isMaterialParsing(material)) return material?.parse_status === 'queued' ? '排队中' : '解析中'
  switch (material?.status) {
    case 'ready': return '已解析'
    case 'failed': return '解析失败'
    case 'retake_required': return '需要重拍'
    default: return '待解析'
  }
}
