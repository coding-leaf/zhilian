import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePracticeStore } from '@/stores/practice'

describe('usePracticeStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('correctly tracks answered count and unanswered count', () => {
    const store = usePracticeStore()
    // 模拟 session
    store.currentSession = {
      id: 'p_1',
      title: '测试练习',
      status: 'IN_PROGRESS',
      total_count: 3,
      submitted_count: 0,
      questions: [
        { id: 'q_1', material_id: 'm_1', type: 'single_choice', stem: 'Q1', answer: 'A' },
        { id: 'q_2', material_id: 'm_1', type: 'single_choice', stem: 'Q2', answer: 'B' },
        { id: 'q_3', material_id: 'm_1', type: 'single_choice', stem: 'Q3', answer: 'C' },
      ],
      created_at: '2026-09-28',
    }

    expect(store.questions.length).toBe(3)
    expect(store.answeredCount).toBe(0)
    expect(store.unansweredCount).toBe(3)

    // 作答第一题
    store.recordAnswer('q_1', 'A')
    expect(store.answeredCount).toBe(1)
    expect(store.unansweredCount).toBe(2)

    // 切换题目
    expect(store.currentIndex).toBe(0)
    store.nextQuestion()
    expect(store.currentIndex).toBe(1)
    store.prevQuestion()
    expect(store.currentIndex).toBe(0)
  })
})
