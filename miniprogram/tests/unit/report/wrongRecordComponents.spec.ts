import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import WrongRecordFilterBar from '@/subpackages/report/components/WrongRecordFilterBar.vue';
import WrongRecordCard from '@/subpackages/report/components/WrongRecordCard.vue';
import type { WrongRecordItem } from '@/types/report';

describe('WrongRecordFilterBar Component', () => {
  const filterBarMountOptions = {
    global: {
      stubs: {
        'scroll-view': {
          template: '<div class="scroll-view-stub"><slot /></div>',
        },
      },
    },
  };

  it('renders status tabs, question types, and error types', () => {
    const wrapper = mount(WrongRecordFilterBar, filterBarMountOptions);

    expect(wrapper.text()).toContain('全部');
    expect(wrapper.text()).toContain('待攻克');
    expect(wrapper.text()).toContain('已攻克');

    expect(wrapper.text()).toContain('单选');
    expect(wrapper.text()).toContain('多选');
    expect(wrapper.text()).toContain('概念性错误');
    expect(wrapper.text()).toContain('审题偏差');
  });

  it('emits filter-change when status tab is selected', async () => {
    const wrapper = mount(WrongRecordFilterBar, filterBarMountOptions);

    const tabs = wrapper.findAll('.status-tab-item');
    expect(tabs.length).toBe(3);

    // Tap '待攻克' (index 1)
    await tabs[1].trigger('tap');

    expect(wrapper.emitted('filter-change')).toBeTruthy();
    const emittedEvents = wrapper.emitted('filter-change')!;
    expect(emittedEvents[0][0]).toEqual({
      material_id: undefined,
      is_mastered: false,
    });

    // Tap '已攻克' (index 2)
    await tabs[2].trigger('tap');
    expect(emittedEvents[1][0]).toEqual({
      material_id: undefined,
      is_mastered: true,
    });
  });

  it('emits filter-change when question type and error type are selected', async () => {
    const wrapper = mount(WrongRecordFilterBar, filterBarMountOptions);

    const capsules = wrapper.findAll('.filter-capsule');
    // Find single_choice
    const singleChoiceCapsule = capsules.find((c) => c.text().includes('单选'));
    expect(singleChoiceCapsule).toBeDefined();
    await singleChoiceCapsule!.trigger('tap');

    const emitted = wrapper.emitted('filter-change')!;
    expect(emitted[emitted.length - 1][0]).toMatchObject({
      question_type: 'single_choice',
    });

    // Find deviation error type (standard enum value)
    const deviationCapsule = capsules.find((c) => c.text().includes('审题偏差'));
    expect(deviationCapsule).toBeDefined();
    await deviationCapsule!.trigger('tap');

    const lastEmitted = wrapper.emitted('filter-change')!;
    expect(lastEmitted[lastEmitted.length - 1][0]).toMatchObject({
      question_type: 'single_choice',
      error_type: 'question_misreading',
    });
  });

  it('renders knowledge points and triggers filter change when selected', async () => {
    const wrapper = mount(WrongRecordFilterBar, {
      ...filterBarMountOptions,
      props: {
        knowledgePoints: [
          { id: 'kp_101', name: '动态规划' },
          { id: 'kp_102', name: '贪心算法' },
        ],
      },
    });

    expect(wrapper.text()).toContain('知识点');
    expect(wrapper.text()).toContain('动态规划');

    const kpCapsule = wrapper.findAll('.filter-capsule').find((c) => c.text().includes('动态规划'));
    expect(kpCapsule).toBeDefined();
    await kpCapsule!.trigger('tap');

    const emitted = wrapper.emitted('filter-change')!;
    expect(emitted[emitted.length - 1][0]).toMatchObject({
      knowledge_point_id: 'kp_101',
    });
  });

  it('handles reset and emits a single filter-change (DIAG-015)', async () => {
    const wrapper = mount(WrongRecordFilterBar, filterBarMountOptions);

    // Click '已攻克'
    const tabs = wrapper.findAll('.status-tab-item');
    await tabs[2].trigger('tap');

    expect(wrapper.find('.reset-btn').exists()).toBe(true);
    await wrapper.find('.reset-btn').trigger('tap');

    // BUG-DIAG-015: reset must only emit filter-change (single channel), no
    // duplicate reset event that would trigger a second parent list request.
    expect(wrapper.emitted('reset')).toBeFalsy();
    const emitted = wrapper.emitted('filter-change')!;
    expect(emitted[emitted.length - 1][0]).toEqual({
      material_id: undefined,
    });
  });
});

