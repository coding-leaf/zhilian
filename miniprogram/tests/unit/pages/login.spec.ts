import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount } from '@vue/test-utils';
import LoginPage from '@/pages/auth/login.vue';
import { useUserStore } from '@/stores/userStore';
import * as authApi from '@/api/auth';

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

  it('performs login authorization via api and updates user store with valid token', async () => {
    const userStore = useUserStore();
    const showToastSpy = vi.spyOn(uni, 'showToast');
    vi.spyOn(authApi, 'loginByWechat').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        access_token: 'real_access_token_123',
        refresh_token: 'real_refresh_token_123',
        token_type: 'Bearer',
        expires_in: 7200,
      },
    });

    const wrapper = mount(LoginPage);

    const loginBtn = wrapper.find('.wechat-login-btn');
    expect(loginBtn.exists()).toBe(true);

    await loginBtn.trigger('tap');

    expect(userStore.isAuthenticated).toBe(true);
    expect(userStore.tokens?.access_token).toBe('real_access_token_123');
    expect(showToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '登录成功',
      }),
    );
  });

  it('does not set tokens when login API fails', async () => {
    const userStore = useUserStore();
    const showToastSpy = vi.spyOn(uni, 'showToast');
    vi.spyOn(authApi, 'loginByWechat').mockRejectedValue(new Error('Network Error'));

    const wrapper = mount(LoginPage);
    const loginBtn = wrapper.find('.wechat-login-btn');

    await loginBtn.trigger('tap');

    expect(userStore.isAuthenticated).toBe(false);
    expect(userStore.tokens).toBeNull();
    expect(showToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Network Error',
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
