import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { setActivePinia, createPinia } from 'pinia';
import MaterialListPage from '@/subpackages/material/pages/list/index.vue';
import { useMaterialStore } from '@/stores/materialStore';
import * as materialApi from '@/api/material';
import type { MaterialItem } from '@/types/material';

describe('MaterialListPage (list/index.vue)', () => {
  const sampleMaterials: MaterialItem[] = [
    {
      id: 'mat_01',
      title: '高数上册核心笔记',
      file_format: 'pdf',
      file_size: 1048576,
      source_type: 'local',
      status: 'ready',
      created_at: '2026-09-25T10:00:00Z',
    },
    {
      id: 'mat_02',
      title: '近代史纲要讲义',
      file_format: 'docx',
      file_size: 2097152,
      source_type: 'wechat',
      status: 'parsing',
      created_at: '2026-09-25T11:00:00Z',
    },
  ];

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('renders material list and cards correctly on mount', async () => {
    vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: sampleMaterials,
        total: 2,
        limit: 20,
        offset: 0,
      },
    });

    const wrapper = mount(MaterialListPage);
    await wrapper.vm.$nextTick();
    // 等待 loadData 完成
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.vm.$nextTick();

    const text = wrapper.text();
    expect(text).toContain('高数上册核心笔记');
    expect(text).toContain('近代史纲要讲义');
    expect(text).toContain('PDF');
    expect(text).toContain('DOCX');
    expect(text).toContain('已完成');
    expect(text).toContain('解析中');

    // 零 Emoji 检查
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });

  it('switches tabs and filters materials by status', async () => {
    const fetchSpy = vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: [sampleMaterials[1]],
        total: 1,
        limit: 20,
        offset: 0,
      },
    });

    const wrapper = mount(MaterialListPage);
    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));

    const tabs = wrapper.findAll('.tab-item');
    expect(tabs.length).toBe(4);

    // 点击“解析中” Tab (第 2 个)
    await tabs[1].trigger('tap');
    await wrapper.vm.$nextTick();

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'parsing',
        page: 1,
      }),
    );
  });

  it('renders zero-emoji empty state when list is empty', async () => {
    vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
      },
    });

    const wrapper = mount(MaterialListPage);
    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.vm.$nextTick();

    expect(wrapper.find('.empty-state').exists()).toBe(true);
    expect(wrapper.text()).toContain('暂无学习资料');
    expect(wrapper.text()).toContain('立即导入资料');

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });

  it('opens upload popup when FAB or empty state import button is clicked', async () => {
    vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
      },
    });

    const wrapper = mount(MaterialListPage);
    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.vm.$nextTick();

    expect(wrapper.vm.uploadVisible).toBe(false);

    // 点击悬浮按钮
    const fabBtn = wrapper.find('.fab-upload-btn');
    expect(fabBtn.exists()).toBe(true);
    await fabBtn.trigger('tap');
    expect(wrapper.vm.uploadVisible).toBe(true);

    // 模拟上传成功回调
    const fetchSpy = vi.spyOn(materialApi, 'fetchMaterialList');
    wrapper.vm.handleUploadSuccess();
    expect(wrapper.vm.uploadVisible).toBe(false);
    expect(fetchSpy).toHaveBeenCalled();
  });

  it('navigates to detail page when a material card is clicked', async () => {
    vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: sampleMaterials,
        total: 2,
        limit: 20,
        offset: 0,
      },
    });

    const navigateSpy = vi.spyOn(uni, 'navigateTo');
    const materialStore = useMaterialStore();

    const wrapper = mount(MaterialListPage);
    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.vm.$nextTick();

    const firstCard = wrapper.findComponent({ name: 'MaterialCard' });
    expect(firstCard.exists()).toBe(true);

    await firstCard.trigger('tap');
    expect(navigateSpy).toHaveBeenCalledWith({
      url: '../detail/index?id=mat_01',
    });
    expect(materialStore.currentMaterialId).toBe('mat_01');
  });

  it('triggers delete API when card emits delete', async () => {
    vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: [sampleMaterials[0]],
        total: 1,
        limit: 20,
        offset: 0,
      },
    });
    const deleteSpy = vi.spyOn(materialApi, 'deleteMaterial').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        material_id: 'mat_01',
        is_deleted: true,
      },
    });

    const wrapper = mount(MaterialListPage);
    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));

    await wrapper.vm.handleCardDelete(sampleMaterials[0]);
    expect(deleteSpy).toHaveBeenCalledWith('mat_01');
  });
});
