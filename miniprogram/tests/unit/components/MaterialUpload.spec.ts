import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { setActivePinia, createPinia } from 'pinia';
import MaterialUpload, {
  generateIdempotencyKey,
  validateMaterialFile,
} from '@/components/common/MaterialUpload.vue';
import { useMaterialStore } from '@/stores/materialStore';
import * as materialApi from '@/api/material';

describe('MaterialUpload.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('validates idempotency key format to be 16 alphanumeric characters', () => {
    const key1 = generateIdempotencyKey();
    const key2 = generateIdempotencyKey();
    expect(key1).toHaveLength(16);
    expect(key2).toHaveLength(16);
    expect(key1).not.toBe(key2);
    expect(/^[A-Za-z0-9]{16}$/.test(key1)).toBe(true);
  });

  it('validates file extension against allowed types (pdf, docx, png, jpg)', () => {
    expect(validateMaterialFile('sample.pdf', 1000).valid).toBe(true);
    expect(validateMaterialFile('notes.docx', 1000).valid).toBe(true);
    expect(validateMaterialFile('page.png', 1000).valid).toBe(true);
    expect(validateMaterialFile('scan.jpg', 1000).valid).toBe(true);
    expect(validateMaterialFile('scan.jpeg', 1000).valid).toBe(true);

    const invalidExt = validateMaterialFile('archive.zip', 1000);
    expect(invalidExt.valid).toBe(false);
    expect(invalidExt.error).toBe('目前仅支持 PDF、DOCX 及图片格式文件');

    const invalidTxt = validateMaterialFile('notes.txt', 1000);
    expect(invalidTxt.valid).toBe(false);
    expect(invalidTxt.error).toBe('目前仅支持 PDF、DOCX 及图片格式文件');
  });

  it('validates file size strictly not exceeding 20MB', () => {
    const maxSize = 20 * 1024 * 1024;
    expect(validateMaterialFile('sample.pdf', maxSize).valid).toBe(true);

    const oversized = validateMaterialFile('sample.pdf', maxSize + 1);
    expect(oversized.valid).toBe(false);
    expect(oversized.error).toBe('文件体积过大，请上传小于 20MB 的文件');
  });

  it('enforces per-format size limits aligned with backend MAX_FILE_SIZES (MAT-005)', () => {
    // Image formats are capped at 10MB.
    const oversizedImage = validateMaterialFile('photo.jpg', 15 * 1024 * 1024);
    expect(oversizedImage.valid).toBe(false);
    expect(oversizedImage.error).toContain('10MB');
    expect(oversizedImage.error).toContain('图片');

    expect(validateMaterialFile('photo.jpeg', 10 * 1024 * 1024).valid).toBe(true);
    expect(validateMaterialFile('photo.png', 10 * 1024 * 1024 + 1).valid).toBe(false);

    // Documents keep the 20MB ceiling.
    expect(validateMaterialFile('lecture.pdf', 15 * 1024 * 1024).valid).toBe(true);
    expect(validateMaterialFile('notes.docx', 20 * 1024 * 1024).valid).toBe(true);
    expect(validateMaterialFile('notes.docx', 20 * 1024 * 1024 + 1).valid).toBe(false);
  });

  it('keeps the mini-program format whitelist as a controlled subset of backend doc types (MAT-006)', () => {
    // The mobile client intentionally narrows accepted formats to pdf/docx/images.
    expect(validateMaterialFile('slides.pptx', 1000).valid).toBe(false);
    expect(validateMaterialFile('notes.txt', 1000).valid).toBe(false);
    expect(validateMaterialFile('readme.md', 1000).valid).toBe(false);
  });

  it('renders initial idle state with selection buttons and zero emoji', () => {
    const wrapper = mount(MaterialUpload, {
      props: {
        visible: true,
      },
    });

    expect(wrapper.text()).toContain('导入学习资料');
    expect(wrapper.text()).toContain('微信文件');
    expect(wrapper.text()).toContain('相册与拍照');
    expect(wrapper.text()).toContain('未选择文件');

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });

  it('intercepts oversized file from wechat message file picker', async () => {
    const showToastSpy = vi.fn();
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.showToast = showToastSpy;

    (globalThis as unknown as { wx: Record<string, unknown> }).wx = {
      chooseMessageFile: vi.fn((options: { success?: (res: unknown) => void }) => {
        options.success?.({
          tempFiles: [
            {
              name: 'huge_book.pdf',
              path: 'wxfile://tmp_huge_book.pdf',
              size: 25 * 1024 * 1024,
            },
          ],
        });
      }),
    };

    const wrapper = mount(MaterialUpload, {
      props: {
        visible: true,
      },
    });

    const wechatBtn = wrapper.find('.wechat-btn');
    expect(wechatBtn.exists()).toBe(true);

    await wechatBtn.trigger('tap');

    expect(showToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '文件体积过大，请上传小于 20MB 的文件',
        icon: 'none',
      }),
    );
  });

  it('handles valid file selection and successful upload flow with store update', async () => {
    const materialStore = useMaterialStore();
    const mockUploadResponse = {
      code: 200,
      data: {
        id: 'mat_new_99',
        version_id: 'ver_init_01',
        title: '微积分精要',
        file_format: 'pdf',
        file_size: 204800,
        source_type: 'wechat',
        status: 'pending' as const,
        created_at: new Date().toISOString(),
      },
      message: 'OK',
    };

    const uploadSpy = vi
      .spyOn(materialApi, 'uploadMaterialFile')
      .mockResolvedValue(mockUploadResponse);

    (globalThis as unknown as { wx: Record<string, unknown> }).wx = {
      chooseMessageFile: vi.fn((options: { success?: (res: unknown) => void }) => {
        options.success?.({
          tempFiles: [
            {
              name: '微积分精要.pdf',
              path: 'wxfile://tmp_calculus.pdf',
              size: 204800,
            },
          ],
        });
      }),
    };

    const wrapper = mount(MaterialUpload, {
      props: {
        visible: true,
      },
    });

    // 1. 选择微信文件
    const wechatBtn = wrapper.find('.wechat-btn');
    await wechatBtn.trigger('tap');

    // 2. 应该显示已选文件
    expect(wrapper.text()).toContain('微积分精要.pdf');

    // 3. 点击开始上传
    const submitBtn = wrapper.find('.submit-btn');
    expect(submitBtn.exists()).toBe(true);
    await submitBtn.trigger('tap');

    expect(uploadSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        filePath: 'wxfile://tmp_calculus.pdf',
        title: '微积分精要',
        sourceType: 'wechat',
      }),
    );

    await wrapper.vm.$nextTick();

    // 4. 验证 store 已同步新增
    expect(materialStore.materialsList.some((m) => m.id === 'mat_new_99')).toBe(true);

    // 5. 验证派发 success 事件
    expect(wrapper.emitted('success')).toBeTruthy();
    expect(wrapper.emitted('success')?.[0]).toEqual([mockUploadResponse.data]);
    expect(wrapper.text()).toContain('上传成功');
  });
});
