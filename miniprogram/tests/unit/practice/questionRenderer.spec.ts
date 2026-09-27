import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import OptionCard from '@/subpackages/practice/components/OptionCard.vue';
import QuestionRenderer, {
  type RendererQuestion,
} from '@/subpackages/practice/components/QuestionRenderer.vue';

describe('OptionCard.vue', () => {
  it('renders option key and content correctly', () => {
    const wrapper = mount(OptionCard, {
      props: {
        optionKey: 'A',
        content: '进程具有动态性与并发性',
      },
    });

    expect(wrapper.text()).toContain('A.');
    expect(wrapper.text()).toContain('进程具有动态性与并发性');
    expect(wrapper.classes()).not.toContain('selected');
  });

  it('renders radio indicator by default and checkbox indicator when specified', () => {
    const radioWrapper = mount(OptionCard, {
      props: {
        optionKey: 'A',
        content: '单选选项',
        type: 'radio',
      },
    });
    expect(radioWrapper.find('.indicator-radio').exists()).toBe(true);

    const checkWrapper = mount(OptionCard, {
      props: {
        optionKey: 'B',
        content: '多选选项',
        type: 'checkbox',
        selected: true,
      },
    });
    expect(checkWrapper.find('.indicator-checkbox').exists()).toBe(true);
    expect(checkWrapper.find('.indicator-checkbox.active').exists()).toBe(true);
    expect(checkWrapper.classes()).toContain('selected');
  });

  it('emits select event when tapped', async () => {
    const wrapper = mount(OptionCard, {
      props: {
        optionKey: 'C',
        content: '测试可点击',
      },
    });

    await wrapper.trigger('tap');
    expect(wrapper.emitted('select')).toBeTruthy();
    expect(wrapper.emitted('select')?.[0]).toEqual(['C']);
  });

  it('does not emit select event when disabled', async () => {
    const wrapper = mount(OptionCard, {
      props: {
        optionKey: 'D',
        content: '禁用卡片',
        disabled: true,
      },
    });

    await wrapper.trigger('tap');
    expect(wrapper.emitted('select')).toBeFalsy();
  });

  it('strictly adheres to zero-emoji policy', () => {
    const wrapper = mount(OptionCard, {
      props: {
        optionKey: 'A',
        content: '无表情纯净选项',
      },
    });
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });
});

