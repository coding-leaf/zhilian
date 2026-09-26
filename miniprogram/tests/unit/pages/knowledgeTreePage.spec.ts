import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { setActivePinia, createPinia } from 'pinia';
import KnowledgeTreePage from '@/subpackages/material/pages/knowledge-tree/index.vue';
import { useMaterialStore } from '@/stores/materialStore';
import * as materialApi from '@/api/material';
import type { KnowledgeTreeResponse } from '@/types/material';

describe('KnowledgeTreePage (knowledge-tree/index.vue)', () => {
  const mockTreeResponse: KnowledgeTreeResponse = {
    material_id: 'mat_001',
    version_id: 'ver_001',
    nodes: [
      {
        id: 'node-1',
        name: '操作系统概述',
        level: 1,
        is_low_confidence: false,
        children: [
          {
            id: 'node-1-1',
            name: '进程与线程模型',
            level: 2,
            is_low_confidence: true,
            parent_id: 'node-1',
            children: [],
          },
        ],
      },
      {
        id: 'node-2',
        name: '存储器管理机制',
        level: 1,
        is_low_confidence: false,
        children: [],
      },
    ],
  };

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('loads and renders tree data with correct overview statistics', async () => {
    vi.spyOn(materialApi, 'fetchKnowledgeTree').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockTreeResponse,
    });
    vi.spyOn(materialApi, 'fetchMaterialDetail').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        id: 'mat_001',
        title: '操作系统考研复习讲义',
        file_format: 'pdf',
        file_size: 1024,
        source_type: 'upload',
        status: 'ready',
        created_at: '2026-09-01T00:00:00Z',
      },
    });

    const wrapper = mount(KnowledgeTreePage, {
      props: {
        materialId: 'mat_001',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 20));
    await wrapper.vm.$nextTick();

    const text = wrapper.text();
    expect(text).toContain('操作系统考研复习讲义');
    expect(text).toContain('操作系统概述');
    expect(text).toContain('进程与线程模型');
    expect(text).toContain('存储器管理机制');

    // Total 3 nodes in mockTreeResponse
    expect(text).toContain('3');
    expect(text).toContain('知识点总数');

    // Zero Emoji check
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });

  it('renders low confidence degradation warning banner when node has is_low_confidence=true', async () => {
    vi.spyOn(materialApi, 'fetchKnowledgeTree').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockTreeResponse,
    });

    const wrapper = mount(KnowledgeTreePage, {
      props: {
        materialId: 'mat_001',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(wrapper.text()).toContain('检测到部分知识点抽取可信度较低，已自动降级');
  });

  it('handles select all and clear selection properly', async () => {
    vi.spyOn(materialApi, 'fetchKnowledgeTree').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockTreeResponse,
    });

    const materialStore = useMaterialStore();
    const wrapper = mount(KnowledgeTreePage, {
      props: {
        materialId: 'mat_001',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 20));

    // Initially 0 selected
    expect(materialStore.selectedCount).toBe(0);

    // Find "全选" button
    const buttons = wrapper.findAll('.tool-btn');
    const selectAllBtn = buttons.find((b) => b.text().includes('全选'));
    expect(selectAllBtn).toBeDefined();

    await selectAllBtn?.trigger('tap');
    expect(materialStore.selectedCount).toBe(3);
    expect(wrapper.text()).toContain('考点覆盖率 100%');

    // Find "清空" button
    const clearBtn = buttons.find((b) => b.text().includes('清空'));
    expect(clearBtn).toBeDefined();

    await clearBtn?.trigger('tap');
    expect(materialStore.selectedCount).toBe(0);
    expect(wrapper.text()).toContain('考点覆盖率 0%');
  });

  it('enables primary button when items are selected and shows toast on click', async () => {
    vi.spyOn(materialApi, 'fetchKnowledgeTree').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockTreeResponse,
    });
    const toastSpy = vi.spyOn(uni, 'showToast');

    const materialStore = useMaterialStore();
    const wrapper = mount(KnowledgeTreePage, {
      props: {
        materialId: 'mat_001',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 20));

    const generateBtn = wrapper.find('.primary-action-btn');
    expect(generateBtn.classes()).toContain('disabled');

    // Select one node
    materialStore.toggleKnowledgeSelection('node-1');
    await wrapper.vm.$nextTick();

    expect(generateBtn.classes()).not.toContain('disabled');

    await generateBtn.trigger('tap');
    expect(toastSpy).toHaveBeenCalledWith({
      title: '已就绪 1 个知识点',
      icon: 'none',
    });
  });

  it('navigates to the standalone question page with material_id from the overview link', async () => {
    vi.spyOn(materialApi, 'fetchKnowledgeTree').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockTreeResponse,
    });
    const navigateSpy = vi.fn();
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.navigateTo = navigateSpy;

    const wrapper = mount(KnowledgeTreePage, {
      props: {
        materialId: 'mat_001',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 20));

    const link = wrapper.find('.material-link');
    await link.trigger('tap');

    expect(navigateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/subpackages/material/pages/questions/index?material_id=mat_001',
        fail: expect.any(Function),
      }),
    );
  });

  it('keeps questions in the standalone page instead of a local tab (no dual data source)', async () => {
    vi.spyOn(materialApi, 'fetchKnowledgeTree').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockTreeResponse,
    });

    const wrapper = mount(KnowledgeTreePage, {
      props: {
        materialId: 'mat_001',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 20));

    const configDrawer = wrapper.findComponent({ name: 'QuestionConfigDrawer' });
    expect(configDrawer.exists()).toBe(true);
    expect(configDrawer.props('materialId')).toBe('mat_001');

    // Emitting success no longer injects a local question list / tab on this page
    configDrawer.vm.$emit('success', [
      {
        id: 'q_test_1',
        material_id: 'mat_001',
        version_id: 'ver_001',
        knowledge_point_id: 'node-1',
        question_type: 'single_choice',
        stem: '临界区是指访问临界资源的代码段吗？',
        difficulty: 3,
      },
    ]);
    await wrapper.vm.$nextTick();

    expect(wrapper.find('.view-tabs').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('临界区是指访问临界资源的代码段吗？');
  });
});
