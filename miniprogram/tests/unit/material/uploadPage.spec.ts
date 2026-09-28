import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount, flushPromises } from '@vue/test-utils';
import UploadPage from '@/subpackages/material/pages/upload/index.vue';
import * as materialApi from '@/api/material';

describe('Upload and OCR Quality Page (upload/index.vue)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('renders upload page title and zero Unicode emoji', () => {
    const wrapper = mount(UploadPage);
    expect(wrapper.text()).toContain('资料导入与质检');
    expect(wrapper.text()).toContain('拍照 / 相册');
    expect(wrapper.text()).toContain('微信聊天文件');

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });

  it('handles batch photo selection, renders gallery cards, and computes qualification rate', async () => {
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.chooseImage = vi.fn(
      (options: unknown) => {
        const opt = options as { success: (res: { tempFilePaths: string[] }) => void };
        opt.success({
          tempFilePaths: ['/tmp/page1.jpg', '/tmp/page2.jpg', '/tmp/page3.jpg'],
        });
        return Promise.resolve();
      },
    );

    const wrapper = mount(UploadPage);
    const mediaCard = wrapper.findAll('.picker-card')[0];
    await mediaCard.trigger('tap');
    await flushPromises();

    expect(wrapper.text()).toContain('OCR 质检画廊 (3页)');
    expect(wrapper.findAll('.gallery-card').length).toBe(3);
    // Page 2 in multi-page (>2) test is flagged for demo reshoot
    expect(wrapper.text()).toContain('第 2 页');
    expect(wrapper.text()).toContain('重拍替换');
  });

  it('performs single page camera reshoot and updates qualification status immediately', async () => {
    const chooseImageMock = vi
      .fn()
      .mockImplementationOnce((options: unknown) => {
        const opt = options as { success: (res: { tempFilePaths: string[] }) => void };
        opt.success({
          tempFilePaths: ['/tmp/page1.jpg', '/tmp/page2.jpg', '/tmp/page3.jpg'],
        });
        return Promise.resolve();
      })
      .mockImplementationOnce((options: unknown) => {
        const opt = options as { success: (res: { tempFilePaths: string[] }) => void };
        opt.success({
          tempFilePaths: ['/tmp/page2_new_camera.jpg'],
        });
        return Promise.resolve();
      });

    (globalThis as unknown as { uni: Record<string, unknown> }).uni.chooseImage = chooseImageMock;

    const wrapper = mount(UploadPage);
    await wrapper.findAll('.picker-card')[0].trigger('tap');
    await flushPromises();

    // Find reshoot button for page 2
    const reshootBtns = wrapper.findAll('.btn-retake-page');
    expect(reshootBtns.length).toBe(3);
    await reshootBtns[1].trigger('tap');
    await flushPromises();

    // After reshooting page 2, qualification rate is 100%
    expect(wrapper.text()).toContain('100% (3/3)');
    expect(wrapper.text()).toContain('确认质检并开启出题');
  });

  it('uploads document and navigates to verify list on confirmation', async () => {
    const uploadSpy = vi.spyOn(materialApi, 'uploadMaterialFile').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'mat_12345',
        version_id: 'v_1',
        title: '高等数学讲义',
        file_format: 'pdf',
        file_size: 1024,
        source_type: 'wechat',
        status: 'ready',
        created_at: '2026-09-28T00:00:00Z',
      },
    });

    const navigateSpy = vi.spyOn(uni, 'navigateTo');

    // Simulate wx.chooseMessageFile
    (globalThis as unknown as { wx: unknown }).wx = {
      chooseMessageFile: (options: {
        success: (res: { tempFiles: Array<{ name: string; path: string; size: number }> }) => void;
      }) => {
        options.success({
          tempFiles: [{ name: '高等数学讲义.pdf', path: '/tmp/math.pdf', size: 1024 }],
        });
      },
    };

    const wrapper = mount(UploadPage);
    const docCard = wrapper.findAll('.picker-card')[1];
    await docCard.trigger('tap');
    await flushPromises();

    expect(wrapper.text()).toContain('高等数学讲义.pdf');
    expect(wrapper.text()).toContain('文档就绪');

    const submitBtn = wrapper.find('.btn-submit');
    await submitBtn.trigger('tap');
    await flushPromises();

    expect(uploadSpy).toHaveBeenCalledTimes(1);
    expect(uploadSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        filePath: '/tmp/math.pdf',
        sourceType: 'wechat',
      }),
    );

    // Timeout delay in component
    await new Promise((r) => setTimeout(r, 600));
    expect(navigateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/subpackages/material/pages/verify/index?material_id=mat_12345',
      }),
    );
  });
});
