import { describe, expect, it } from 'vitest'
import { adaptPractice, adaptDiagnosisReport, adaptQuestion, needsGradingRetry } from '../src/api'
import { buildAttemptResults, summarizeProgress } from '../src/api/adapters/practice'
import { adaptMaterial } from '../src/api/adapters/material'
import {
  buildWrongGroupOptions,
  recordsInGroup,
  resolveRegenerateScope,
  wrongSnapshotStem,
  type WireWrongRecordItem,
} from '../src/api/adapters/wrong'
import {
  computeKnowledgeCoverage,
  planGenerationBatches,
} from '../src/api/adapters/question'
import {
  diagnosisReportFixture,
  generatedQuestionFixture,
  practiceDetailFixture,
  practiceItemWithSourceSnippetFixture,
  wrongRecordsFixture,
} from './fixtures/backendResponses'

describe('backend wire contract -> view projection', () => {
  it('projects practice items from items[].question_snapshot and keeps grading state', () => {
    const session = adaptPractice(practiceDetailFixture as any)

    expect(session.id).toBe('p-1')
    expect(session.questions).toHaveLength(3)
    expect(session.questions[0]).toMatchObject({ id: 'q-1', type: 'single_choice' })
    expect(session.user_answers).toEqual({ 'q-1': 'A', 'q-2': '我的论述' })
    expect(session.items?.[1].grading_status).toBe('pending_regrade')
  })

  it('does not mark grading / unanswered items as wrong or zero-scored', () => {
    const results = buildAttemptResults(adaptPractice(practiceDetailFixture as any))

    const graded = results[0]
    expect(graded).toMatchObject({ isCorrect: true, score: 1, gradingStatus: 'graded', isPending: false })

    const pending = results[1]
    expect(pending.score).toBeNull()
    expect(pending.isCorrect).toBeNull()
    expect(pending.isPending).toBe(true)
    expect(pending.gradingStatus).toBe('pending_regrade')
    expect(pending.hitKeywords).toEqual([])
    expect(pending.missingKeywords).toEqual(['拥塞控制'])

    const unanswered = results[2]
    expect(unanswered.isAnswered).toBe(false)
    expect(unanswered.isCorrect).toBeNull()
    expect(unanswered.score).toBeNull()
    expect(unanswered.gradingStatus).toBe('unanswered')

    const progress = summarizeProgress(adaptPractice(practiceDetailFixture as any))
    expect(progress).toMatchObject({
      total: 3, graded: 1, pendingRegrade: 1, unanswered: 1, fullyGraded: false,
    })
  })

  it('only reports fullyGraded after completed_at is persisted', () => {
    const gradedItems = (practiceDetailFixture.items as any[]).map((item) => ({
      ...item,
      score: item.score ?? 1,
      grading_status: 'graded',
    }))
    const completed = adaptPractice({
      ...(practiceDetailFixture as any),
      status: 'completed',
      completed_at: '2026-09-28T12:00:00',
      items: gradedItems,
    } as any)

    expect(summarizeProgress(completed).fullyGraded).toBe(true)
  })

  it('consumes only real diagnosis fields (no details/score/accuracy)', () => {
    const report = adaptDiagnosisReport(diagnosisReportFixture as any)

    expect(report.score_rate).toBe(0.7)
    expect(report.pending_regrade_count).toBe(1)
    expect(report.wrong_count).toBe(1)
    expect(report.weak_knowledge_points[0]).toMatchObject({
      knowledge_point_id: 'k-1',
      knowledge_name: '拥塞控制',
      current_score: 0.3,
      actionable_advice: '重读第 3.4 节并重做练习',
    })
    expect('details' in report).toBe(false)
  })

  it('normalizes question_type, keyed options and rubric points', () => {
    const question = adaptQuestion(generatedQuestionFixture() as any)

    expect(question).toMatchObject({
      id: 'q-new-1',
      type: 'single_choice',
      options: [
        { key: 'A', content: '窗口指数增长' },
        { key: 'B', content: '窗口线性增长' },
      ],
    })
    // 题目的来源正文经 source_snippet 下发，断言见下方 source_quote 用例
  })

  it('maps source_quote from the real question response source_snippet', () => {
    // 题目侧来源正文的事实源：QuestionService.attach_source_snippets（按 source_snippet_id 批量装配）
    const question = adaptQuestion(generatedQuestionFixture() as any)

    expect(question.source_quote).toBe('慢启动阶段拥塞窗口指数增长，直到达到慢启动阈值。')
  })

  it('keeps source_quote empty when the question has no source snippet', () => {
    // 无来源（历史数据 / 切片已删除）时后端返回 null，前端据此渲染空态
    const question = adaptQuestion(generatedQuestionFixture({ source_snippet: null }) as any)

    expect(question.source_quote).toBeUndefined()
  })

  it('maps source_quote from the real practice answer-item source_snippet', () => {
    const [result] = buildAttemptResults(adaptPractice(practiceItemWithSourceSnippetFixture as any))

    expect(result.sourceQuote).toBe('慢启动阶段拥塞窗口指数增长，直到达到慢启动阈值。')
    expect(result.gradingStatus).toBe('graded')
    // 快照副本同样携带切片对象，练习页/结果页共用同一投影
    const snapshot = (practiceItemWithSourceSnippetFixture as any).items[0].question_snapshot
    expect(adaptQuestion({ ...snapshot, id: 'q-source-1' }).source_quote)
      .toBe('慢启动阶段拥塞窗口指数增长，直到达到慢启动阈值。')
  })

  it('flags grading retry only for partially_graded sessions', () => {
    expect(needsGradingRetry(adaptPractice(practiceDetailFixture as any))).toBe(true)
    expect(
      needsGradingRetry(
        adaptPractice({ ...(practiceDetailFixture as any), status: 'submitted' } as any),
      ),
    ).toBe(false)
    expect(
      needsGradingRetry(
        adaptPractice({ ...(practiceDetailFixture as any), status: 'completed' } as any),
      ),
    ).toBe(false)
    expect(needsGradingRetry(null)).toBe(false)
  })

  it('lowers material status into the backend state machine union', () => {
    expect(adaptMaterial({ id: 'm-1', title: 'x', status: 'READY', created_at: '' } as any).status)
      .toBe('ready')
    expect(adaptMaterial({ id: 'm-1', title: 'x', status: 'UNKNOWN', created_at: '' } as any).status)
      .toBe('pending')
  })
})

