import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount } from '@vue/test-utils';
import LoginPage from '@/pages/auth/login.vue';
import { useUserStore } from '@/stores/userStore';

describe('Auth Login Page', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('renders login components with zero Unicode emoji', () => {
    const wrapper = mount(LoginPage);
    expect(wrapper.text()).toContain('账号授权登录');
    expect(wrapper.text()).toContain('微信一键登录');
    expect(wrapper.text()).toContain('返回工作台');

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(wrapper.text())).toBe(false);
  });

  it('performs mock login authorization and updates user store', async () => {
    const userStore = useUserStore();
    const showToastSpy = vi.spyOn(uni, 'showToast');
    const wrapper = mount(LoginPage);

    const loginBtn = wrapper.find('.wechat-login-btn');
    expect(loginBtn.exists()).toBe(true);

    await loginBtn.trigger('tap');

    expect(userStore.isAuthenticated).toBe(true);
    expect(userStore.profile?.id).toBe('usr_mock_001');
    expect(showToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '登录成功',
      }),
    );
  });

  it('navigates back to dashboard when back button is pressed', async () => {
    const reLaunchSpy = vi.spyOn(uni, 'reLaunch');
    const wrapper = mount(LoginPage);

    const backBtn = wrapper.find('.back-btn');
    expect(backBtn.exists()).toBe(true);

    await backBtn.trigger('tap');
    expect(reLaunchSpy).toHaveBeenCalledWith({
      url: '/pages/index/index',
    });
  });
});
