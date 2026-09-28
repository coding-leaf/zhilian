import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount, flushPromises } from '@vue/test-utils';
import VerifyPage from '@/subpackages/material/pages/verify/index.vue';
import * as questionApi from '@/api/question';
import * as practiceApi from '@/api/practice';
import type { QuestionItem } from '@/types/question';

describe('Question Verify Checklist Page (verify/index.vue)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  const mockQuestions: QuestionItem[] = [
    {
      id: 'q_1',
      material_id: 'mat_100',
      version_id: 'v_1',
      knowledge_point_id: 'kp_1',
      question_type: 'single_choice',
      stem: '以下哪种排序算法在最坏情况下的时间复杂度仍为 O(n log n)？',
      options: [
        { key: 'A', text: '快速排序' },
        { key: 'B', text: '归并排序' },
        { key: 'C', text: '冒泡排序' },
        { key: 'D', text: '插入排序' },
      ],
      answer: 'B',
      difficulty: 3,
      source_snippet_id: 'snip_1',
    },
    {
      id: 'q_2',
      material_id: 'mat_100',
      version_id: 'v_1',
      knowledge_point_id: 'kp_2',
      question_type: 'short_answer',
      stem: '请简述平衡二叉树（AVL树）的平衡因子定义及其失衡调整策略。',
      answer: '平衡因子为左子树高度减去右子树高度，只能是 -1, 0, 1。',
      difficulty: 4,
    },
  ];

  it('renders verify page title and zero Unicode emoji', () => {
    const wrapper = mount(VerifyPage);
    expect(wrapper.text()).toContain('出题核验清单');

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });

  it('loads and displays question checklist with source citation toggle', async () => {
    vi.spyOn(questionApi, 'fetchQuestionList').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: mockQuestions,
        total: 2,
        limit: 50,
        offset: 0,
      },
    });

    const wrapper = mount(VerifyPage);
    // Trigger onLoad simulation
    // @ts-expect-error test trigger
    wrapper.vm.materialId = 'mat_100';
    // @ts-expect-error test trigger
    await wrapper.vm.loadExistingQuestions();
    await flushPromises();

    expect(wrapper.text()).toContain('已质检通过题目 (2 题)');
    expect(wrapper.text()).toContain('归并排序');
    expect(wrapper.text()).toContain('查看出处讲义原文');

    // Toggle citation
    const citationBtn = wrapper.findAll('.citation-toggle')[0];
    await citationBtn.trigger('tap');
    await flushPromises();

    expect(wrapper.text()).toContain('收起出处讲义原文');
  });

  it('allows question deletion and updates verified count', async () => {
    vi.spyOn(questionApi, 'deleteQuestion').mockResolvedValue({
      code: 0,
      message: 'success',
      data: { id: 'q_1', is_deleted: true },
    });

    (globalThis as unknown as { uni: Record<string, unknown> }).uni.showModal = vi.fn(
      (options: unknown) => {
        const opt = options as { success: (res: { confirm: boolean }) => void };
        opt.success({ confirm: true });
        return Promise.resolve();
      },
    );

    const wrapper = mount(VerifyPage);
    // @ts-expect-error test trigger
    wrapper.vm.materialId = 'mat_100';
    // @ts-expect-error test trigger
    wrapper.vm.questions = [...mockQuestions];
    await flushPromises();

    expect(wrapper.text()).toContain('已核验 2 道优质题目');

    const deleteBtns = wrapper.findAll('.btn-card-action.danger');
    await deleteBtns[0].trigger('tap');
    await flushPromises();

    expect(wrapper.text()).toContain('已核验 1 道优质题目');
  });

  it('starts practice session and navigates to session page', async () => {
    const createPracticeSpy = vi.spyOn(practiceApi, 'createPractice').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'prac_verify_123',
        title: '测试练习',
        status: 'in_progress',
        created_at: '2026-09-28T00:00:00Z',
        items: [],
        questions: [],
      },
    });
    const navigateSpy = vi.spyOn(uni, 'navigateTo');

    const wrapper = mount(VerifyPage);
    // @ts-expect-error test trigger
    wrapper.vm.materialId = 'mat_100';
    // @ts-expect-error test trigger
    wrapper.vm.questions = [...mockQuestions];
    await flushPromises();

    const startBtn = wrapper.find('.btn-start-practice');
    await startBtn.trigger('tap');
    await flushPromises();

    expect(createPracticeSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        material_id: 'mat_100',
        question_ids: ['q_1', 'q_2'],
      }),
    );

    await new Promise((r) => setTimeout(r, 500));
    expect(navigateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/subpackages/practice/pages/session/index?id=prac_verify_123',
      }),
    );
  });
});
