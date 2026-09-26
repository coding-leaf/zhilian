import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { setActivePinia, createPinia } from 'pinia';
import MaterialDetailPage from '@/subpackages/material/pages/detail/index.vue';
import { useMaterialStore } from '@/stores/materialStore';
import * as materialApi from '@/api/material';
import type { MaterialItem } from '@/types/material';

describe('MaterialDetailPage (detail/index.vue)', () => {
  const baseDetail: MaterialItem = {
    id: 'mat_detail_01',
    title: '计算机网络核心考点讲义',
    file_format: 'pdf',
    file_size: 2097152, // 2MB
    source_type: 'local',
    status: 'ready',
    versions_count: 2,
    created_at: '2026-09-25T12:00:00Z',
  };

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('loads and renders material detail metadata correctly', async () => {
    vi.spyOn(materialApi, 'fetchMaterialDetail').mockResolvedValue({
      code: 200,
      message: 'success',
      data: baseDetail,
    });

    const wrapper = mount(MaterialDetailPage, {
      props: {
        id: 'mat_detail_01',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.vm.$nextTick();

    const text = wrapper.text();
    expect(text).toContain('计算机网络核心考点讲义');
    expect(text).toContain('PDF');
    expect(text).toContain('2.0 MB');
    expect(text).toContain('2 个版本');
    expect(text).toContain('已完成');
    expect(text).toContain('考点解析已完成');

    // 零 Emoji 检查
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });

  it('triggers polling when material status is parsing', async () => {
    const parsingDetail: MaterialItem = {
      ...baseDetail,
      status: 'parsing',
    };

    vi.spyOn(materialApi, 'fetchMaterialDetail').mockResolvedValue({
      code: 200,
      message: 'success',
      data: parsingDetail,
    });
    const statusSpy = vi.spyOn(materialApi, 'fetchMaterialStatus').mockResolvedValue({
      code: 200,
      message: 'success',
      data: parsingDetail,
    });

    const wrapper = mount(MaterialDetailPage, {
      props: {
        id: 'mat_detail_01',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain('解析中');
    expect(wrapper.text()).toContain('正在智能提取考点大纲');
    expect(wrapper.vm.isPolling).toBe(true);
    expect(statusSpy).toHaveBeenCalled();
  });

  it('renders retake banner and opens drawer when retake is required', async () => {
    const retakeDetail: MaterialItem = {
      ...baseDetail,
      status: 'retake_required',
    };

    vi.spyOn(materialApi, 'fetchMaterialDetail').mockResolvedValue({
      code: 200,
      message: 'success',
      data: retakeDetail,
    });

    const wrapper = mount(MaterialDetailPage, {
      props: {
        id: 'mat_detail_01',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.vm.$nextTick();

    // 检查告警横幅
    const banner = wrapper.find('.retake-banner');
    expect(banner.exists()).toBe(true);
    expect(banner.text()).toContain('检测到部分页面文字模糊或存在缺陷');
    expect(banner.text()).toContain('查看待重新拍摄页');

    // 点击按钮唤起 RetakeDrawer
    expect(wrapper.vm.isRetakeDrawerVisible).toBe(false);
    const bannerBtn = banner.find('.banner-btn');
    await bannerBtn.trigger('tap');
    expect(wrapper.vm.isRetakeDrawerVisible).toBe(true);
  });

  it('refreshes detail and restarts polling after retake success', async () => {
    const retakeDetail: MaterialItem = {
      ...baseDetail,
      status: 'retake_required',
    };

    const fetchDetailSpy = vi.spyOn(materialApi, 'fetchMaterialDetail').mockResolvedValue({
      code: 200,
      message: 'success',
      data: retakeDetail,
    });
    vi.spyOn(materialApi, 'fetchMaterialStatus').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        ...baseDetail,
        status: 'parsing',
      },
    });

    const wrapper = mount(MaterialDetailPage, {
      props: {
        id: 'mat_detail_01',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));

    // 模拟重拍成功事件
    wrapper.vm.handleRetakeSuccess({ page_no: 1 });
    await wrapper.vm.$nextTick();

    expect(wrapper.vm.isRetakeDrawerVisible).toBe(false);
    expect(fetchDetailSpy).toHaveBeenCalledTimes(2);
  });

  it('allows navigating to knowledge tree when parsing is ready', async () => {
    vi.spyOn(materialApi, 'fetchMaterialDetail').mockResolvedValue({
      code: 200,
      message: 'success',
      data: baseDetail,
    });
    const navigateSpy = vi.spyOn(uni, 'navigateTo');

    const wrapper = mount(MaterialDetailPage, {
      props: {
        id: 'mat_detail_01',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.vm.$nextTick();

    const actionBtn = wrapper.find('.action-btn');
    expect(actionBtn.classes()).not.toContain('disabled');

    await actionBtn.trigger('tap');
    expect(navigateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/subpackages/material/pages/knowledge-tree/index?material_id=mat_detail_01',
      }),
    );
  });

  it('synchronizes active material to store when detail loads', async () => {
    vi.spyOn(materialApi, 'fetchMaterialDetail').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        ...baseDetail,
        current_version_id: 'ver_001',
      },
    });

    const materialStore = useMaterialStore();
    const wrapper = mount(MaterialDetailPage, {
      props: {
        id: 'mat_detail_01',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(materialStore.currentMaterialId).toBe('mat_detail_01');
    expect(materialStore.activeVersion).toBe('ver_001');
  });

  it('renders failed box and retry button when material status is failed, and retries successfully', async () => {
    const failedDetail: MaterialItem = {
      ...baseDetail,
      status: 'failed',
    };

    vi.spyOn(materialApi, 'fetchMaterialDetail').mockResolvedValue({
      code: 200,
      message: 'success',
      data: failedDetail,
    });
    const retrySpy = vi.spyOn(materialApi, 'retryMaterial').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        ...failedDetail,
        status: 'pending',
      },
    });

    const wrapper = mount(MaterialDetailPage, {
      props: {
        id: 'mat_detail_01',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain('资料解析遇到异常');
    const retryBtn = wrapper.find('.retry-action-btn');
    expect(retryBtn.exists()).toBe(true);
    expect(retryBtn.text()).toContain('重试解析');

    await retryBtn.trigger('tap');
    expect(retrySpy).toHaveBeenCalledWith('mat_detail_01');
  });
});
