import { describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import MaterialCard from '@/subpackages/material/components/MaterialCard.vue';
import type { MaterialItem } from '@/types/material';

describe('MaterialCard.vue', () => {
  const baseMaterial: MaterialItem = {
    id: 'mat_test_01',
    title: '高数上册核心笔记',
    file_format: 'pdf',
    file_size: 1048576, // 1MB
    source_type: 'wechat',
    status: 'ready',
    versions_count: 1,
    created_at: '2026-09-25T08:00:00Z',
  };

  it('renders material title, format tag, and formatted size correctly', () => {
    const wrapper = mount(MaterialCard, {
      props: {
        material: baseMaterial,
      },
    });

    expect(wrapper.text()).toContain('高数上册核心笔记');
    expect(wrapper.text()).toContain('PDF');
    expect(wrapper.text()).toContain('1.0 MB');
  });

  it('renders corresponding status capsule for different states', async () => {
    const states: Array<{ status: MaterialItem['status']; expectedText: string }> = [
      { status: 'ready', expectedText: '已完成' },
      { status: 'parsing', expectedText: '解析中' },
      { status: 'retake_required', expectedText: '待重新拍摄' },
      { status: 'failed', expectedText: '解析失败' },
    ];

    for (const item of states) {
      const wrapper = mount(MaterialCard, {
        props: {
          material: {
            ...baseMaterial,
            status: item.status,
          },
        },
      });

      expect(wrapper.text()).toContain(item.expectedText);
    }
  });

  it('renders natural copywriting for knowledge points without forbidden terms', () => {
    const wrapper = mount(MaterialCard, {
      props: {
        material: {
          ...baseMaterial,
          key_points_count: 12,
        } as unknown as MaterialItem,
      },
    });

    expect(wrapper.text()).toContain('12 个核心考点');
    const text = wrapper.text();
    expect(text).not.toContain('切片:');
    expect(text).not.toContain('乱码率');
    expect(text).not.toContain('BM25');
  });

  it('strictly adheres to zero-emoji policy across rendered text', () => {
    const wrapper = mount(MaterialCard, {
      props: {
        material: baseMaterial,
      },
    });

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });

  it('emits click event when the card container is tapped', async () => {
    const wrapper = mount(MaterialCard, {
      props: {
        material: baseMaterial,
      },
    });

    await wrapper.find('.material-card').trigger('tap');
    expect(wrapper.emitted('click')).toBeTruthy();
    expect(wrapper.emitted('click')?.[0]).toEqual([baseMaterial]);
  });

  it('emits delete event when delete button is triggered', async () => {
    const showModalSpy = vi.fn();
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.showModal = showModalSpy;

    showModalSpy.mockImplementation(
      (options: { success?: (res: { confirm: boolean }) => void }) => {
        if (options.success) {
          options.success({ confirm: true });
        }
      },
    );

    const wrapper = mount(MaterialCard, {
      props: {
        material: baseMaterial,
      },
    });

    const deleteBtn = wrapper.find('.delete-btn');
    expect(deleteBtn.exists()).toBe(true);

    await deleteBtn.trigger('tap');
    expect(showModalSpy).toHaveBeenCalled();
    expect(wrapper.emitted('delete')).toBeTruthy();
    expect(wrapper.emitted('delete')?.[0]).toEqual([baseMaterial]);
  });
});
