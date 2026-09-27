import { describe, expect, it, beforeEach, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { mount, flushPromises } from '@vue/test-utils';
import LoginPage from '@/pages/auth/login.vue';
import { useUserStore } from '@/stores/userStore';
import * as authApi from '@/api/auth';
import * as userApi from '@/api/user';

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
    await flushPromises();

    expect(userStore.isAuthenticated).toBe(true);
    expect(userStore.tokens?.access_token).toBe('real_access_token_123');
    expect(showToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '登录成功',
      }),
    );
  });

  it('submits login payload without a hardcoded nickname', async () => {
    const loginSpy = vi.spyOn(authApi, 'loginByWechat').mockResolvedValue({
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
    await wrapper.find('.wechat-login-btn').trigger('tap');
    await flushPromises();

    expect(loginSpy).toHaveBeenCalledTimes(1);
    expect(loginSpy).toHaveBeenCalledWith({ code: 'dev_code' });
  });

  it('does not set tokens when login API fails', async () => {
    const userStore = useUserStore();
    const showToastSpy = vi.spyOn(uni, 'showToast');
    vi.spyOn(authApi, 'loginByWechat').mockRejectedValue(new Error('Network Error'));

    const wrapper = mount(LoginPage);
    const loginBtn = wrapper.find('.wechat-login-btn');

    await loginBtn.trigger('tap');
    await flushPromises();

    expect(userStore.isAuthenticated).toBe(false);
    expect(userStore.tokens).toBeNull();
    expect(showToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Network Error',
      }),
    );
  });

  it('clears session and warns when post-login profile hydration fails', async () => {
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
    vi.spyOn(userApi, 'fetchUserProfile').mockRejectedValue(new Error('网络异常'));

    const wrapper = mount(LoginPage);
    await wrapper.find('.wechat-login-btn').trigger('tap');
    await flushPromises();

    expect(userStore.tokens).toBeNull();
    expect(userStore.profile).toBeNull();
    expect(userStore.isAuthenticated).toBe(false);
    expect(showToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '获取用户资料失败，请重新登录',
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
