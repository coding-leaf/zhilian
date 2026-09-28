import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount, flushPromises } from '@vue/test-utils';
import ProfilePage from '@/pages/profile/index.vue';
import { useUserStore } from '@/stores/userStore';
import * as userApi from '@/api/user';
import * as folderApi from '@/api/folder';
import * as diagnosisApi from '@/api/diagnosis';

describe('Profile & Data Governance Page (profile/index.vue)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    vi.spyOn(userApi, 'fetchUserProfile').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'u_test_123',
        nickname: '学术探索者',
        avatar_url: '',
        created_at: '2026-09-01T00:00:00Z',
      },
    });
  });

  it('renders profile page with assets overview and zero Unicode emoji', async () => {
    const userStore = useUserStore();
    userStore.setTokens({
      access_token: 'tok_1',
      refresh_token: 'tok_2',
      token_type: 'Bearer',
      expires_in: 7200,
    });
    userStore.setProfile({
      id: 'u_test_123',
      nickname: '学术探索者',
      avatar_url: '',
      created_at: '2026-09-01T00:00:00Z',
    });

    vi.spyOn(diagnosisApi, 'fetchMasteryOverview').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        overall_mastery_score: 0.9,
        mastered_count: 24,
        proficient_count: 6,
        weak_count: 2,
        unlearned_count: 1,
      },
    });

    vi.spyOn(diagnosisApi, 'fetchWrongBook').mockResolvedValue({
      code: 0,
      message: 'success',
      data: { items: [], total: 0, limit: 50, offset: 0 },
    });

    vi.spyOn(folderApi, 'fetchFolderList').mockResolvedValue({
      code: 0,
      message: 'success',
      data: { items: [], total: 0 },
    });

    const wrapper = mount(ProfilePage);
    await flushPromises();

    expect(wrapper.text()).toContain('学术探索者');
    expect(wrapper.text()).toContain('学习资产总览');
    expect(wrapper.text()).toContain('已掌握考点');
    expect(wrapper.text()).toContain('已攻克错题');
    expect(wrapper.text()).toContain('数据治理与隐私安全');

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });

  it('manages archived courses: opening drawer, restoring folder, and updating list', async () => {
    const userStore = useUserStore();
    userStore.setTokens({
      access_token: 'tok_1',
      refresh_token: 'tok_2',
      token_type: 'Bearer',
      expires_in: 7200,
    });
    userStore.setProfile({
      id: 'u_test_123',
      nickname: '学术探索者',
      avatar_url: '',
      created_at: '2026-09-01T00:00:00Z',
    });

    vi.spyOn(folderApi, 'fetchFolderList').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: [
          {
            id: 'arch_1',
            name: '编译原理（历史）',
            is_archived: true,
            material_count: 3,
            ready_material_count: 3,
            knowledge_point_count: 12,
            question_count: 20,
            created_at: '2026-09-01T00:00:00Z',
          },
        ],
        total: 1,
      },
    });

    const restoreSpy = vi.spyOn(folderApi, 'restoreFolder').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'arch_1',
        name: '编译原理（历史）',
        is_archived: false,
        material_count: 3,
        ready_material_count: 3,
        knowledge_point_count: 12,
        question_count: 20,
        created_at: '2026-09-01T00:00:00Z',
      },
    });

    const wrapper = mount(ProfilePage);
    await flushPromises();

    // Click on "归档课程管理箱" menu item
    const archiveMenuItem = wrapper.findAll('.menu-item')[0];
    await archiveMenuItem.trigger('tap');
    await flushPromises();

    expect(wrapper.text()).toContain('编译原理（历史）');
    const restoreBtn = wrapper.find('.btn-restore');
    expect(restoreBtn.exists()).toBe(true);

    await restoreBtn.trigger('tap');
    await flushPromises();

    expect(restoreSpy).toHaveBeenCalledWith('arch_1');
  });

  it('performs account deletion with two-step modal confirmation and storage clearing', async () => {
    const userStore = useUserStore();
    userStore.setTokens({
      access_token: 'tok_1',
      refresh_token: 'tok_2',
      token_type: 'Bearer',
      expires_in: 7200,
    });
    userStore.setProfile({
      id: 'u_test_123',
      nickname: '学术探索者',
      avatar_url: '',
      created_at: '2026-09-01T00:00:00Z',
    });

    const deleteSpy = vi.spyOn(userApi, 'deleteAccount').mockResolvedValue({
      code: 0,
      message: 'success',
      data: { message: '账号已注销', success: true },
    });

    const modalSpy = vi.fn((options: unknown) => {
      const opt = options as { success: (res: { confirm: boolean }) => void };
      opt.success({ confirm: true });
      return Promise.resolve();
    });
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.showModal = modalSpy;

    const wrapper = mount(ProfilePage);
    await flushPromises();

    const deleteItem = wrapper.find('.danger-item');
    expect(deleteItem.exists()).toBe(true);
    await deleteItem.trigger('tap');
    await flushPromises();

    // Two modals were shown
    expect(modalSpy).toHaveBeenCalledTimes(2);
    expect(deleteSpy).toHaveBeenCalledTimes(1);
    expect(userStore.isAuthenticated).toBe(false);
  });
});
