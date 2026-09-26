import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import QuestionCard from '@/subpackages/material/components/QuestionCard.vue';
import type { QuestionItem } from '@/types/question';

describe('QuestionCard.vue', () => {
  const choiceQuestion: QuestionItem = {
    id: 'q_card_1',
    material_id: 'mat_001',
    version_id: 'ver_001',
    knowledge_point_id: 'kp_001',
    question_type: 'multiple_choice',
    stem: '以下哪些属于操作系统功能？',
    options: [
      { key: 'A', text: '进程管理' },
      { key: 'B', text: '内存管理' },
    ],
    answer: 'A,B',
    analysis: '操作系统负责进程与内存等资源管理。',
    difficulty: 2,
  };

  it('renders type badge, difficulty, stem, options, answer and emits actions', async () => {
    const wrapper = mount(QuestionCard, { props: { question: choiceQuestion } });

    const text = wrapper.text();
    expect(text).toContain('多选题');
    expect(text).toContain('难度 2');
    expect(text).toContain('以下哪些属于操作系统功能？');
    expect(wrapper.findAll('.q-option').length).toBe(2);

    await wrapper.find('.action-btn.primary').trigger('tap');
    expect(wrapper.emitted('edit')?.[0]?.[0]).toEqual(choiceQuestion);

    await wrapper.findAll('.action-btn')[1].trigger('tap');
    expect(wrapper.emitted('audit')?.[0]?.[0]).toBe('q_card_1');

    await wrapper.find('.action-btn.danger').trigger('tap');
    expect(wrapper.emitted('delete')?.[0]?.[0]).toBe('q_card_1');
  });

  it('hides options for short_answer questions', () => {
    const shortAnswer: QuestionItem = {
      ...choiceQuestion,
      id: 'q_card_2',
      question_type: 'short_answer',
    };

    const wrapper = mount(QuestionCard, { props: { question: shortAnswer } });

    expect(wrapper.findAll('.q-option').length).toBe(0);
    expect(wrapper.text()).toContain('主观简答题');
  });
});
