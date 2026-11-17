import { describe, expect, it } from 'vitest'
import { adaptPractice, summarizeProgress } from '@/api/adapters/practice'
import {
  buildWeakPointViews,
  collectWrongKnowledgePointIds,
  formatAnswer,
  formatAttemptAnswer,
  formatPercent,
  formatScore,
  resolveOptionTone,
  resolveResultBadge,
  resolveSessionScope,
  resolveSourceQuoteView,
  typeLabel,
} from '@/subpackages/report/utils/reportView'
import type { AttemptResult, DiagnosisReport, PracticeSession } from '@/types'

function makeResult(overrides: Partial<AttemptResult> = {}): AttemptResult {
  return {
    attemptItemId: 'ai-1',
    questionId: 'q-1',
    knowledgePointId: 'kp-1',
    orderIndex: 1,
    type: 'single_choice',
    stem: '题干',
    options: [],
    userAnswer: 'A',
    correctAnswer: 'A',
    isAnswered: true,
    gradingStatus: 'graded',
    isPending: false,
    score: 2,
    maxScore: 2,
    isCorrect: true,
    hitKeywords: [],
    missingKeywords: [],
    gradingPoints: [],
    ...overrides,
  }
}

function makeReport(overrides: Partial<DiagnosisReport> = {}): DiagnosisReport {
  return {
    id: 'rep-1',
    practice_id: 'p-1',
    knowledge_evaluations: [],
    weak_knowledge_points: [],
    regressed_knowledge_points: [],
    analysis_causes: [],
    actionable_suggestions: [],
    root_causes: [],
    suggestions: [],
    unanswered_count: 0,
    wrong_count: 0,
    pending_regrade_count: 0,
    total_questions: 1,
    score_rate: 1,
    is_structure_degraded: false,
    ...overrides,
  }
}

describe('reportView formatting helpers', () => {
  it('formats scalar, array, object, and empty answers consistently', () => {
    expect(formatAnswer(undefined)).toBe('未作答')
    expect(formatAnswer(null)).toBe('未作答')
    expect(formatAnswer('')).toBe('未作答')
    expect(formatAnswer([])).toBe('未作答')
    expect(formatAnswer(['A', 'C'])).toBe('A、C')
    expect(formatAnswer({ step: 1 })).toBe('{"step":1}')
    expect(formatAnswer('B')).toBe('B')
    expect(formatAnswer(0)).toBe('0')
  })

  it('formats attempt answers by question type and guards garbled source quotes', () => {
    expect(formatAttemptAnswer('A', 'true_false')).toBe('正确')
    expect(formatAttemptAnswer('F', 'true_false')).toBe('错误')
    expect(formatAttemptAnswer('["A","C"]', 'multiple_choice')).toBe('A、C')
    expect(formatAttemptAnswer('先验|||后验; 极大似然', 'fill_in_blank')).toBe(
      '先验 或 后验 ； 极大似然',
    )

    expect(resolveSourceQuoteView('AB&A&\n"#$"$').isGarbled).toBe(true)
    expect(resolveSourceQuoteView('AB&A&\n"#$"$').content).toBe('')
    expect(resolveSourceQuoteView('贝叶斯公式利用先验概率更新后验概率。')).toEqual({
      visible: true,
      isGarbled: false,
      content: '贝叶斯公式利用先验概率更新后验概率。',
    })
    expect(resolveSourceQuoteView('')).toEqual({
      visible: false,
      isGarbled: false,
      content: '',
    })

    const mcResult = makeResult({
      type: 'multiple_choice',
      options: [
        { key: 'A', content: '一' },
        { key: 'B', content: '二' },
        { key: 'C', content: '三' },
      ],
      userAnswer: ['A', 'B'],
      correctAnswer: 'A,C',
    })
    expect(resolveOptionTone(mcResult.options[0], 0, mcResult)).toBe('correct')
    expect(resolveOptionTone(mcResult.options[1], 1, mcResult)).toBe('wrong')
    expect(resolveOptionTone(mcResult.options[2], 2, mcResult)).toBe('missed')
  })

  it('formats score, percentage, and question type labels', () => {
    expect(formatScore(null, 5)).toBe('—/5')
    expect(formatScore(3, 5)).toBe('3/5')
    expect(formatPercent(0)).toBe('0%')
    expect(formatPercent(0.756)).toBe('76%')
    expect(typeLabel('single_choice')).toBe('单选题')
    expect(typeLabel('unknown_type')).toBe('试题')
  })
})

