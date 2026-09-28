import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePracticeStore } from '@/stores/practice'
import { useFolderStore } from '@/stores/folder'

describe('Practice & Learning Workflow Unit Tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('correctly tracks answered count and unanswered count for multi-question session', () => {
    const store = usePracticeStore()
    store.currentSession = {
      id: 'p_1',
      title: '测试多题型练习',
      status: 'IN_PROGRESS',
      total_count: 4,
      submitted_count: 0,
      questions: [
        { id: 'q_1', type: 'single_choice', stem: '单选题干', answer: 'A' },
        { id: 'q_2', type: 'multiple_choice', stem: '多选题干', answer: ['A', 'B'] },
        { id: 'q_3', type: 'fill_in_blank', stem: '填空题干', answer: '贝叶斯定理' },
        { id: 'q_4', type: 'short_answer', stem: '简答题干', answer: '详细论述' },
      ],
      created_at: '2026-09-28',
    }

    expect(store.questions.length).toBe(4)
    expect(store.answeredCount).toBe(0)
    expect(store.unansweredCount).toBe(4)

    // 1. 作答单选
    store.recordAnswer('q_1', 'A')
    expect(store.answeredCount).toBe(1)
    expect(store.unansweredCount).toBe(3)

    // 2. 作答多选
    store.recordAnswer('q_2', ['A', 'B'])
    expect(store.answeredCount).toBe(2)
    expect(store.unansweredCount).toBe(2)

    // 3. 多选清空为空数组时不计入已作答
    store.recordAnswer('q_2', [])
    expect(store.answeredCount).toBe(1)
    expect(store.unansweredCount).toBe(3)

    // 4. 作答填空与主观题
    store.recordAnswer('q_3', '贝叶斯公式')
    store.recordAnswer('q_4', '先验概率转后验概率')
    expect(store.answeredCount).toBe(3)

    // 5. 游标切换
    expect(store.currentIndex).toBe(0)
    store.nextQuestion()
    expect(store.currentIndex).toBe(1)
    store.jumpTo(3)
    expect(store.currentIndex).toBe(3)
    store.prevQuestion()
    expect(store.currentIndex).toBe(2)
  })

  it('folderStore initializes and manages folder state correctly', () => {
    const folderStore = useFolderStore()
    expect(folderStore.folders).toEqual([])
    expect(folderStore.currentFolderId).toBe('all')

    folderStore.setCurrentFolderId('folder_123')
    expect(folderStore.currentFolderId).toBe('folder_123')
  })
})

