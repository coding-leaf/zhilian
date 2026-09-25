import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import QuickUploadBar from '@/components/home/QuickUploadBar.vue';
import MaterialUpload from '@/components/common/MaterialUpload.vue';
import type { MaterialUploadResponse } from '@/types/material';

describe('QuickUploadBar.vue', () => {
  const EMOJI_REGEX =
    /[\u{1F300}-\u{1FAFF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}]/u;

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('renders copywriting, title, subtitle and action pill correctly', () => {
    const wrapper = mount(QuickUploadBar);

    expect(wrapper.text()).toContain('快捷上传学习资料');
    expect(wrapper.text()).toContain('支持聊天文档与拍照导入');
    expect(wrapper.text()).toContain('点击上传');
  });

  it('strictly adheres to zero-emoji policy', () => {
    const wrapper = mount(QuickUploadBar);
    expect(EMOJI_REGEX.test(wrapper.text())).toBe(false);
  });

  it('opens upload modal on tap when not disabled', async () => {
    const wrapper = mount(QuickUploadBar, {
      props: {
        disabled: false,
      },
    });

    const uploadComp = wrapper.findComponent(MaterialUpload);
    expect(uploadComp.props('visible')).toBe(false);

    await wrapper.trigger('tap');

    expect(uploadComp.props('visible')).toBe(true);
  });

  it('does not open upload modal when disabled is true', async () => {
    const wrapper = mount(QuickUploadBar, {
      props: {
        disabled: true,
      },
    });

    const uploadComp = wrapper.findComponent(MaterialUpload);
    expect(uploadComp.props('visible')).toBe(false);

    await wrapper.trigger('tap');

    expect(uploadComp.props('visible')).toBe(false);
    expect(wrapper.classes()).toContain('is-disabled');
  });

  it('forwards upload-success event and closes modal when child upload succeeds', async () => {
    const wrapper = mount(QuickUploadBar);
    const uploadComp = wrapper.findComponent(MaterialUpload);

    await wrapper.trigger('tap');
    expect(uploadComp.props('visible')).toBe(true);

    const mockResponse: MaterialUploadResponse = {
      id: 'mat_mock_99',
      version_id: 'ver_mock_01',
      title: '编译原理讲义',
      file_format: 'pdf',
      file_size: 2048,
      source_type: 'wechat',
      status: 'pending',
      created_at: '2026-09-25T10:00:00Z',
    };

    await uploadComp.vm.$emit('success', mockResponse);

    expect(wrapper.emitted('upload-success')).toBeTruthy();
    expect(wrapper.emitted('upload-success')?.[0]).toEqual([mockResponse]);
    expect(uploadComp.props('visible')).toBe(false);
  });

  it('handles child close event correctly', async () => {
    const wrapper = mount(QuickUploadBar);
    const uploadComp = wrapper.findComponent(MaterialUpload);

    await wrapper.trigger('tap');
    expect(uploadComp.props('visible')).toBe(true);

    await uploadComp.vm.$emit('close');
    expect(uploadComp.props('visible')).toBe(false);
  });

  it('supports programmatic open and close via exposed methods', async () => {
    const wrapper = mount(QuickUploadBar);
    const uploadComp = wrapper.findComponent(MaterialUpload);

    wrapper.vm.open();
    await wrapper.vm.$nextTick();
    expect(uploadComp.props('visible')).toBe(true);

    wrapper.vm.close();
    await wrapper.vm.$nextTick();
    expect(uploadComp.props('visible')).toBe(false);
  });
});
