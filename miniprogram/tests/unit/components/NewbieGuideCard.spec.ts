import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import NewbieGuideCard from '@/components/home/NewbieGuideCard.vue';

describe('NewbieGuideCard.vue', () => {
  const EMOJI_REGEX =
    /[\u{1F300}-\u{1FAFF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}]/u;

  it('renders correctly when visible is true (default)', () => {
    const wrapper = mount(NewbieGuideCard, {
      props: {
        visible: true,
      },
    });

    expect(wrapper.find('.newbie-guide-card').exists()).toBe(true);
    expect(wrapper.text()).toContain('新手学习指南');
    expect(wrapper.text()).toContain('导入学习资料');
    expect(wrapper.text()).toContain('考点智能提炼');
    expect(wrapper.text()).toContain('自适应练习与诊断');
  });

  it('does not render content when visible is false', () => {
    const wrapper = mount(NewbieGuideCard, {
      props: {
        visible: false,
      },
    });

    expect(wrapper.find('.newbie-guide-card').exists()).toBe(false);
  });

  it('emits "start-first" event when the action button is tapped', async () => {
    const wrapper = mount(NewbieGuideCard, {
      props: {
        visible: true,
      },
    });

    const actionBtn = wrapper.find('.guide-action-btn');
    expect(actionBtn.exists()).toBe(true);
    expect(actionBtn.text()).toContain('立即体验导入资料');

    await actionBtn.trigger('tap');
    expect(wrapper.emitted('start-first')).toHaveLength(1);
  });

  it('strictly contains zero Unicode emoji characters across rendered text', () => {
    const wrapper = mount(NewbieGuideCard, {
      props: {
        visible: true,
      },
    });

    const renderedText = wrapper.text();
    expect(EMOJI_REGEX.test(renderedText)).toBe(false);
  });
});
