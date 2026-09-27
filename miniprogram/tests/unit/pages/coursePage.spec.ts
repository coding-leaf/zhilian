import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { onLoad } from '@dcloudio/uni-app';
import { setActivePinia, createPinia } from 'pinia';
import CourseDetailPage from '@/subpackages/material/pages/course/index.vue';
import MaterialUpload from '@/components/common/MaterialUpload.vue';
import * as folderApi from '@/api/folder';
import * as materialApi from '@/api/material';
import type { FolderItem } from '@/types/folder';
import type { MaterialItem } from '@/types/material';

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 10));

const folder: FolderItem = {
  id: 'f1',
  name: '高等数学',
  is_archived: false,
  material_count: 1,
  ready_material_count: 1,
  knowledge_point_count: 8,
  question_count: 20,
  created_at: '2026-09-20T00:00:00Z',
};

const material: MaterialItem = {
  id: 'mat_1',
  title: '高数笔记',
  file_format: 'pdf',
  file_size: 1024,
  source_type: 'local',
  status: 'ready',
  folder_id: 'f1',
  created_at: '2026-09-25T00:00:00Z',
};

describe('CourseDetailPage (course/index.vue)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();

    vi.spyOn(folderApi, 'fetchFolderDetail').mockResolvedValue({
      code: 200,
      message: 'success',
      data: folder,
    });
    vi.spyOn(folderApi, 'fetchFolderList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { items: [folder], total: 1 },
    });
    vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { items: [material], total: 1, limit: 50, offset: 0 },
    });
  });

  it('resolves folder_id from the route query and renders the in-course materials', async () => {
    const wrapper = mount(CourseDetailPage);
    await flush();

    const onLoadMock = vi.mocked(onLoad);
    const loadCallback = onLoadMock.mock.calls.at(-1)?.[0] as
      ((query?: Record<string, string>) => void) | undefined;
    loadCallback?.({ folder_id: 'f1' });
    await wrapper.vm.$nextTick();

    expect(wrapper.vm.targetFolderId).toBe('f1');

    await wrapper.vm.loadFolder();
    await wrapper.vm.loadMaterials();
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain('高等数学');
    expect(wrapper.text()).toContain('高数笔记');
    expect(wrapper.text()).toContain('上传资料');
  });

  it('moves an in-course material to another course and removes it locally', async () => {
    const moveSpy = vi
      .spyOn(materialApi, 'moveMaterialFolder')
      .mockResolvedValue({ code: 200, message: 'success', data: { ...material, folder_id: 'f2' } });

    const wrapper = mount(CourseDetailPage);
    await flush();
    wrapper.vm.targetFolderId = 'f1';
    await wrapper.vm.loadMaterials();
    await wrapper.vm.$nextTick();

    wrapper.vm.handleOpenMove(material);
    expect(wrapper.vm.moveVisible).toBe(true);

    await wrapper.vm.handleMoveSelect('f2');

    expect(moveSpy).toHaveBeenCalledWith('mat_1', 'f2');
    expect(wrapper.vm.listData).toHaveLength(0);
  });

  it('opens the question list placeholder with folder_id and a fail fallback (C4 wiring pending)', async () => {
    const navigateSpy = vi.spyOn(uni, 'navigateTo');
    const wrapper = mount(CourseDetailPage);
    await flush();
    wrapper.vm.targetFolderId = 'f1';

    wrapper.vm.handleGoQuestions();

    expect(navigateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/subpackages/material/pages/questions/index?folder_id=f1',
        fail: expect.any(Function),
      }),
    );
  });

  it('uploads attributed to this course by passing folderId to the upload modal', async () => {
    const wrapper = mount(CourseDetailPage);
    await flush();
    wrapper.vm.targetFolderId = 'f1';
    await wrapper.vm.$nextTick();

    const upload = wrapper.findComponent(MaterialUpload);
    expect(upload.exists()).toBe(true);
    expect(upload.props('folderId')).toBe('f1');
  });

  it('strictly contains zero Unicode emoji characters across rendered text', async () => {
    const wrapper = mount(CourseDetailPage);
    await flush();
    const emojiRegex =
      /[\u{1F300}-\u{1FAFF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });
});
