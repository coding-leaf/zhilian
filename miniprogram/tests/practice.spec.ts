import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePracticeStore } from '@/stores/practice'
import { useFolderStore } from '@/stores/folder'
import {
  collectLegacyTrueFalseUpgrades,
  isSingleOrTrueFalseSelected,
  joinFillBlankAnswers,
  normalizeMultipleSelection,
  normalizeTrueFalseValue,
  resolveFillBlankCount,
  resolveTrueFalseOptions,
  splitFillBlankAnswers,
  toggleMultipleSelection,
} from '@/subpackages/practice/utils/practiceSession'

describe('Practice & Learning Workflow Unit Tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('correctly tracks answered count and unanswered count for multi-question session', () => {
    const store = usePracticeStore()
    store.currentSession = {
      id: 'p_1',
      title: '测试多题型练习',
      status: 'in_progress',
      total_count: 4,
      completed_count: 0,
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

  it('normalizes true_false options and legacy draft answers to canonical 正确/错误', () => {
    expect(normalizeTrueFalseValue('A')).toBe('正确')
    expect(normalizeTrueFalseValue('T')).toBe('正确')
    expect(normalizeTrueFalseValue('正确')).toBe('正确')
    expect(normalizeTrueFalseValue('B')).toBe('错误')
    expect(normalizeTrueFalseValue('F')).toBe('错误')
    expect(normalizeTrueFalseValue('错误')).toBe('错误')

    const opts = resolveTrueFalseOptions([
      { key: 'A', content: '正确' },
      { key: 'B', content: '错误' },
    ])
    expect(opts).toEqual([
      { key: '正确', content: '正确' },
      { key: '错误', content: '错误' },
    ])

    expect(isSingleOrTrueFalseSelected('true_false', 'A', '正确')).toBe(true)
    expect(isSingleOrTrueFalseSelected('true_false', 'F', '错误')).toBe(true)
    expect(isSingleOrTrueFalseSelected('true_false', 'A', '错误')).toBe(false)

    const upgrades = collectLegacyTrueFalseUpgrades(
      [
        { id: 'q-tf-1', type: 'true_false', stem: '判断题 1' },
        { id: 'q-tf-2', type: 'true_false', stem: '判断题 2' },
        { id: 'q-tf-3', type: 'true_false', stem: '判断题 3' },
      ],
      { 'q-tf-1': 'A', 'q-tf-2': 'F', 'q-tf-3': '正确' },
    )
    expect(upgrades).toEqual([
      { questionId: 'q-tf-1', answer: '正确' },
      { questionId: 'q-tf-2', answer: '错误' },
    ])
  })

  it('supports multi-choice array toggling and multi-blank fill_in_blank split/join', () => {
    expect(normalizeMultipleSelection('["C","A"]')).toEqual(['C', 'A'])
    expect(toggleMultipleSelection(['A'], 'C')).toEqual(['A', 'C'])
    expect(toggleMultipleSelection(['A', 'C'], 'A')).toEqual(['C'])

    expect(resolveFillBlankCount('先验概率是____，似然度是（）')).toBe(2)
    expect(resolveFillBlankCount('公式 $P(Y=c_k|X=x_j)$ 中唯一空白是____')).toBe(1)
    expect(resolveFillBlankCount('请填写两个术语', '先验; 后验')).toBe(2)

    expect(splitFillBlankAnswers('先验概率; 后验概率', 2)).toEqual(['先验概率', '后验概率'])
    expect(joinFillBlankAnswers(['先验概率', '后验概率'])).toBe('先验概率; 后验概率')
    expect(joinFillBlankAnswers(['', '   '])).toBe('')
  })
})
