import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount, flushPromises } from '@vue/test-utils';
import ReviewPage from '@/pages/review/index.vue';
import * as diagnosisApi from '@/api/diagnosis';
import * as practiceApi from '@/api/practice';
import type { WrongRecordItem } from '@/types/report';

describe('Review & Wrong Book Page (review/index.vue)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  const mockRecords: WrongRecordItem[] = [
    {
      id: 'rec_1',
      practice_id: 'prac_1',
      question_id: 'q_101',
      knowledge_point_id: 'kp_1',
      question_type: 'single_choice',
      course_name: '数据结构',
      is_mastered: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      question_snapshot: {
        stem: '在哈希表中，解决冲突的常用方法不包括？',
        question_type: 'single_choice',
        answer: '分治法',
        analysis: '分治法是算法设计策略，而非散列表冲突解决策略。',
      },
      last_user_answer: '开放定址法',
    },
    {
      id: 'rec_2',
      practice_id: 'prac_2',
      question_id: 'q_102',
      knowledge_point_id: 'kp_2',
      question_type: 'short_answer',
      course_name: '操作系统',
      is_mastered: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      question_snapshot: {
        stem: '简述死锁产生的四个必要条件。',
        question_type: 'short_answer',
        answer: '互斥、占有且等待、不可抢占、循环等待。',
      },
    },
  ];

  it('renders mastery overview progress ring and zero Unicode emoji', async () => {
    vi.spyOn(diagnosisApi, 'fetchMasteryOverview').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        overall_mastery_score: 0.85,
        mastered_count: 17,
        proficient_count: 5,
        weak_count: 3,
        unlearned_count: 2,
      },
    });

    vi.spyOn(diagnosisApi, 'fetchWrongBook').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: mockRecords,
        total: 2,
        limit: 50,
        offset: 0,
      },
    });

    const wrapper = mount(ReviewPage);
    await flushPromises();

    expect(wrapper.text()).toContain('学情与掌握度');
    expect(wrapper.text()).toContain('85%');
    expect(wrapper.text()).toContain('总体掌握');
    expect(wrapper.text()).toContain('待攻克错题');

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });

  it('supports multi-select cart mechanism and generates practice with question_ids', async () => {
    vi.spyOn(diagnosisApi, 'fetchMasteryOverview').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        overall_mastery_score: 0.85,
        mastered_count: 17,
        proficient_count: 5,
        weak_count: 3,
        unlearned_count: 2,
      },
    });

    vi.spyOn(diagnosisApi, 'fetchWrongBook').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: mockRecords,
        total: 2,
        limit: 50,
        offset: 0,
      },
    });

    const createPracticeSpy = vi.spyOn(practiceApi, 'createPractice').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'prac_wrong_batch_77',
        title: '错题针对性重练',
        status: 'in_progress',
        created_at: '2026-09-28T00:00:00Z',
        items: [],
        questions: [],
      },
    });

    const wrapper = mount(ReviewPage);
    await flushPromises();

    // Toggle multi-select mode
    const selectToggle = wrapper.find('.toggle-text');
    await selectToggle.trigger('tap');
    await flushPromises();

    expect(wrapper.text()).toContain('取消勾选');

    // Click on cards to select them
    const cards = wrapper.findAll('.wrong-record-card');
    await cards[0].trigger('tap');
    await cards[1].trigger('tap');
    await flushPromises();

    expect(wrapper.text()).toContain('已勾选 2 题');

    // Trigger generate practice
    const batchBtn = wrapper.find('.btn-create-practice');
    await batchBtn.trigger('tap');
    await flushPromises();

    expect(createPracticeSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        question_ids: ['q_101', 'q_102'],
        source_type: 'wrong_record',
      }),
    );
  });

  it('allows single-question review and toggling mastery status', async () => {
    vi.spyOn(diagnosisApi, 'fetchMasteryOverview').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        overall_mastery_score: 0.85,
        mastered_count: 17,
        proficient_count: 5,
        weak_count: 3,
        unlearned_count: 2,
      },
    });

    vi.spyOn(diagnosisApi, 'fetchWrongBook').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: mockRecords,
        total: 2,
        limit: 50,
        offset: 0,
      },
    });

    const toggleSpy = vi.spyOn(diagnosisApi, 'toggleWrongRecordResolved').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'rec_1',
        is_mastered: true,
        mastered_at: new Date().toISOString(),
        message: 'success',
      },
    });

    const wrapper = mount(ReviewPage);
    await flushPromises();

    const toggleBtn = wrapper.findAll('.btn-toggle-mastery')[0];
    await toggleBtn.trigger('tap');
    await flushPromises();

    expect(toggleSpy).toHaveBeenCalledWith('rec_1', true);
  });
});
