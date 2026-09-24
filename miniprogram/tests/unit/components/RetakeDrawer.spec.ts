import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import RetakeDrawer from '@/subpackages/material/components/RetakeDrawer.vue';
import type { PageOCRStatus } from '@/types/material';
import * as materialApi from '@/api/material';

describe('RetakeDrawer.vue', () => {
  const samplePages: PageOCRStatus[] = [
    {
      page_no: 2,
      is_qualified: false,
      issue_type: 'blur',
      issue_description: '字符无法识别',
      retake_count: 1,
      max_retakes: 3,
    },
    {
      page_no: 4,
      is_qualified: false,
      issue_type: 'dark',
      issue_description: '光线不足',
      retake_count: 0,
      max_retakes: 3,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when visible is false', () => {
    const wrapper = mount(RetakeDrawer, {
      props: {
        visible: false,
        materialId: 'mat_test_1',
        pages: samplePages,
      },
    });

    expect(wrapper.find('.drawer-mask').exists()).toBe(false);
  });

  it('renders drawer, title, and page list when visible is true', () => {
    const wrapper = mount(RetakeDrawer, {
      props: {
        visible: true,
        materialId: 'mat_test_1',
        pages: samplePages,
      },
    });

    expect(wrapper.find('.drawer-mask').exists()).toBe(true);
    expect(wrapper.find('.drawer-title').text()).toContain('单页重新拍摄');
    expect(wrapper.findAll('.page-item')).toHaveLength(2);

    const text = wrapper.text();
    expect(text).toContain('第 2 页');
    expect(text).toContain('第 2 页文字模糊，需重新拍摄');
    expect(text).toContain('第 4 页');
    expect(text).toContain('第 4 页光线过暗，需重新拍摄');

    // 零 Emoji 原则检验
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });

  it('displays remaining retake counts correctly', () => {
    const wrapper = mount(RetakeDrawer, {
      props: {
        visible: true,
        materialId: 'mat_test_1',
        pages: samplePages,
      },
    });

    const pageItems = wrapper.findAll('.page-item');
    expect(pageItems[0].text()).toContain('剩余可重拍次数: 2 次');
    expect(pageItems[1].text()).toContain('剩余可重拍次数: 3 次');
  });

  it('disables retake button and shows limit warning when retake_count reaches max_retakes', async () => {
    const fusedPages: PageOCRStatus[] = [
      {
        page_no: 3,
        is_qualified: false,
        issue_type: 'blur',
        issue_description: '严重模糊',
        retake_count: 3,
        max_retakes: 3,
      },
    ];

    const chooseImageSpy = vi.fn();
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.chooseImage = chooseImageSpy;

    const wrapper = mount(RetakeDrawer, {
      props: {
        visible: true,
        materialId: 'mat_test_1',
        pages: fusedPages,
      },
    });

    const pageItem = wrapper.find('.page-item');
    expect(pageItem.text()).toContain('已达最大重拍限制');
    expect(pageItem.text()).toContain('剩余可重拍次数: 0 次');

    const retakeBtn = pageItem.find('.retake-btn');
    expect(retakeBtn.attributes('disabled')).toBeDefined();
    expect(retakeBtn.classes()).toContain('disabled');

    await retakeBtn.trigger('tap');
    expect(chooseImageSpy).not.toHaveBeenCalled();
  });

  it('emits update:visible and close on mask or close button tap', async () => {
    const wrapper = mount(RetakeDrawer, {
      props: {
        visible: true,
        materialId: 'mat_test_1',
        pages: samplePages,
      },
    });

    const closeBtn = wrapper.find('.close-btn');
    await closeBtn.trigger('tap');

    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
    expect(wrapper.emitted('close')).toHaveLength(1);

    const mask = wrapper.find('.drawer-mask');
    await mask.trigger('tap');
    expect(wrapper.emitted('update:visible')?.length).toBeGreaterThanOrEqual(2);
  });

  it('invokes retakeMaterialPage and emits retake-success on successful photo selection', async () => {
    const mockApiResponse = {
      code: 0,
      message: 'success',
      data: {
        material_id: 'mat_test_1',
        page_no: 4,
        status: 'ready',
      },
    };

    const retakeSpy = vi
      .spyOn(materialApi, 'retakeMaterialPage')
      .mockResolvedValue(mockApiResponse);

    const showToastSpy = vi.fn();
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.showToast = showToastSpy;

    (globalThis as unknown as { uni: Record<string, unknown> }).uni.chooseImage = vi.fn(
      (options: { success?: (res: unknown) => void }) => {
        options.success?.({
          tempFilePaths: ['wxfile://tmp_page_4.jpg'],
        });
      },
    );

    const wrapper = mount(RetakeDrawer, {
      props: {
        visible: true,
        materialId: 'mat_test_1',
        pages: samplePages,
      },
    });

    const secondPageItem = wrapper.findAll('.page-item')[1];
    const retakeBtn = secondPageItem.find('.retake-btn');
    await retakeBtn.trigger('tap');

    expect(retakeSpy).toHaveBeenCalledWith(
      'mat_test_1',
      4,
      'wxfile://tmp_page_4.jpg',
      expect.any(String),
    );

    expect(wrapper.emitted('retake-success')?.[0]).toEqual([
      {
        page_no: 4,
        data: mockApiResponse.data,
      },
    ]);

    expect(showToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '重拍提交成功',
      }),
    );
  });

  it('handles api failure gracefully with error toast', async () => {
    vi.spyOn(materialApi, 'retakeMaterialPage').mockRejectedValue(new Error('Network error'));

    const showToastSpy = vi.fn();
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.showToast = showToastSpy;

    (globalThis as unknown as { uni: Record<string, unknown> }).uni.chooseImage = vi.fn(
      (options: { success?: (res: unknown) => void }) => {
        options.success?.({
          tempFilePaths: ['wxfile://tmp_page_4.jpg'],
        });
      },
    );

    const wrapper = mount(RetakeDrawer, {
      props: {
        visible: true,
        materialId: 'mat_test_1',
        pages: samplePages,
      },
    });

    const secondPageItem = wrapper.findAll('.page-item')[1];
    const retakeBtn = secondPageItem.find('.retake-btn');
    await retakeBtn.trigger('tap');

    expect(showToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '重拍提交失败，请重试',
        icon: 'none',
      }),
    );
  });
});
