import { describe, expect, it } from 'vitest'
import { canStartMaterialParse, isMaterialParsing, materialStatusText } from '../src/utils/materialState'

describe('manual material parsing', () => {
  it('allows a new upload but blocks an already queued version', () => {
    expect(canStartMaterialParse({ status: 'pending', parse_status: 'not_started' })).toBe(true)
    const queued = { status: 'pending' as const, parse_status: 'queued' }
    expect(canStartMaterialParse(queued)).toBe(false)
    expect(isMaterialParsing(queued)).toBe(true)
    expect(materialStatusText(queued)).toBe('排队中')
  })

  it('shows OCR and knowledge stages as processing and preserves terminal states', () => {
    for (const stage of ['ocr_processing', 'extracting_knowledge', 'auditing_knowledge', 'embedding_generation']) {
      expect(isMaterialParsing({ status: 'pending', parse_status: stage })).toBe(true)
    }
    expect(isMaterialParsing({ status: 'failed', parse_status: 'queued' })).toBe(false)
    expect(materialStatusText({ status: 'retake_required' })).toBe('需要重拍')
  })
})
