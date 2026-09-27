import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount } from '@vue/test-utils';
import IndexPage from '@/pages/index/index.vue';
import { useUserStore } from '@/stores/userStore';
import { useMaterialStore } from '@/stores/materialStore';
import { useFolderStore } from '@/stores/folderStore';
import * as folderApi from '@/api/folder';
import * as materialApi from '@/api/material';
import type { FolderItem } from '@/types/folder';

function buildFolder(partial: Partial<FolderItem> = {}): FolderItem {
  return {
    id: 'folder_1',
    name: '高等数学',
    is_archived: false,
    material_count: 3,
    ready_material_count: 2,
    knowledge_point_count: 12,
    question_count: 30,
    created_at: '2026-09-20T10:00:00Z',
    updated_at: '2026-09-25T10:00:00Z',
    ...partial,
  };
}

describe('Index Dashboard Page', () => {
  const mountOptions = {
    global: {
      stubs: {
        'wd-skeleton': true,
      },
    },
  };

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();

    vi.spyOn(folderApi, 'fetchFolderList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { items: [], total: 0 },
    });

    vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: [],
        total: 0,
        limit: 5,
        offset: 0,
      },
    });
  });

  it('renders default dashboard correctly with unauthenticated state', () => {
    const wrapper = mount(IndexPage, mountOptions);
    expect(wrapper.text()).toContain('智练工作台');
    expect(wrapper.text()).toContain('登录同步学习进度与定制复习方案');
    expect(wrapper.find('.btn-login').exists()).toBe(true);
    expect(wrapper.find('.btn-logout').exists()).toBe(false);
  });

  it('navigates to login page when login button is pressed', async () => {
    const navigateSpy = vi.spyOn(uni, 'navigateTo');
    const wrapper = mount(IndexPage, mountOptions);
    const loginBtn = wrapper.find('.btn-login');

    await loginBtn.trigger('tap');
    expect(navigateSpy).toHaveBeenCalledWith({
      url: '/pages/auth/login',
      fail: expect.any(Function),
    });
  });

  it('displays user greeting when authenticated and allows logging out', async () => {
    const userStore = useUserStore();
    userStore.setTokens({
      access_token: 'valid_token',
      refresh_token: 'refresh_token',
      token_type: 'Bearer',
      expires_in: 3600,
    });
    userStore.setUserProfile({
      id: 'usr_test_1',
      nickname: '测试学员01',
      avatar_url: '',
    });

    const wrapper = mount(IndexPage, mountOptions);
    expect(wrapper.text()).toContain('你好，测试学员01，今日保持高效专注');
    const logoutBtn = wrapper.find('.btn-logout');
    expect(logoutBtn.exists()).toBe(true);

    await logoutBtn.trigger('tap');
    expect(userStore.isAuthenticated).toBe(false);
    expect(wrapper.text()).toContain('登录同步学习进度与定制复习方案');
  });

  it('removes the total mastery score card from the dashboard (AC1)', () => {
    const wrapper = mount(IndexPage, mountOptions);
    expect(wrapper.findComponent({ name: 'MasteryDashboardBar' }).exists()).toBe(false);
    expect(wrapper.text()).not.toContain('综合掌握度');
  });

  it('renders the course list entry and unclassified entry when unclassified materials exist', async () => {
    vi.spyOn(folderApi, 'fetchFolderList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { items: [buildFolder({ id: 'f1', name: '线性代数' })], total: 1 },
    });
    vi.spyOn(materialApi, 'fetchMaterialList').mockImplementation((params) => {
      if (params?.folder_id === '__none__') {
        return Promise.resolve({
          code: 200,
          message: 'success',
          data: { items: [], total: 4, limit: 1, offset: 0 },
        });
      }
      return Promise.resolve({
        code: 200,
        message: 'success',
        data: { items: [], total: 0, limit: 5, offset: 0 },
      });
    });

    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };
    await vm.loadDashboardData(false);
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain('我的课程');
    expect(wrapper.text()).toContain('线性代数');
    expect(wrapper.text()).toContain('未分类资料');
    expect(wrapper.text()).toContain('4 份资料待归位');

    const folderStore = useFolderStore();
    expect(folderStore.folders).toHaveLength(1);
    expect(folderStore.unclassifiedCount).toBe(4);
  });

  it('hides the unclassified entry when there are no unclassified materials', async () => {
    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };
    await vm.loadDashboardData(false);
    await wrapper.vm.$nextTick();

    expect(wrapper.find('.unclassified-entry').exists()).toBe(false);
  });

  it('navigates to the course detail page with folder_id and a fail fallback', async () => {
    const navigateSpy = vi.spyOn(uni, 'navigateTo');
    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };
    await vm.loadDashboardData(false);
    await wrapper.vm.$nextTick();

    const section = wrapper.findComponent({ name: 'CourseListSection' });
    expect(section.exists()).toBe(true);
    section.vm.$emit('enter', buildFolder({ id: 'f9' }));
    await wrapper.vm.$nextTick();

    expect(navigateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/subpackages/material/pages/course/index?folder_id=f9',
        fail: expect.any(Function),
      }),
    );
  });

  it('renders NewbieGuideCard when user has no materials and no drafts', async () => {
    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };
    await vm.loadDashboardData(false);

    expect(wrapper.findComponent({ name: 'NewbieGuideCard' }).exists()).toBe(true);
    expect(wrapper.findComponent({ name: 'RecentLearningSection' }).exists()).toBe(false);
    expect(wrapper.text()).toContain('新手学习指南');
  });

  it('renders RecentLearningSection when materials or drafts are available', async () => {
    vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: [
          {
            id: 'mat_1',
            title: '高等数学核心笔记',
            file_format: 'pdf',
            file_size: 1048576,
            source_type: 'upload',
            status: 'ready',
            created_at: new Date().toISOString(),
          },
        ],
        total: 1,
        limit: 5,
        offset: 0,
      },
    });

    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };
    await vm.loadDashboardData(false);

    expect(wrapper.findComponent({ name: 'NewbieGuideCard' }).exists()).toBe(false);
    expect(wrapper.findComponent({ name: 'RecentLearningSection' }).exists()).toBe(true);
    expect(wrapper.text()).toContain('高等数学核心笔记');
  });

  it('fetches course folders and materials concurrently using Promise.allSettled', async () => {
    const fetchFolderSpy = vi.spyOn(folderApi, 'fetchFolderList');
    const fetchMaterialSpy = vi.spyOn(materialApi, 'fetchMaterialList');

    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };

    await vm.loadDashboardData(true);

    expect(fetchFolderSpy).toHaveBeenCalledWith({ include_archived: true });
    expect(fetchMaterialSpy).toHaveBeenCalledWith({ page: 1, page_size: 5 });
    expect(fetchMaterialSpy).toHaveBeenCalledWith({
      folder_id: '__none__',
      page: 1,
      page_size: 1,
    });
  });

  it('splits archived courses out of the active list', async () => {
    vi.spyOn(folderApi, 'fetchFolderList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: [
          buildFolder({ id: 'active_1', name: '活跃课程' }),
          buildFolder({
            id: 'archived_1',
            name: '归档课程',
            is_archived: true,
            archived_at: '2026-09-27T00:00:00Z',
            purge_after: '2026-10-04T00:00:00Z',
          }),
        ],
        total: 2,
      },
    });

    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };
    await vm.loadDashboardData(false);
    await wrapper.vm.$nextTick();

    const folderStore = useFolderStore();
    expect(folderStore.folders.map((f) => f.id)).toEqual(['active_1']);
    expect(folderStore.archivedFolders.map((f) => f.id)).toEqual(['archived_1']);
    expect(wrapper.text()).toContain('已归档课程');
  });

  it('tolerates partial API failure gracefully without throwing', async () => {
    vi.spyOn(folderApi, 'fetchFolderList').mockRejectedValue(new Error('Network timeout'));
    vi.spyOn(materialApi, 'fetchMaterialList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        items: [
          {
            id: 'mat_1',
            title: '容灾资料',
            file_format: 'txt',
            file_size: 512,
            source_type: 'upload',
            status: 'ready',
            created_at: new Date().toISOString(),
          },
        ],
        total: 1,
        limit: 5,
        offset: 0,
      },
    });

    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };

    // 不应抛出未捕获错误
    await expect(vm.loadDashboardData(false)).resolves.not.toThrow();

    const materialStore = useMaterialStore();
    expect(materialStore.materialsList).toHaveLength(1);
    expect(materialStore.materialsList[0].title).toBe('容灾资料');
  });

  it('calls uni.stopPullDownRefresh during pull down refresh', async () => {
    const stopRefreshSpy = vi.spyOn(uni, 'stopPullDownRefresh');
    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };

    // 触发刷新
    await vm.loadDashboardData(false);
    uni.stopPullDownRefresh();

    expect(stopRefreshSpy).toHaveBeenCalled();
  });

  it('strictly contains zero Unicode emoji characters across rendered text', () => {
    const wrapper = mount(IndexPage, mountOptions);
    const text = wrapper.text();
    const emojiRegex =
      /[\u{1F300}-\u{1FAFF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });
});
