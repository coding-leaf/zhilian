import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import CourseListSection from '@/components/home/CourseListSection.vue';
import CourseCreateDialog from '@/components/course/CourseCreateDialog.vue';
import * as folderApi from '@/api/folder';
import type { FolderItem } from '@/types/folder';

function makeFolder(id: string, overrides: Partial<FolderItem> = {}): FolderItem {
  return {
    id,
    name: `课程-${id}`,
    is_archived: false,
    material_count: 1,
    ready_material_count: 1,
    knowledge_point_count: 2,
    question_count: 3,
    created_at: '2026-09-20T00:00:00Z',
    ...overrides,
  };
}

describe('CourseListSection.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty state when no courses exist', () => {
    const wrapper = mount(CourseListSection);
    expect(wrapper.text()).toContain('我的课程');
    expect(wrapper.text()).toContain('还没有课程');
  });

  it('creates a course and emits changed', async () => {
    const createSpy = vi
      .spyOn(folderApi, 'createFolder')
      .mockResolvedValue({ code: 200, message: 'success', data: makeFolder('f1') });

    const wrapper = mount(CourseListSection);
    const dialog = wrapper.findComponent(CourseCreateDialog);
    dialog.vm.$emit('confirm', '新课程');
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(createSpy).toHaveBeenCalledWith({ name: '新课程' });
    expect(wrapper.emitted('changed')).toBeTruthy();
  });

  it('archives a course after the confirm modal resolves', async () => {
    const archiveSpy = vi
      .spyOn(folderApi, 'archiveFolder')
      .mockResolvedValue({ code: 200, message: 'success', data: {} as never });

    const uniRef = uni as unknown as {
      showModal: (options: {
        success?: (res: { confirm: boolean; cancel: boolean }) => void;
      }) => void;
    };
    const originalShowModal = uniRef.showModal;
    uniRef.showModal = (options) => {
      options.success?.({ confirm: true, cancel: false });
    };

    try {
      const wrapper = mount(CourseListSection, {
        props: { folders: [makeFolder('f1', { name: '待归档' })] },
      });

      wrapper.findComponent({ name: 'CourseCard' }).vm.$emit('archive', makeFolder('f1'));
      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(archiveSpy).toHaveBeenCalledWith('f1');
      expect(wrapper.emitted('changed')).toBeTruthy();
    } finally {
      uniRef.showModal = originalShowModal;
    }
  });

  it('restores an archived course and shows remaining grace time', async () => {
    const restoreSpy = vi
      .spyOn(folderApi, 'restoreFolder')
      .mockResolvedValue({ code: 200, message: 'success', data: makeFolder('z') });

    const wrapper = mount(CourseListSection, {
      props: {
        archivedFolders: [
          makeFolder('z', {
            name: '归档课程',
            is_archived: true,
            purge_after: new Date(Date.now() + 6 * 24 * 3600 * 1000).toISOString(),
          }),
        ],
      },
    });

    expect(wrapper.text()).toContain('已归档课程');
    expect(wrapper.text()).toContain('剩余 5 天');

    wrapper.findComponent({ name: 'ArchivedCourseItem' }).vm.$emit('restore', makeFolder('z'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(restoreSpy).toHaveBeenCalledWith('z');
    expect(wrapper.emitted('changed')).toBeTruthy();
  });

  it('renders the unclassified entry only when unclassified materials exist', async () => {
    const wrapper = mount(CourseListSection, { props: { unclassifiedCount: 0 } });
    expect(wrapper.find('.unclassified-entry').exists()).toBe(false);

    await wrapper.setProps({ unclassifiedCount: 3 });
    expect(wrapper.find('.unclassified-entry').exists()).toBe(true);
    expect(wrapper.text()).toContain('3 份资料待归位');
  });
});