describe('WrongRecordCard Component', () => {
  const mockRecord: WrongRecordItem = {
    id: 'wr_001',
    practice_id: 'prac_001',
    question_id: 'q_001',
    knowledge_point_id: 'kp_001',
    question_type: 'single_choice',
    error_type: 'conceptual',
    error_count: 2,
    wrong_count: 2,
    first_wrong_at: '2026-09-25T10:00:00Z',
    created_at: '2026-09-25T10:00:00Z',
    is_mastered: false,
    user_answer: 'B',
    correct_answer: 'A',
    question_snapshot: {
      stem: '关于平衡二叉树的描述，哪项是正确的？',
      question_type: 'single_choice',
      options: [
        { key: 'A', text: '任意节点左右子树高度差绝对值不超过1' },
        { key: 'B', text: '完全二叉树一定是平衡二叉树' },
      ],
      answer: 'A',
      analysis: '平衡二叉树要求左右子树高度差绝对值<=1。',
      knowledge_name: '二叉平衡树',
    },
  };

  it('renders card with stem, tags, options and error statistics', () => {
    const wrapper = mount(WrongRecordCard, {
      props: { record: mockRecord },
    });

    expect(wrapper.text()).toContain('单选题');
    expect(wrapper.text()).toContain('概念性错误');
    expect(wrapper.text()).toContain('标为已攻克');
    expect(wrapper.text()).toContain('答错 2 次');
    expect(wrapper.text()).toContain('二叉平衡树');
    expect(wrapper.text()).toContain('关于平衡二叉树的描述，哪项是正确的？');
    expect(wrapper.text()).toContain('A.');
    expect(wrapper.text()).toContain('任意节点左右子树高度差绝对值不超过1');
  });

  it('renders authoritative fill_in_blank question type (DIAG-011 enum alignment)', () => {
    const wrapper = mount(WrongRecordCard, {
      props: {
        record: {
          ...mockRecord,
          question_type: 'fill_in_blank',
        },
      },
    });

    expect(wrapper.text()).toContain('填空题');
    expect(wrapper.text()).not.toContain('试题');
  });

  it('toggles expansion of answers and analysis', async () => {
    const wrapper = mount(WrongRecordCard, {
      props: { record: mockRecord },
    });

    // Folded initially
    expect(wrapper.find('.answer-analysis-foldable').exists()).toBe(false);
    expect(wrapper.text()).toContain('展开答案与解析');

    // Click toggle expand
    await wrapper.find('.toggle-expand-btn').trigger('tap');
    expect(wrapper.find('.answer-analysis-foldable').exists()).toBe(true);
    expect(wrapper.text()).toContain('您的作答：');
    expect(wrapper.text()).toContain('B');
    expect(wrapper.text()).toContain('正确答案：');
    expect(wrapper.text()).toContain('A');
    expect(wrapper.text()).toContain('平衡二叉树要求左右子树高度差绝对值<=1。');
    expect(wrapper.text()).toContain('收起解析');

    // Click again to fold
    await wrapper.find('.toggle-expand-btn').trigger('tap');
    expect(wrapper.find('.answer-analysis-foldable').exists()).toBe(false);
  });

  it('emits toggle-mastered when master action button is tapped', async () => {
    const wrapper = mount(WrongRecordCard, {
      props: { record: mockRecord },
    });

    const masterBtn = wrapper.find('.master-action-btn');
    await masterBtn.trigger('tap');

    expect(wrapper.emitted('toggle-mastered')).toBeTruthy();
    expect(wrapper.emitted('toggle-mastered')![0][0]).toEqual(mockRecord);
  });

  it('does not emit toggle-mastered when mastering is true', async () => {
    const wrapper = mount(WrongRecordCard, {
      props: { record: mockRecord, mastering: true },
    });

    expect(wrapper.text()).toContain('处理中...');
    const masterBtn = wrapper.find('.master-action-btn');
    await masterBtn.trigger('tap');

    expect(wrapper.emitted('toggle-mastered')).toBeFalsy();
  });

  it('handles selectable mode and emits toggle-select', async () => {
    const wrapper = mount(WrongRecordCard, {
      props: { record: mockRecord, selectable: true, selected: false },
    });

    expect(wrapper.find('.select-touch-area').exists()).toBe(true);
    expect(wrapper.find('.select-checkbox.checked').exists()).toBe(false);

    await wrapper.find('.select-touch-area').trigger('tap');

    expect(wrapper.emitted('toggle-select')).toBeTruthy();
    expect(wrapper.emitted('toggle-select')![0][0]).toEqual(mockRecord);
  });
});
