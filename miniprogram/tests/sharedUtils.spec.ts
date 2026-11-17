import { describe, expect, it } from 'vitest'
import { flattenKnowledgeTree } from '@/utils/knowledgeTree'
import { isAnswered } from '@/utils/practiceHelpers'
import {
  ACCESS_TOKEN_KEY,
  STORAGE_KEYS,
  practiceDraftStorageKey,
  practiceSubmitStorageKey,
} from '@/utils/storageKeys'

describe('shared frontend utilities', () => {
  it('flattens knowledge tree in pre-order without mutating source nodes', () => {
    interface TestNode {
      id: string
      name: string
      children?: TestNode[]
    }
    const tree: TestNode[] = [
      {
        id: '1',
        name: 'Chapter 1',
        children: [
          { id: '1-1', name: 'Section 1.1', children: [{ id: '1-1-1', name: 'Topic' }] },
          { id: '1-2', name: 'Section 1.2', children: [] },
        ],
      },
      { id: '2', name: 'Chapter 2' },
    ]

    const flat = flattenKnowledgeTree(tree)
    expect(flat.map((n) => n.id)).toEqual(['1', '1-1', '1-1-1', '1-2', '2'])
    expect(flattenKnowledgeTree(null)).toEqual([])
    expect(flattenKnowledgeTree([])).toEqual([])
  })

  it('evaluates isAnswered consistently across scalar and array values', () => {
    expect(isAnswered(undefined)).toBe(false)
    expect(isAnswered(null)).toBe(false)
    expect(isAnswered('')).toBe(false)
    expect(isAnswered([])).toBe(false)
    expect(isAnswered('A')).toBe(true)
    expect(isAnswered(['A'])).toBe(true)
    expect(isAnswered(0)).toBe(true)
  })

  it('builds centralized storage keys consistently', () => {
    expect(STORAGE_KEYS.ACCESS_TOKEN).toBe('access_token')
    expect(ACCESS_TOKEN_KEY).toBe('access_token')
    expect(practiceDraftStorageKey('u1', 'p1')).toBe('practice_draft_u1_p1')
    expect(practiceDraftStorageKey(undefined, 'p1')).toBe('practice_draft_anonymous_p1')
    expect(practiceSubmitStorageKey('p1')).toBe('practice_submit_key_p1')
  })
})