describe('QuestionRenderer.vue', () => {
  const singleChoiceQ: RendererQuestion = {
    id: 'q_sc_1',
    stem: '以下哪项属于操作系统的基本特征？',
    question_type: 'single_choice',
    options: [
      { key: 'A', text: '并发性' },
      { key: 'B', text: '孤立性' },
      { key: 'C', text: '单调性' },
    ],
  };

  const multiChoiceQ: RendererQuestion = {
    id: 'q_mc_1',
    stem: '关于死锁产生的必要条件，包括哪些？',
    question_type: 'multiple_choice',
    options: [
      { key: 'A', text: '互斥条件' },
      { key: 'B', text: '不剥夺条件' },
      { key: 'C', text: '请求和保持条件' },
      { key: 'D', text: '循环等待条件' },
    ],
  };

  const trueFalseQ: RendererQuestion = {
    id: 'q_tf_1',
    stem: '线程是资源分配的基本单位。',
    question_type: 'true_false',
  };

  const blankQ: RendererQuestion = {
    id: 'q_fib_1',
    stem: '存储管理中，页式存储通过______将逻辑地址转换为物理地址。',
    question_type: 'fill_in_blank',
  };

  const shortAnswerQ: RendererQuestion = {
    id: 'q_sa_1',
    stem: '简述进程与线程的核心区别。',
    question_type: 'short_answer',
  };

  const termExplanationQ: RendererQuestion = {
    id: 'q_te_1',
    stem: '请解释名词：进程。',
    question_type: 'term_explanation',
  };

  const caseAnalysisQ: RendererQuestion = {
    id: 'q_ca_1',
    stem: '结合案例说明死锁的预防策略。',
    question_type: 'case_analysis',
  };

  it('renders single choice question and handles single option selection', async () => {
    const wrapper = mount(QuestionRenderer, {
      props: {
        question: singleChoiceQ,
        modelValue: 'A',
        orderIndex: 1,
      },
    });

    expect(wrapper.text()).toContain('单选题');
    expect(wrapper.text()).toContain('第 1 题');
    expect(wrapper.text()).toContain('以下哪项属于操作系统的基本特征？');

    const cards = wrapper.findAllComponents(OptionCard);
    expect(cards).toHaveLength(3);
    expect(cards[0].props('selected')).toBe(true);
    expect(cards[1].props('selected')).toBe(false);

    // Click option B
    await cards[1].trigger('tap');
    expect(wrapper.emitted('update:modelValue')).toBeTruthy();
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['B']);
  });

  it('renders multiple choice question and supports toggle multi-select with sorting', async () => {
    const wrapper = mount(QuestionRenderer, {
      props: {
        question: multiChoiceQ,
        modelValue: ['A', 'C'],
        orderIndex: 2,
      },
    });

    expect(wrapper.text()).toContain('多选题');
    const cards = wrapper.findAllComponents(OptionCard);
    expect(cards).toHaveLength(4);
    expect(cards[0].props('selected')).toBe(true);
    expect(cards[1].props('selected')).toBe(false);
    expect(cards[2].props('selected')).toBe(true);

    // Toggle B (add)
    await cards[1].trigger('tap');
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([['A', 'B', 'C']]);

    // Update props to simulate v-model change
    await wrapper.setProps({ modelValue: ['A', 'B', 'C'] });

    // Toggle A (remove)
    await cards[0].trigger('tap');
    expect(wrapper.emitted('update:modelValue')?.[1]).toEqual([['B', 'C']]);
  });

  it('renders true/false question and allows toggling truth value', async () => {
    const wrapper = mount(QuestionRenderer, {
      props: {
        question: trueFalseQ,
        modelValue: 'T',
        orderIndex: 3,
      },
    });

    expect(wrapper.text()).toContain('判断题');
    const cards = wrapper.findAllComponents(OptionCard);
    expect(cards).toHaveLength(2);
    expect(cards[0].props('content')).toBe('正确');
    expect(cards[1].props('content')).toBe('错误');
    expect(cards[0].props('selected')).toBe(true);

    // Click 'F'
    await cards[1].trigger('tap');
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['F']);
  });

  it('renders fill in blank input and emits value on typing', async () => {
    const wrapper = mount(QuestionRenderer, {
      props: {
        question: blankQ,
        modelValue: '',
        orderIndex: 4,
      },
    });

    expect(wrapper.text()).toContain('填空题');
    const input = wrapper.find('.blank-input');
    expect(input.exists()).toBe(true);

    await input.trigger('input', { detail: { value: '页表' } });
    expect(wrapper.emitted('update:modelValue')).toBeTruthy();
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['页表']);
  });

  it('renders short answer textarea with character counter and emits updates', async () => {
    const wrapper = mount(QuestionRenderer, {
      props: {
        question: shortAnswerQ,
        modelValue: '进程是资源分配单位',
        orderIndex: 5,
      },
    });

    expect(wrapper.text()).toContain('简答题');
    expect(wrapper.find('.word-count').text()).toBe('9/500');

    const textarea = wrapper.find('.short-answer-textarea');
    expect(textarea.exists()).toBe(true);

    await textarea.trigger('input', { detail: { value: '新答案分析' } });
    expect(wrapper.emitted('update:modelValue')).toBeTruthy();
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['新答案分析']);
  });

  it('renders term explanation as a long text input with the correct label (PRAC-014)', async () => {
    const wrapper = mount(QuestionRenderer, {
      props: {
        question: termExplanationQ,
        modelValue: '',
        orderIndex: 6,
      },
    });

    expect(wrapper.text()).toContain('名词解释');
    const textarea = wrapper.find('.short-answer-textarea');
    expect(textarea.exists()).toBe(true);

    await textarea.trigger('input', { detail: { value: '进程是程序的一次执行过程' } });
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['进程是程序的一次执行过程']);
  });

  it('renders case analysis as a long text input with the correct label (PRAC-014)', async () => {
    const wrapper = mount(QuestionRenderer, {
      props: {
        question: caseAnalysisQ,
        modelValue: '',
        orderIndex: 7,
      },
    });

    expect(wrapper.text()).toContain('案例分析');
    const textarea = wrapper.find('.short-answer-textarea');
    expect(textarea.exists()).toBe(true);

    await textarea.trigger('input', { detail: { value: '采用资源有序分配法打破循环等待' } });
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['采用资源有序分配法打破循环等待']);
  });

  it('falls back to a subjective text area for unknown question types (PRAC-014)', () => {
    const wrapper = mount(QuestionRenderer, {
      props: {
        question: {
          id: 'q_unknown_1',
          stem: '未知主观题型题干',
          question_type: 'some_future_type',
        },
      },
    });

    expect(wrapper.text()).toContain('练习题');
    expect(wrapper.find('.short-answer-textarea').exists()).toBe(true);
  });

  it('strictly adheres to zero-emoji policy and natural copywriting', () => {
    const wrapper = mount(QuestionRenderer, {
      props: {
        question: singleChoiceQ,
        modelValue: 'A',
      },
    });

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
    expect(wrapper.text()).not.toContain('BM25');
    expect(wrapper.text()).not.toContain('match_and_grade_answer');
  });
});