describe('wrong record grouping and regenerate scope', () => {
  const records = wrongRecordsFixture.items as unknown as WireWrongRecordItem[]

  it('reads question stem from question_snapshot', () => {
    const [first] = records
    expect(wrongSnapshotStem(first as any)).toBe('简述 TCP 拥塞控制的主要阶段。')
  })

  it('groups into one course and one unclassified material', () => {
    const options = buildWrongGroupOptions(wrongRecordsFixture.groups as any)

    expect(options).toHaveLength(2)
    expect(options[0]).toMatchObject({ label: '计算机网络', folderId: 'f-1', unclassified: false })
    expect(options[1]).toMatchObject({ label: '未归档讲义', materialId: 'm-9', unclassified: true })
    expect(options[0].count).toBe(1)
  })

  it('scopes regenerate to exactly one course or one unclassified material', () => {
    const options = buildWrongGroupOptions(wrongRecordsFixture.groups as any)

    expect(resolveRegenerateScope(options[0])).toEqual({ folderId: 'f-1' })
    expect(resolveRegenerateScope(options[1])).toEqual({ materialId: 'm-9' })
    expect(resolveRegenerateScope(null)).toBeNull()
  })

  it('filters records by their group without mixing courses', () => {
    const options = buildWrongGroupOptions(wrongRecordsFixture.groups as any)

    expect(recordsInGroup(records as any, options[0]).map((item) => item.id)).toEqual(['w-1'])
    expect(recordsInGroup(records as any, options[1]).map((item) => item.id)).toEqual(['w-2'])
  })
})

describe('multi-point generation planning and coverage', () => {
  it('covers every selected point and respects the 20-item batch cap', () => {
    const kpIds = Array.from({ length: 45 }, (_, i) => `k-${i}`)
    const batches = planGenerationBatches(kpIds, 5)

    expect(batches).toHaveLength(3)
    expect(batches.every((batch) => batch.count <= 20)).toBe(true)
    const covered = batches.flatMap((batch) => batch.knowledgePointIds)
    expect(new Set(covered).size).toBe(45)
    expect(Math.max(...batches.map((batch) => batch.count))).toBe(20)
  })

  it('raises the target count to the number of selected knowledge points', () => {
    const batches = planGenerationBatches(['k-1', 'k-2', 'k-3', 'k-4'], 2)
    const total = batches.reduce((sum, batch) => sum + batch.count, 0)
    expect(total).toBeGreaterThanOrEqual(4)
  })

  it('reports coverage gaps instead of assuming generation success', () => {
    const questions = [
      adaptQuestion(generatedQuestionFixture({ id: 'q-a', knowledge_point_id: 'k-1' }) as any),
      adaptQuestion(generatedQuestionFixture({ id: 'q-b', knowledge_point_id: 'k-2' }) as any),
    ]
    const coverage = computeKnowledgeCoverage(questions, ['k-1', 'k-2', 'k-3'])

    expect(coverage.covered).toEqual(['k-1', 'k-2'])
    expect(coverage.missing).toEqual(['k-3'])
    expect(coverage.ratio).toBeCloseTo(2 / 3)
  })
})
