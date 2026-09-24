import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount } from '@vue/test-utils';
import IndexPage from '@/pages/index/index.vue';
import { useUserStore } from '@/stores/userStore';
import { useMaterialStore } from '@/stores/materialStore';
import { usePracticeStore } from '@/stores/practiceStore';
import { useReportStore } from '@/stores/reportStore';

describe('Index Dashboard Page', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('renders default dashboard correctly with unauthenticated state', () => {
    const wrapper = mount(IndexPage);
    expect(wrapper.text()).toContain('智练工作台');
    expect(wrapper.text()).toContain('未登录');
    expect(wrapper.text()).toContain('资料总数');
    expect(wrapper.text()).toContain('0');
    expect(wrapper.text()).toContain('暂无练习');
    expect(wrapper.text()).toContain('未诊断');
    expect(wrapper.text()).toContain('0道');
  });

  it('displays user profile information when authenticated', async () => {
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

    const wrapper = mount(IndexPage);
    expect(wrapper.text()).toContain('测试学员01');
    expect(wrapper.text()).toContain('退出登录');
  });

  it('triggers logout when logout button is pressed', async () => {
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

    const wrapper = mount(IndexPage);
    const logoutBtn = wrapper.find('.logout-btn');
    expect(logoutBtn.exists()).toBe(true);

    await logoutBtn.trigger('tap');
    expect(userStore.isAuthenticated).toBe(false);
    expect(wrapper.text()).toContain('未登录');
  });

  it('updates dashboard counts dynamically from stores', async () => {
    const materialStore = useMaterialStore();
    materialStore.setMaterialsList([
      {
        id: 'mat_1',
        title: '测试教材',
        file_format: 'pdf',
        file_size: 1024,
        source_type: 'upload',
        status: 'ready',
        created_at: new Date().toISOString(),
      },
      {
        id: 'mat_2',
        title: '模拟真题',
        file_format: 'txt',
        file_size: 2048,
        source_type: 'upload',
        status: 'ready',
        created_at: new Date().toISOString(),
      },
    ]);

    const practiceStore = usePracticeStore();
    practiceStore.initSession('prac_1', [
      {
        id: 'q_1',
        type: 'single_choice',
        stem: '第一题',
        order_index: 0,
        options: [
          { key: 'A', text: 'A' },
          { key: 'B', text: 'B' },
        ],
      },
      {
        id: 'q_2',
        type: 'single_choice',
        stem: '第二题',
        order_index: 1,
        options: [
          { key: 'A', text: 'A' },
          { key: 'B', text: 'B' },
        ],
      },
    ]);

    const reportStore = useReportStore();
    reportStore.setReport({
      id: 'rep_1',
      practice_id: 'prac_1',
      overall_score: 0.88,
      mastery_rate: 88,
      weak_points: [
        {
          knowledge_point_id: 'kp_1',
          knowledge_name: '难点1',
          current_score: 0.35,
          actionable_advice: '建议多练',
        },
      ],
      created_at: new Date().toISOString(),
    });

    const wrapper = mount(IndexPage);
    expect(wrapper.text()).toContain('2');
    expect(wrapper.text()).toContain('1/2');
    expect(wrapper.text()).toContain('88分');
    expect(wrapper.text()).toContain('1道');
  });

  it('strictly contains zero Unicode emoji characters across rendered text', () => {
    const wrapper = mount(IndexPage);
    const text = wrapper.text();
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });
});
