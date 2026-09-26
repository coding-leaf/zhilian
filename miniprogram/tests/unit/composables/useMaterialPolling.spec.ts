import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { defineComponent } from 'vue';
import { mount } from '@vue/test-utils';
import * as materialApi from '@/api/material';
import { useMaterialPolling } from '@/subpackages/material/composables/useMaterialPolling';
import type { MaterialItem } from '@/types/material';

describe('useMaterialPolling Composable', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it('should poll status every 2s until COMPLETED is returned', async () => {
    const parsingResponse = {
      code: 0,
      message: 'success',
      data: { id: 'mat_1', status: 'parsing', title: 'Test 1' } as MaterialItem,
    };
    const completedResponse = {
      code: 0,
      message: 'success',
      data: { id: 'mat_1', status: 'COMPLETED', title: 'Test 1' } as MaterialItem,
    };

    const statusSpy = vi
      .spyOn(materialApi, 'fetchMaterialStatus')
      .mockResolvedValueOnce(parsingResponse)
      .mockResolvedValueOnce(completedResponse);

    const onComplete = vi.fn();
    const { status, isPolling, startPolling } = useMaterialPolling('mat_1', {
      interval: 2000,
      immediate: true,
      onComplete,
    });

    startPolling();
    expect(isPolling.value).toBe(true);

    // Initial immediate call
    await vi.advanceTimersByTimeAsync(0);
    expect(statusSpy).toHaveBeenCalledTimes(1);
    expect(status.value).toBe('parsing');
    expect(isPolling.value).toBe(true);

    // Advance 2s to trigger next poll
    await vi.advanceTimersByTimeAsync(2000);
    expect(statusSpy).toHaveBeenCalledTimes(2);
    expect(status.value).toBe('COMPLETED');
    expect(isPolling.value).toBe(false);
    expect(onComplete).toHaveBeenCalledWith(completedResponse.data);

    // Advance another 2s to verify no additional polls occur
    await vi.advanceTimersByTimeAsync(2000);
    expect(statusSpy).toHaveBeenCalledTimes(2);
  });

  it('should automatically terminate when status is FAILED', async () => {
    const failedResponse = {
      code: 0,
      message: 'success',
      data: { id: 'mat_2', status: 'failed', title: 'Test 2' } as MaterialItem,
    };

    const statusSpy = vi
      .spyOn(materialApi, 'fetchMaterialStatus')
      .mockResolvedValue(failedResponse);

    const { status, isPolling, startPolling } = useMaterialPolling('mat_2', {
      immediate: true,
    });

    startPolling();
    await vi.advanceTimersByTimeAsync(0);

    expect(statusSpy).toHaveBeenCalledTimes(1);
    expect(status.value).toBe('failed');
    expect(isPolling.value).toBe(false);

    await vi.advanceTimersByTimeAsync(4000);
    expect(statusSpy).toHaveBeenCalledTimes(1);
  });

  it('should automatically terminate when status is RETAKE_REQUIRED', async () => {
    const retakeResponse = {
      code: 0,
      message: 'success',
      data: { id: 'mat_3', status: 'RETAKE_REQUIRED', title: 'Test 3' } as MaterialItem,
    };

    const statusSpy = vi
      .spyOn(materialApi, 'fetchMaterialStatus')
      .mockResolvedValue(retakeResponse);

    const { status, isPolling, startPolling } = useMaterialPolling('mat_3', {
      immediate: true,
    });

    startPolling();
    await vi.advanceTimersByTimeAsync(0);

    expect(statusSpy).toHaveBeenCalledTimes(1);
    expect(status.value).toBe('RETAKE_REQUIRED');
    expect(isPolling.value).toBe(false);

    await vi.advanceTimersByTimeAsync(4000);
    expect(statusSpy).toHaveBeenCalledTimes(1);
  });

  it('should automatically stop when reaching 60s timeout limit', async () => {
    const parsingResponse = {
      code: 0,
      message: 'success',
      data: { id: 'mat_timeout', status: 'parsing', title: 'Timeout Doc' } as MaterialItem,
    };

    const statusSpy = vi
      .spyOn(materialApi, 'fetchMaterialStatus')
      .mockResolvedValue(parsingResponse);

    const { isPolling, startPolling } = useMaterialPolling('mat_timeout', {
      interval: 2000,
      maxTimeout: 60000,
      immediate: false,
    });

    startPolling();
    expect(isPolling.value).toBe(true);

    // Fast-forward past 60s
    await vi.advanceTimersByTimeAsync(60000);
    expect(isPolling.value).toBe(false);

    const callCountAtTimeout = statusSpy.mock.calls.length;

    // Advance further to verify polling has permanently ceased
    await vi.advanceTimersByTimeAsync(10000);
    expect(statusSpy.mock.calls.length).toBe(callCountAtTimeout);
  });

  it('should stop polling immediately when stopPolling is called manually', async () => {
    const parsingResponse = {
      code: 0,
      message: 'success',
      data: { id: 'mat_manual', status: 'parsing', title: 'Doc' } as MaterialItem,
    };

    const statusSpy = vi
      .spyOn(materialApi, 'fetchMaterialStatus')
      .mockResolvedValue(parsingResponse);

    const { isPolling, startPolling, stopPolling } = useMaterialPolling('mat_manual', {
      interval: 2000,
      immediate: true,
    });

    startPolling();
    await vi.advanceTimersByTimeAsync(0);
    expect(statusSpy).toHaveBeenCalledTimes(1);
    expect(isPolling.value).toBe(true);

    stopPolling();
    expect(isPolling.value).toBe(false);

    await vi.advanceTimersByTimeAsync(4000);
    expect(statusSpy).toHaveBeenCalledTimes(1);
  });

  it('should clean up timers automatically on component unmount', async () => {
    const parsingResponse = {
      code: 0,
      message: 'success',
      data: { id: 'mat_lifecycle', status: 'parsing', title: 'Doc' } as MaterialItem,
    };

    const statusSpy = vi
      .spyOn(materialApi, 'fetchMaterialStatus')
      .mockResolvedValue(parsingResponse);

    let pollingInstance: ReturnType<typeof useMaterialPolling> | null = null;

    const TestComponent = defineComponent({
      setup() {
        pollingInstance = useMaterialPolling('mat_lifecycle', {
          interval: 2000,
          immediate: true,
        });
        pollingInstance.startPolling();
        return {};
      },
      template: '<div>test</div>',
    });

    const wrapper = mount(TestComponent);
    await vi.advanceTimersByTimeAsync(0);
    expect(statusSpy).toHaveBeenCalledTimes(1);
    expect(pollingInstance!.isPolling.value).toBe(true);

    // Unmount component to trigger onUnmounted lifecycle hook
    wrapper.unmount();
    expect(pollingInstance!.isPolling.value).toBe(false);

    // Further timers should not trigger requests
    await vi.advanceTimersByTimeAsync(4000);
    expect(statusSpy).toHaveBeenCalledTimes(1);
  });

  it('should adaptively back off polling interval by 1.5x up to maxInterval', async () => {
    const parsingResponse = {
      code: 0,
      message: 'success',
      data: { id: 'mat_backoff', status: 'parsing', title: 'Doc' } as MaterialItem,
    };

    const statusSpy = vi
      .spyOn(materialApi, 'fetchMaterialStatus')
      .mockResolvedValue(parsingResponse);

    const { isPolling, startPolling } = useMaterialPolling('mat_backoff', {
      interval: 1500,
      backoffFactor: 1.5,
      maxInterval: 8000,
      immediate: true,
    });

    startPolling();
    expect(isPolling.value).toBe(true);

    // Call 1: Immediate at t=0
    await vi.advanceTimersByTimeAsync(0);
    expect(statusSpy).toHaveBeenCalledTimes(1);

    // 1st interval is 1500ms
    await vi.advanceTimersByTimeAsync(1499);
    expect(statusSpy).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(statusSpy).toHaveBeenCalledTimes(2);

    // 2nd interval is round(1500 * 1.5) = 2250ms
    await vi.advanceTimersByTimeAsync(2249);
    expect(statusSpy).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(statusSpy).toHaveBeenCalledTimes(3);

    // 3rd interval is round(2250 * 1.5) = 3375ms
    await vi.advanceTimersByTimeAsync(3374);
    expect(statusSpy).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(statusSpy).toHaveBeenCalledTimes(4);

    // 4th interval is round(3375 * 1.5) = 5063ms
    await vi.advanceTimersByTimeAsync(5062);
    expect(statusSpy).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(1);
    expect(statusSpy).toHaveBeenCalledTimes(5);

    // 5th interval is round(5063 * 1.5) = 7595ms
    await vi.advanceTimersByTimeAsync(7594);
    expect(statusSpy).toHaveBeenCalledTimes(5);
    await vi.advanceTimersByTimeAsync(1);
    expect(statusSpy).toHaveBeenCalledTimes(6);

    // 6th interval is min(round(7595 * 1.5), 8000) = 8000ms (capped at maxInterval)
    await vi.advanceTimersByTimeAsync(7999);
    expect(statusSpy).toHaveBeenCalledTimes(6);
    await vi.advanceTimersByTimeAsync(1);
    expect(statusSpy).toHaveBeenCalledTimes(7);
  });

  it('should trigger onTimeout and showToast after default 3 minutes (180000ms)', async () => {
    const parsingResponse = {
      code: 0,
      message: 'success',
      data: { id: 'mat_default_timeout', status: 'parsing', title: 'Doc' } as MaterialItem,
    };

    vi.spyOn(materialApi, 'fetchMaterialStatus').mockResolvedValue(parsingResponse);
    const toastSpy = vi.spyOn(uni, 'showToast');
    const onTimeout = vi.fn();

    const { isPolling, startPolling } = useMaterialPolling('mat_default_timeout', {
      immediate: true,
      onTimeout,
    });

    startPolling();
    expect(isPolling.value).toBe(true);

    // Advance 180s
    await vi.advanceTimersByTimeAsync(180000);

    expect(isPolling.value).toBe(false);
    expect(onTimeout).toHaveBeenCalledTimes(1);
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '解析等待超时，请稍后刷新查看',
        icon: 'none',
      }),
    );
  });

  it('should gracefully handle API error and continue backoff scheduling', async () => {
    const errorSpy = vi.fn();
    const networkError = new Error('Network timeout');
    const statusSpy = vi
      .spyOn(materialApi, 'fetchMaterialStatus')
      .mockRejectedValueOnce(networkError)
      .mockResolvedValueOnce({
        code: 0,
        message: 'success',
        data: { id: 'mat_err', status: 'COMPLETED', title: 'Resolved' } as MaterialItem,
      });

    const { isPolling, error, startPolling } = useMaterialPolling('mat_err', {
      interval: 1500,
      backoffFactor: 1.5,
      immediate: true,
      onError: errorSpy,
    });

    startPolling();
    await vi.advanceTimersByTimeAsync(0);
    expect(statusSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith(networkError);
    expect(error.value).toBe(networkError);
    expect(isPolling.value).toBe(true);

    // After backoff of 1500ms, retry occurs and completes
    await vi.advanceTimersByTimeAsync(1500);
    expect(statusSpy).toHaveBeenCalledTimes(2);
    expect(isPolling.value).toBe(false);
  });
});
