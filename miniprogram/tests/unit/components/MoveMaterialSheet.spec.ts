import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import MoveMaterialSheet from '@/components/course/MoveMaterialSheet.vue';
import type { FolderItem } from '@/types/folder';

function makeFolder(id: string, name: string): FolderItem {
  return {
    id,
    name,
    is_archived: false,
    material_count: 0,
    ready_material_count: 0,
    knowledge_point_count: 0,
    question_count: 0,
    created_at: '2026-09-20T00:00:00Z',
  };
}

describe('MoveMaterialSheet.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the unclassified option and every active course', () => {
    const wrapper = mount(MoveMaterialSheet, {
      props: {
        visible: true,
        folders: [makeFolder('f1', '高等数学'), makeFolder('f2', '线性代数')],
      },
    });

    expect(wrapper.text()).toContain('移动到课程');
    expect(wrapper.text()).toContain('未分类');
    expect(wrapper.text()).toContain('高等数学');
    expect(wrapper.text()).toContain('线性代数');
  });

  it('emits select(folderId) and closes when a course is chosen', async () => {
    const wrapper = mount(MoveMaterialSheet, {
      props: { visible: true, folders: [makeFolder('f1', '高等数学')] },
    });

    const options = wrapper.findAll('.course-option');
    await options[1].trigger('tap');

    expect(wrapper.emitted('select')?.[0]).toEqual(['f1']);
    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
  });

  it('emits select(null) when moving back to unclassified', async () => {
    const wrapper = mount(MoveMaterialSheet, {
      props: { visible: true, folders: [makeFolder('f1', '高等数学')], currentFolderId: 'f1' },
    });

    const options = wrapper.findAll('.course-option');
    await options[0].trigger('tap');

    expect(wrapper.emitted('select')?.[0]).toEqual([null]);
  });

  it('closes without emitting select when the current course is re-selected', async () => {
    const wrapper = mount(MoveMaterialSheet, {
      props: { visible: true, folders: [makeFolder('f1', '高等数学')], currentFolderId: 'f1' },
    });

    const options = wrapper.findAll('.course-option');
    await options[1].trigger('tap');

    expect(wrapper.emitted('select')).toBeUndefined();
    expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
  });

  it('hides the unclassified option when allowUnclassified is false', () => {
    const wrapper = mount(MoveMaterialSheet, {
      props: {
        visible: true,
        folders: [makeFolder('f1', '高等数学')],
        allowUnclassified: false,
      },
    });

    expect(wrapper.text()).not.toContain('未分类');
    expect(wrapper.findAll('.course-option')).toHaveLength(1);
  });
});