describe('resolveResultBadge', () => {
  it('never renders pending or unanswered attempts as zero or wrong', () => {
    expect(resolveResultBadge(makeResult({ isAnswered: false }))).toEqual({
      text: '未作答',
      tone: 'unanswered',
    })
    expect(resolveResultBadge(makeResult({ gradingStatus: 'grading', isCorrect: null, score: null }))).toEqual({
      text: '判题中',
      tone: 'pending',
    })
    expect(
      resolveResultBadge(makeResult({ gradingStatus: 'pending_regrade', isCorrect: null, score: null })),
    ).toEqual({
      text: '待重判',
      tone: 'pending',
    })
    expect(resolveResultBadge(makeResult({ gradingStatus: 'graded', isCorrect: null, score: null }))).toEqual({
      text: '判题中',
      tone: 'pending',
    })
  })

  it('renders graded correct and wrong badges with scores', () => {
    expect(resolveResultBadge(makeResult({ isCorrect: true, score: 2, maxScore: 2 }))).toEqual({
      text: '正确 2/2',
      tone: 'correct',
    })
    expect(resolveResultBadge(makeResult({ isCorrect: false, score: 0, maxScore: 2 }))).toEqual({
      text: '错误 0/2',
      tone: 'wrong',
    })
  })
})

describe('collectWrongKnowledgePointIds & buildWeakPointViews', () => {
  it('prefers weak_knowledge_points from diagnosis report and deduplicates IDs', () => {
    const report = makeReport({
      weak_knowledge_points: [
        {
          knowledge_point_id: 'kp-10',
          knowledge_name: '进程调度',
          current_score: 0.3,
          score_delta: -0.1,
        },
        {
          knowledge_id: 'kp-10',
          knowledge_title: '进程调度',
          current_score: 0.3,
          score_delta: -0.1,
        },
        {
          knowledge_id: 'kp-11',
          knowledge_title: '死锁预防',
          current_score: 0.2,
          score_delta: -0.2,
        },
        {
          current_score: 0.1,
          score_delta: 0,
        },
      ],
    })
    const results = [makeResult({ knowledgePointId: 'kp-fallback', isCorrect: false })]

    expect(collectWrongKnowledgePointIds(report, results)).toEqual(['kp-10', 'kp-11'])
  })

  it('falls back to wrong attempt results when report has no weak points', () => {
    const results = [
      makeResult({ attemptItemId: 'a-1', knowledgePointId: 'kp-1', isCorrect: false }),
      makeResult({ attemptItemId: 'a-2', knowledgePointId: 'kp-1', isCorrect: false }),
      makeResult({ attemptItemId: 'a-3', knowledgePointId: 'kp-2', isCorrect: true }),
      makeResult({ attemptItemId: 'a-4', knowledgePointId: 'kp-3', isCorrect: null }),
      makeResult({ attemptItemId: 'a-5', knowledgePointId: undefined, isCorrect: false }),
    ]

    expect(collectWrongKnowledgePointIds(null, results)).toEqual(['kp-1'])
    expect(collectWrongKnowledgePointIds(makeReport(), results)).toEqual(['kp-1'])
  })

  it('maps weak knowledge points into view items with fallback explanations', () => {
    expect(buildWeakPointViews(null)).toEqual([])

    const report = makeReport({
      weak_knowledge_points: [
        {
          knowledge_point_id: 'kp-1',
          knowledge_name: '页面置换',
          current_score: 0.35,
          score_delta: -0.05,
          cause_explanation: '概念混淆',
          actionable_advice: '重做例题',
        },
        {
          knowledge_id: 'kp-2',
          knowledge_title: '虚拟内存',
          current_score: 0.2,
          score_delta: -0.1,
          cause_type: 'concept_gap',
        },
        {
          current_score: 0.1,
          score_delta: 0,
        },
      ],
    })

    expect(buildWeakPointViews(report)).toEqual([
      {
        id: 'kp-1',
        name: '页面置换',
        masteryRate: 0.35,
        reason: '概念混淆',
        suggestion: '重做例题',
      },
      {
        id: 'kp-2',
        name: '虚拟内存',
        masteryRate: 0.2,
        reason: 'concept_gap',
        suggestion: '建议针对性复习后再次练习',
      },
      {
        id: undefined,
        name: '未命名考点',
        masteryRate: 0.1,
        reason: '暂无归因说明',
        suggestion: '建议针对性复习后再次练习',
      },
    ])
  })
})

