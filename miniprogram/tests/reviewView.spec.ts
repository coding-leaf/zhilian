import { describe, expect, it } from 'vitest'
import {
  computePracticedPointCount,
  formatPointAccuracy,
  groupKnowledgePointIds,
  hasScope,
  isResumeable,
  masteryLevelLabel,
  mergeMasteryPoints,
  practiceAccuracyBadge,
  practiceActionButtonText,
  practiceActionText,
  practiceQuestionLabel,
  practiceStatusText,
  recordRegenerateScope,
  resolveWrongMarkAction,
  wrongKnowledgePointLabel,
  wrongMarkLabel,
} from '@/pages/review/reviewView'
import type {
  PracticeStatus,
  PracticeSummary,
  UserMasteryOverview,
  WrongRecordItem,
} from '@/types'

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
    expect(practiceActionButtonText(makePractice({ status: 'completed' }))).toBe('查看解析报告')
    expect(practiceActionButtonText(makePractice({ status: 'in_progress' }))).toBe('继续作答')
    expect(practiceAccuracyBadge(makePractice({ score_rate: 0.82 }))).toBe('正确率 82%')
    expect(practiceAccuracyBadge(makePractice({ total_score: 4, max_score: 5 }))).toBe('4/5 · 80%')
  })

  it('formats practiceQuestionLabel with fallback to total_count and 0', () => {
    expect(practiceQuestionLabel(makePractice({ question_count: 12, total_count: 15 }))).toBe('12 题')
    expect(practiceQuestionLabel(makePractice({ question_count: 0, total_count: 8 }))).toBe('8 题')
    expect(practiceQuestionLabel(makePractice({ question_count: 0, total_count: null }))).toBe('0 题')
  })
})

describe('reviewView mastery sorting & wrong KP labels', () => {
  it('sorts mastery points with weak -> basic -> unlearned -> proficient priority', () => {
    const overview: UserMasteryOverview = {
      total_points: 4,
      total_knowledge_points: 4,
      mastered_count: 1,
      proficient_count: 1,
      learning_count: 1,
      basic_count: 1,
      weak_count: 1,
      unlearned_count: 1,
      overall_score: 0.52,
      overall_mastery_score: 0.52,
      points: [
        {
          knowledge_point_id: 'kp-prof',
          knowledge_name: '全概率公式',
          mastery_score: 0.92,
          level: 'proficient',
          practice_count: 5,
          correct_count: 5,
        },
        {
          knowledge_point_id: 'kp-un',
          knowledge_name: '平滑修正',
          mastery_score: 0,
          level: 'unlearned',
          practice_count: 0,
          correct_count: 0,
        },
        {
          knowledge_point_id: 'kp-basic',
          knowledge_name: '条件独立假设',
          mastery_score: 0.65,
          level: 'basic',
          practice_count: 4,
          correct_count: 3,
        },
      ],
      weak_knowledge_points: [
        {
          knowledge_point_id: 'kp-weak',
          knowledge_name: '朴素贝叶斯分类器',
          mastery_score: 0.2,
          level: 'weak',
          practice_count: 2,
          correct_count: 0,
        },
      ],
      weak_points: [],
    }

    const merged = mergeMasteryPoints(overview)
    expect(merged.map((p) => p.knowledge_point_id)).toEqual([
      'kp-weak',
      'kp-basic',
      'kp-un',
      'kp-prof',
    ])
    expect(masteryLevelLabel('weak')).toBe('薄弱')
    expect(masteryLevelLabel('basic')).toBe('基本掌握')
    expect(masteryLevelLabel('unlearned')).toBe('未练')
    expect(masteryLevelLabel('proficient')).toBe('熟练')
    expect(computePracticedPointCount(overview)).toBe(3)
    expect(formatPointAccuracy(merged[1])).toBe('正确率 75% (3/4)')
    expect(formatPointAccuracy(merged[2])).toBe('暂无作答')
  })

  it('binds real knowledge point name for wrong record instead of question type', () => {
    expect(
      wrongKnowledgePointLabel(makeWrong({ knowledge_point_name: '最大似然估计' })),
    ).toBe('最大似然估计')
    expect(
      wrongKnowledgePointLabel(
        makeWrong({
          knowledge_point_name: null,
          question_snapshot: {
            stem: '题干',
            question_type: 'single_choice',
            knowledge_point_name: '贝叶斯定理',
          },
        }),
      ),
    ).toBe('贝叶斯定理')
    expect(wrongKnowledgePointLabel(makeWrong({ knowledge_point_name: null }))).toBe('综合考点')
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
