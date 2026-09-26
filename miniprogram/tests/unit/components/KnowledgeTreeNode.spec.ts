import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import { setActivePinia, createPinia } from 'pinia';
import KnowledgeTreeNode from '@/subpackages/material/components/KnowledgeTreeNode.vue';
import { useMaterialStore } from '@/stores/materialStore';
import type { KnowledgeTreeNode as KnowledgeNodeType } from '@/types/material';

describe('KnowledgeTreeNode.vue', () => {
  const sampleNode: KnowledgeNodeType = {
    id: 'kp-root',
    name: '计算机组成原理',
    description: '核心基础课程体系',
    level: 1,
    is_low_confidence: false,
    children: [
      {
        id: 'kp-child-1',
        name: '指令系统与寻址方式',
        description: '重点考察各类寻址模式',
        level: 2,
        parent_id: 'kp-root',
        is_low_confidence: true,
        children: [],
      },
    ],
  };

  it('renders node title and description correctly', () => {
    const wrapper = mount(KnowledgeTreeNode, {
      props: {
        node: sampleNode,
        level: 1,
      },
    });

    expect(wrapper.text()).toContain('计算机组成原理');
    expect(wrapper.text()).toContain('核心基础课程体系');
  });

  it('renders low confidence tag when is_low_confidence is true', () => {
    const lowConfNode: KnowledgeNodeType = {
      id: 'kp-low',
      name: '低置信度知识点',
      level: 2,
      is_low_confidence: true,
    };

    const wrapper = mount(KnowledgeTreeNode, {
      props: {
        node: lowConfNode,
      },
    });

    expect(wrapper.text()).toContain('低可信度');
  });

  it('does not render low confidence tag when is_low_confidence is false', () => {
    const normalNode: KnowledgeNodeType = {
      id: 'kp-normal',
      name: '高置信度知识点',
      level: 1,
      is_low_confidence: false,
    };

    const wrapper = mount(KnowledgeTreeNode, {
      props: {
        node: normalNode,
      },
    });

    expect(wrapper.text()).not.toContain('低可信度');
  });

  it('emits toggle-select when checkbox or content area is clicked', async () => {
    const wrapper = mount(KnowledgeTreeNode, {
      props: {
        node: sampleNode,
        selectedIds: [],
      },
    });

    const checkboxArea = wrapper.find('.checkbox-hit-area');
    await checkboxArea.trigger('tap');

    expect(wrapper.emitted('toggle-select')).toBeTruthy();
    expect(wrapper.emitted('toggle-select')?.[0]).toEqual(['kp-root']);
  });

  it('renders checked style when node id is in selectedIds', () => {
    const wrapper = mount(KnowledgeTreeNode, {
      props: {
        node: sampleNode,
        selectedIds: ['kp-root'],
      },
    });

    const checkbox = wrapper.find('.custom-checkbox');
    expect(checkbox.classes()).toContain('checked');
  });

  it('emits toggle-collapse when collapse hit area is clicked', async () => {
    const wrapper = mount(KnowledgeTreeNode, {
      props: {
        node: sampleNode,
        collapsedMap: {},
      },
    });

    const collapseArea = wrapper.find('.collapse-hit-area');
    await collapseArea.trigger('tap');

    expect(wrapper.emitted('toggle-collapse')).toBeTruthy();
    expect(wrapper.emitted('toggle-collapse')?.[0]).toEqual(['kp-root']);
  });

  it('renders a collapse hit area for nodes with children and a placeholder for leaves', () => {
    const parent = mount(KnowledgeTreeNode, {
      props: {
        node: sampleNode,
      },
    });
    expect(parent.find('.collapse-hit-area').exists()).toBe(true);
    expect(parent.find('.collapse-placeholder').exists()).toBe(false);

    const leaf = mount(KnowledgeTreeNode, {
      props: {
        node: { id: 'kp-leaf', name: '叶子考点', level: 2 },
      },
    });
    expect(leaf.find('.collapse-placeholder').exists()).toBe(true);
    expect(leaf.find('.collapse-hit-area').exists()).toBe(false);
  });

  it('renders only its own node without recursive descendants (row component)', () => {
    const wrapper = mount(KnowledgeTreeNode, {
      props: {
        node: sampleNode,
        collapsedMap: { 'kp-root': false },
      },
    });
    expect(wrapper.text()).toContain('计算机组成原理');
    expect(wrapper.text()).not.toContain('指令系统与寻址方式');
  });

  it('cascades selection to descendants via materialStore when Pinia is active', async () => {
    setActivePinia(createPinia());
    const store = useMaterialStore();
    expect(store.selectedKnowledgeIds).toEqual([]);

    const wrapper = mount(KnowledgeTreeNode, {
      props: {
        node: sampleNode,
        selectedIds: store.selectedKnowledgeIds,
      },
    });

    const checkboxArea = wrapper.find('.checkbox-hit-area');
    await checkboxArea.trigger('tap');

    // Both kp-root and kp-child-1 should be selected
    expect(store.selectedKnowledgeIds).toContain('kp-root');
    expect(store.selectedKnowledgeIds).toContain('kp-child-1');

    // Tap again to unselect both
    await wrapper.setProps({ selectedIds: store.selectedKnowledgeIds });
    await checkboxArea.trigger('tap');

    expect(store.selectedKnowledgeIds).not.toContain('kp-root');
    expect(store.selectedKnowledgeIds).not.toContain('kp-child-1');
  });
});
