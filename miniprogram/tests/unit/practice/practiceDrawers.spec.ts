import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import AnswerSheetDrawer from '@/subpackages/practice/components/AnswerSheetDrawer.vue';
import SubmitConfirmModal from '@/subpackages/practice/components/SubmitConfirmModal.vue';

describe('AnswerSheetDrawer.vue', () => {
  const questionIds = ['q1', 'q2', 'q3', 'q4', 'q5'];
  const sampleAnswers = {
    q1: 'A',
    q2: ['B', 'C'],
    q3: '',
    q4: null,
    // q5 undefined
  };

  it('does not render content when visible is false', () => {
    const wrapper = mount(AnswerSheetDrawer, {
      props: {
        visible: false,
        totalCount: 5,
        currentIndex: 0,
        answers: sampleAnswers,
        questionIds,
      },
    });

    expect(wrapper.find('.sheet-drawer').exists()).toBe(false);
  });

  it('renders title, progress subtitle, and cell grid when visible is true', () => {
    const wrapper = mount(AnswerSheetDrawer, {
      props: {
        visible: true,
        totalCount: 5,
        currentIndex: 2, // q3 is current
        answers: sampleAnswers,
        questionIds,
      },
    });

    expect(wrapper.text()).toContain('答题卡');
    expect(wrapper.text()).toContain('已完成 2/5');

    const cells = wrapper.findAll('.sheet-cell');
    expect(cells).toHaveLength(5);

    // q1 (index 0): answered
    expect(cells[0].classes()).toContain('cell-answered');
    // q2 (index 1): answered
    expect(cells[1].classes()).toContain('cell-answered');
    // q3 (index 2): current has highest priority
    expect(cells[2].classes()).toContain('cell-current');
    // q4 (index 3): unanswered
    expect(cells[3].classes()).toContain('cell-unanswered');
    // q5 (index 4): unanswered
    expect(cells[4].classes()).toContain('cell-unanswered');
  });

  it('emits select and update:visible false when a cell is tapped', async () => {
    const wrapper = mount(AnswerSheetDrawer, {
      props: {
        visible: true,
        totalCount: 5,
        currentIndex: 0,
        answers: sampleAnswers,
        questionIds,
      },
    });

    const cells = wrapper.findAll('.sheet-cell');
    await cells[3].trigger('tap'); // tap 4th question (index 3)

    expect(wrapper.emitted('select')).toBeTruthy();
    expect(wrapper.emitted('select')?.[0]).toEqual([3]);

    expect(wrapper.emitted('update:visible')).toBeTruthy();
    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
  });

  it('emits update:visible false when close button or mask is clicked', async () => {
    const wrapper = mount(AnswerSheetDrawer, {
      props: {
        visible: true,
        totalCount: 5,
        currentIndex: 0,
        questionIds,
      },
    });

    const closeBtn = wrapper.find('.close-btn');
    await closeBtn.trigger('tap');
    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);

    const mask = wrapper.find('.sheet-mask');
    await mask.trigger('tap');
    expect(wrapper.emitted('update:visible')?.[1]).toEqual([false]);
  });

  it('strictly adheres to zero-emoji policy', () => {
    const wrapper = mount(AnswerSheetDrawer, {
      props: {
        visible: true,
        totalCount: 5,
        currentIndex: 0,
        answers: sampleAnswers,
        questionIds,
      },
    });
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });
});

describe('SubmitConfirmModal.vue', () => {
  it('does not render modal card when visible is false', () => {
    const wrapper = mount(SubmitConfirmModal, {
      props: {
        visible: false,
        totalCount: 10,
        answeredCount: 8,
        unansweredIndices: [3, 7],
      },
    });

    expect(wrapper.find('.modal-card').exists()).toBe(false);
  });

  it('renders unanswered warning and chip buttons when unanswered questions exist', async () => {
    const wrapper = mount(SubmitConfirmModal, {
      props: {
        visible: true,
        totalCount: 10,
        answeredCount: 8,
        unansweredIndices: [3, 7],
      },
    });

    expect(wrapper.text()).toContain('交卷确认');
    expect(wrapper.text()).toContain('总题数');
    expect(wrapper.text()).toContain('10');
    expect(wrapper.text()).toContain('8');
    expect(wrapper.text()).toContain('2');
    expect(wrapper.text()).toContain('尚有 2 道题目未作答');

    const chips = wrapper.findAll('.chip-item');
    expect(chips).toHaveLength(2);
    expect(chips[0].text()).toBe('第 3 题');
    expect(chips[1].text()).toBe('第 7 题');

    // Click chip to locate
    await chips[0].trigger('tap');
    expect(wrapper.emitted('locate-unanswered')).toBeTruthy();
    expect(wrapper.emitted('locate-unanswered')?.[0]).toEqual([2]); // 0-based
    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
  });

  it('emits confirm with confirm_unanswered: true when confirmed with unanswered questions', async () => {
    const wrapper = mount(SubmitConfirmModal, {
      props: {
        visible: true,
        totalCount: 5,
        answeredCount: 3,
        unansweredIndices: [2, 5],
      },
    });

    const submitBtn = wrapper.find('.btn-primary');
    expect(submitBtn.text()).toBe('仍要交卷');

    await submitBtn.trigger('tap');
    expect(wrapper.emitted('confirm')).toBeTruthy();
    expect(wrapper.emitted('confirm')?.[0]).toEqual([{ confirm_unanswered: true }]);

    const cancelBtn = wrapper.find('.btn-secondary');
    expect(cancelBtn.text()).toBe('继续作答');
    await cancelBtn.trigger('tap');
    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
  });

  it('renders all-completed branch and emits confirm_unanswered: false when fully answered', async () => {
    const wrapper = mount(SubmitConfirmModal, {
      props: {
        visible: true,
        totalCount: 5,
        answeredCount: 5,
        unansweredIndices: [],
      },
    });

    expect(wrapper.text()).toContain('已完成全部题目作答');
    const submitBtn = wrapper.find('.btn-primary');
    expect(submitBtn.text()).toBe('确认交卷');

    await submitBtn.trigger('tap');
    expect(wrapper.emitted('confirm')).toBeTruthy();
    expect(wrapper.emitted('confirm')?.[0]).toEqual([{ confirm_unanswered: false }]);

    const cancelBtn = wrapper.find('.btn-secondary');
    expect(cancelBtn.text()).toBe('再检查一下');
    await cancelBtn.trigger('tap');
    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
  });

  it('disables interactions and displays submitting status during submission', async () => {
    const wrapper = mount(SubmitConfirmModal, {
      props: {
        visible: true,
        totalCount: 5,
        answeredCount: 5,
        unansweredIndices: [],
        submitting: true,
      },
    });

    const submitBtn = wrapper.find('.btn-primary');
    expect(submitBtn.text()).toBe('交卷中...');
    expect(submitBtn.classes()).toContain('disabled');

    await submitBtn.trigger('tap');
    expect(wrapper.emitted('confirm')).toBeFalsy();

    const cancelBtn = wrapper.find('.btn-secondary');
    await cancelBtn.trigger('tap');
    expect(wrapper.emitted('update:visible')).toBeFalsy();
  });

  it('strictly adheres to zero-emoji policy', () => {
    const wrapper = mount(SubmitConfirmModal, {
      props: {
        visible: true,
        totalCount: 10,
        answeredCount: 8,
        unansweredIndices: [3, 7],
      },
    });
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });
});
