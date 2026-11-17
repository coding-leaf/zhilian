import { describe, expect, it } from 'vitest'
import {
  groupKnowledgePointIds,
  hasScope,
  isResumeable,
  practiceActionText,
  practiceQuestionLabel,
  practiceStatusText,
  recordRegenerateScope,
  resolveWrongMarkAction,
  wrongMarkLabel,
} from '@/pages/review/reviewView'
import type { PracticeStatus, PracticeSummary, WrongRecordItem } from '@/types'

function makePractice(overrides: Partial<PracticeSummary> = {}): PracticeSummary {
  return {
    id: 'p-1',
    title: '专题练习',
    status: 'not_started',
    question_count: 10,
    ...overrides,
  }
}

function makeWrong(overrides: Partial<WrongRecordItem> = {}): WrongRecordItem {
  return {
    id: 'w-1',
    practice_id: 'p-1',
    attempt_item_id: 'ai-1',
    question_id: 'q-1',
    knowledge_point_id: 'kp-1',
    is_mastered: false,
    question_snapshot: { stem: '题干', question_type: 'single_choice' },
    ...overrides,
  }
}

describe('reviewView practice status & labels', () => {
  it('maps all practice statuses and fallback to readable Chinese labels', () => {
    const cases: Array<[PracticeStatus, string, boolean, string]> = [
      ['not_started', '未开始', true, '继续作答'],
      ['in_progress', '作答中', true, '继续作答'],
      ['paused', '已暂停', true, '继续作答'],
      ['submitted', '判题中', false, '查看结果'],
      ['partially_graded', '待重判', false, '查看结果'],
      ['completed', '已完成', false, '查看结果'],
      ['timeout', '已超时', false, '查看结果'],
    ]

    for (const [status, expectedText, resumeable, expectedAction] of cases) {
      const p = makePractice({ status })
      expect(practiceStatusText(p)).toBe(expectedText)
      expect(isResumeable(p)).toBe(resumeable)
      expect(practiceActionText(p)).toBe(expectedAction)
    }

    expect(practiceStatusText(makePractice({ status: 'unknown' as PracticeStatus }))).toBe('进行中')
  })

  it('formats practiceQuestionLabel with fallback to total_count and 0', () => {
    expect(practiceQuestionLabel(makePractice({ question_count: 12, total_count: 15 }))).toBe('12 题')
    expect(practiceQuestionLabel(makePractice({ question_count: 0, total_count: 8 }))).toBe('8 题')
    expect(practiceQuestionLabel(makePractice({ question_count: 0, total_count: null }))).toBe('0 题')
  })
})

describe('reviewView wrong-record scope & action helpers', () => {
  it('collects unmastered knowledge point IDs only when a group option is active', () => {
    const records = [
      makeWrong({ id: 'w-1', knowledge_point_id: 'kp-1', is_mastered: false }),
      makeWrong({ id: 'w-2', knowledge_point_id: 'kp-2', is_mastered: true }),
      makeWrong({ id: 'w-3', knowledge_point_id: 'kp-1', is_mastered: false }),
    ]

    expect(groupKnowledgePointIds(records, null)).toEqual([])
    expect(
      groupKnowledgePointIds(records, {
        key: 'folder:f-1',
        label: '操作系统',
        folderId: 'f-1',
        count: 3,
        unclassified: false,
      }),
    ).toEqual(['kp-1'])
  })

  it('resolves single-record regenerate scope giving folder_id precedence over material_id', () => {
    const folderScope = recordRegenerateScope(makeWrong({ folder_id: 'f-1', material_id: 'm-1' }))
    expect(folderScope).toEqual({ folderId: 'f-1' })
    expect(hasScope(folderScope)).toBe(true)

    const materialScope = recordRegenerateScope(makeWrong({ folder_id: null, material_id: 'm-2' }))
    expect(materialScope).toEqual({ materialId: 'm-2' })
    expect(hasScope(materialScope)).toBe(true)

    const emptyScope = recordRegenerateScope(makeWrong({ folder_id: null, material_id: null }))
    expect(emptyScope).toEqual({})
    expect(hasScope(emptyScope)).toBe(false)
  })

  it('resolves wrong mark actions and labels exhaustively', () => {
    expect(resolveWrongMarkAction(null)).toBe('mark')
    expect(wrongMarkLabel(null)).toBe('记入错题')

    const manual = makeWrong({ practice_id: null, attempt_item_id: null })
    expect(resolveWrongMarkAction(manual)).toBe('delete')
    expect(wrongMarkLabel(manual)).toBe('取消标记')

    const judgedPending = makeWrong({ practice_id: 'p-1', is_mastered: false })
    expect(resolveWrongMarkAction(judgedPending)).toBe('master')
    expect(wrongMarkLabel(judgedPending)).toBe('已标记')

    const judgedMastered = makeWrong({ practice_id: 'p-1', is_mastered: true })
    expect(resolveWrongMarkAction(judgedMastered)).toBe('none')
    expect(wrongMarkLabel(judgedMastered)).toBe('已掌握')
  })
})
