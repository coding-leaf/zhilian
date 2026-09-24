import { describe, expect, it, beforeEach, vi } from 'vitest';
import { createApp } from '@/main';
import { setActivePinia, createPinia } from 'pinia';
import App from '@/App.vue';
import { shallowMount } from '@vue/test-utils';
import { useUserStore } from '@/stores/userStore';

describe('App & Main Assembly', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('createApp should initialize Vue application instance with Pinia', () => {
    const { app, pinia } = createApp();
    expect(app).toBeDefined();
    expect(pinia).toBeDefined();
  });

  it('App.vue should mount cleanly and initialize store credentials onLaunch', () => {
    const userStore = useUserStore();
    const initSpy = vi.spyOn(userStore, 'initFromStorage');

    const wrapper = shallowMount(App);
    expect(wrapper.exists()).toBe(true);
    expect(initSpy).toHaveBeenCalledTimes(1);
  });
});
