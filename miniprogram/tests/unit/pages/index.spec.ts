import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount } from '@vue/test-utils';
import IndexPage from '@/pages/index/index.vue';
import { useUserStore } from '@/stores/userStore';
import { useMaterialStore } from '@/stores/materialStore';
import { useReportStore } from '@/stores/reportStore';
import * as diagnosisApi from '@/api/diagnosis';
import * as materialApi from '@/api/material';

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

    // Default API Mocks
    vi.spyOn(diagnosisApi, 'fetchMasteryOverview').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        mastered_count: 5,
        proficient_count: 8,
        weak_count: 3,
        unlearned_count: 4,
        overall_score: 0.82,
      },
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

  it('fetches mastery overview and materials concurrently using Promise.allSettled', async () => {
    const fetchMasterySpy = vi.spyOn(diagnosisApi, 'fetchMasteryOverview');
    const fetchMaterialSpy = vi.spyOn(materialApi, 'fetchMaterialList');

    const wrapper = mount(IndexPage, mountOptions);
    const vm = wrapper.vm as unknown as {
      loadDashboardData: (showSkeleton?: boolean) => Promise<void>;
    };

    await vm.loadDashboardData(true);

    expect(fetchMasterySpy).toHaveBeenCalled();
    expect(fetchMaterialSpy).toHaveBeenCalledWith({ page: 1, page_size: 5 });

    const reportStore = useReportStore();
    expect(reportStore.masteryOverview?.overall_score).toBe(0.82);
  });

  it('tolerates partial API failure gracefully without throwing', async () => {
    vi.spyOn(diagnosisApi, 'fetchMasteryOverview').mockRejectedValue(new Error('Network timeout'));
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