describe('resolveSessionScope & summarizeProgress', () => {
  it('resolves regenerate scope giving folder_id precedence over material_id', () => {
    expect(resolveSessionScope(null)).toEqual({ folderId: undefined, materialId: undefined })
    expect(
      resolveSessionScope({
        id: 'p-1',
        title: '测验',
        status: 'completed',
        folder_id: 'f-1',
        material_id: 'm-1',
        questions: [],
        total_count: 0,
      } as PracticeSession),
    ).toEqual({ folderId: 'f-1', materialId: undefined })
    expect(
      resolveSessionScope({
        id: 'p-2',
        title: '测验',
        status: 'completed',
        folder_id: null,
        material_id: 'm-2',
        questions: [],
        total_count: 0,
      } as PracticeSession),
    ).toEqual({ folderId: undefined, materialId: 'm-2' })
  })

  it('summarizes grading progress accurately across empty, partial, and completed sessions', () => {
    expect(summarizeProgress(null)).toEqual({
      total: 0,
      graded: 0,
      grading: 0,
      pendingRegrade: 0,
      unanswered: 0,
      fullyGraded: false,
    })

    const partial = adaptPractice({
      practice_id: 'p-partial',
      title: '半判练习',
      status: 'partially_graded',
      total_count: 4,
      completed_at: null,
      items: [
        {
          attempt_item_id: 'a-1',
          question_id: 'q-1',
          order_index: 1,
          status: 'graded',
          is_answered: true,
          score: 1,
          grading_status: 'graded',
          max_score: 1,
          question_snapshot: { id: 'q-1', question_type: 'single_choice', stem: '1' },
        },
        {
          attempt_item_id: 'a-2',
          question_id: 'q-2',
          order_index: 2,
          status: 'submitted',
          is_answered: true,
          score: null,
          grading_status: null,
          max_score: 1,
          question_snapshot: { id: 'q-2', question_type: 'short_answer', stem: '2' },
        },
        {
          attempt_item_id: 'a-3',
          question_id: 'q-3',
          order_index: 3,
          status: 'pending_regrade',
          is_answered: true,
          score: null,
          grading_status: 'pending_regrade',
          max_score: 5,
          question_snapshot: { id: 'q-3', question_type: 'short_answer', stem: '3' },
        },
        {
          attempt_item_id: 'a-4',
          question_id: 'q-4',
          order_index: 4,
          status: 'unanswered',
          is_answered: false,
          score: null,
          grading_status: 'unanswered',
          max_score: 1,
          question_snapshot: { id: 'q-4', question_type: 'single_choice', stem: '4' },
        },
      ],
    })
    expect(summarizeProgress(partial)).toEqual({
      total: 4,
      graded: 1,
      grading: 1,
      pendingRegrade: 1,
      unanswered: 1,
      fullyGraded: false,
    })

    const finished = adaptPractice({
      practice_id: 'p-done',
      title: '完成练习',
      status: 'completed',
      total_count: 1,
      completed_at: '2026-11-17T10:00:00',
      items: [
        {
          attempt_item_id: 'a-1',
          question_id: 'q-1',
          order_index: 1,
          status: 'graded',
          is_answered: true,
          score: 1,
          grading_status: 'graded',
          max_score: 1,
          question_snapshot: { id: 'q-1', question_type: 'single_choice', stem: '1' },
        },
      ],
    })
    expect(summarizeProgress(finished)).toEqual({
      total: 1,
      graded: 1,
      grading: 0,
      pendingRegrade: 0,
      unanswered: 0,
      fullyGraded: true,
    })
  })
})
