import { describe, expect, it } from 'vitest'
import { adaptStudyGuideResult } from '@/api/adapters/knowledge'

describe('knowledge adapter study guide statuses', () => {
  it('adapts failed status with trimmed error_message', () => {
    const res = adaptStudyGuideResult({
      knowledge_point_id: 'kp-1',
      status: 'failed',
      study_guide: null,
      generated_at: null,
      error_message: '  模型调用超时，请稍后重试  ',
    })

    expect(res).toEqual({
      knowledge_point_id: 'kp-1',
      status: 'failed',
      study_guide: null,
      generated_at: null,
      error_message: '模型调用超时，请稍后重试',
    })
  })

  it('normalizes blank error_message to null across ready, generating, and empty states', () => {
    const generating = adaptStudyGuideResult({
      knowledge_point_id: 'kp-2',
      status: 'generating',
      study_guide: null,
      generated_at: null,
      error_message: '   ',
    })
    expect(generating.status).toBe('generating')
    expect(generating.error_message).toBeNull()

    const empty = adaptStudyGuideResult({
      knowledge_point_id: 'kp-3',
      status: 'empty',
      study_guide: null,
      generated_at: null,
    })
    expect(empty.status).toBe('empty')
    expect(empty.error_message).toBeNull()
  })
})
