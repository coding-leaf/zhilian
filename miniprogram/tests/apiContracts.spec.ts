import { describe, expect, it } from 'vitest'
import { adaptMaterial, adaptPractice, adaptQuestion } from '../src/api'

describe('backend response adapters', () => {
  it('normalizes material status without losing parse progress fields', () => {
    const material = adaptMaterial({
      id: 'm-1', title: '讲义', status: 'READY', created_at: '2026-01-01',
      parse_status: 'ready', progress_percentage: 100,
    })

    expect(material).toMatchObject({ status: 'ready', parse_status: 'ready', progress_percentage: 100 })
  })

  it('maps question_type and keyed options into the view model', () => {
    const question = adaptQuestion({
      id: 'q-1', question_type: 'single_choice', stem: '选择',
      options: [{ key: 'A', content: '选项一' }], answer: 'A', analysis: '解析',
      grading_rubric: { total_score: 5, points: [{ point: '说明原因', score: 5 }] },
    })

    expect(question).toMatchObject({
      type: 'single_choice', options: [{ key: 'A', content: '选项一' }], explanation: '解析',
      grading_points: ['说明原因'], max_score: 5,
    })
    // 题目详情响应不含切片正文，source_quote 只可能来自练习详情响应
    expect(question.source_quote).toBeUndefined()
  })

  it('projects practice items from question_snapshot and retains grading state', () => {
    const practice = adaptPractice({
      practice_id: 'p-1', title: '练习', status: 'submitted', total_count: 1,
      completed_count: 1,
      items: [{
        attempt_item_id: 'a-1', question_id: 'q-1', order_index: 1,
        status: 'graded', is_answered: true, user_answer: 'A', score: 1,
        grading_status: 'graded', max_score: 1,
        question_snapshot: {
          id: 'q-snapshot', question_type: 'single_choice', stem: '选择',
          options: [{ key: 'A', content: '选项一' }], answer: 'A',
        },
      }],
    })

    expect(practice.id).toBe('p-1')
    expect(practice.questions[0]).toMatchObject({ id: 'q-1', type: 'single_choice' })
    expect(practice.items?.[0]).toMatchObject({ grading_status: 'graded', user_answer: 'A' })
  })
})
