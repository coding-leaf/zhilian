import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import CourseKnowledgePointPicker from '@/components/course/CourseKnowledgePointPicker.vue';
import * as folderApi from '@/api/folder';

const groups = [
  {
    material_id: 'mat_1',
    material_title: '高数笔记',
    knowledge_points: [
      { id: 'kp_1', name: '导数', level: 1, parent_id: null },
      { id: 'kp_2', name: '积分', level: 1, parent_id: null },
    ],
  },
  {
    material_id: 'mat_2',
    material_title: '线代讲义',
    knowledge_points: [{ id: 'kp_3', name: '矩阵', level: 1, parent_id: null }],
  },
];

function mountPicker(props: Record<string, unknown> = {}) {
  return mount(CourseKnowledgePointPicker, { props: { folderId: 'f1', ...props } });
}

describe('CourseKnowledgePointPicker.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(folderApi, 'fetchFolderKnowledgePoints').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { folder_id: 'f1', groups, total: 3 },
    });
  });

  it('loads and renders knowledge points grouped by material', async () => {
    const wrapper = mountPicker();
    await flushPromises();

    expect(folderApi.fetchFolderKnowledgePoints).toHaveBeenCalledWith('f1');
    expect(wrapper.text()).toContain('高数笔记');
    expect(wrapper.text()).toContain('线代讲义');
    expect(wrapper.text()).toContain('导数');
    expect(wrapper.text()).toContain('矩阵');
    expect(wrapper.text()).toContain('默认：课程全部考点');
  });

  it('emits updated selection when a knowledge point is toggled', async () => {
    const wrapper = mountPicker();
    await flushPromises();

    wrapper.vm.togglePoint('kp_1');
    expect(wrapper.emitted('update:selectedIds')?.[0]).toEqual([['kp_1']]);

    await wrapper.setProps({ selectedIds: ['kp_1'] });
    wrapper.vm.togglePoint('kp_1');
    expect(wrapper.emitted('update:selectedIds')?.[1]).toEqual([[]]);
  });

  it('toggles every point of a material group at once', async () => {
    const wrapper = mountPicker();
    await flushPromises();

    wrapper.vm.toggleGroup(groups[0] as never);
    expect(wrapper.emitted('update:selectedIds')?.[0]).toEqual([['kp_1', 'kp_2']]);
  });

  it('shows a retryable error state when loading fails', async () => {
    vi.mocked(folderApi.fetchFolderKnowledgePoints).mockRejectedValue(new Error('offline'));
    const wrapper = mountPicker();
    await flushPromises();

    expect(wrapper.vm.error).toBe(true);
    expect(wrapper.text()).toContain('考点加载失败');

    vi.mocked(folderApi.fetchFolderKnowledgePoints).mockResolvedValue({
      code: 200,
      message: 'success',
      data: { folder_id: 'f1', groups, total: 3 },
    });
    await wrapper.vm.loadPoints();
    await flushPromises();
    expect(wrapper.vm.error).toBe(false);
    expect(wrapper.text()).toContain('导数');
  });

  it('shows an explanatory message when the course has no points', async () => {
    vi.mocked(folderApi.fetchFolderKnowledgePoints).mockResolvedValue({
      code: 200,
      message: 'success',
      data: { folder_id: 'f1', groups: [], total: 0 },
    });
    const wrapper = mountPicker();
    await flushPromises();

    expect(wrapper.text()).toContain('课程暂无可用考点');
  });
});
