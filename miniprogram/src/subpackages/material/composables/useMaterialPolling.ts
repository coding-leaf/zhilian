/**
 * 资料解析状态智能轮询组合式函数。
 *
 * 负责在资料处于 pending 或 parsing 阶段时定时查询最新解析状态。
 * 遵循生命周期守护与零泄漏原则：
 * - 2000ms 默认轮询周期；
 * - 状态转为 COMPLETED / READY / FAILED / RETAKE_REQUIRED 时自动终止；
 * - 60s 最大超时兜底熔断，杜绝无休止请求；
 * - 绑定 onUnmounted 钩子，组件销毁时强力清理定时器；
 * - 单文件 <= 300 行，零 Emoji。
 */

import { ref, unref, onUnmounted, getCurrentInstance, type Ref } from 'vue';
import { fetchMaterialStatus } from '../../../api/material';
import type { MaterialItem, MaterialStatus } from '../../../types/material';

export interface UseMaterialPollingOptions {
  /** 轮询间隔毫秒数，默认 2000ms (2s) */
  interval?: number;
  /** 最大轮询超时毫秒数，默认 60000ms (60s) */
  maxTimeout?: number;
  /** 是否在 startPolling 时立即触发首次请求，默认 true */
  immediate?: boolean;
  /** 状态变更回调 */
  onStatusChange?: (status: MaterialStatus) => void;
  /** 解析完成回调 */
  onComplete?: (data: MaterialItem) => void;
  /** 错误回调 */
  onError?: (err: unknown) => void;
}

export function useMaterialPolling(
  materialId: Ref<string> | string,
  options: UseMaterialPollingOptions = {},
) {
  const {
    interval = 2000,
    maxTimeout = 60000,
    immediate = true,
    onStatusChange,
    onComplete,
    onError,
  } = options;

  const status = ref<MaterialStatus | null>(null);
  const materialData = ref<MaterialItem | null>(null);
  const isPolling = ref<boolean>(false);
  const error = ref<unknown | null>(null);

  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let timeoutTimer: ReturnType<typeof setTimeout> | null = null;
  let startTime = 0;

  const isTerminalStatus = (currentStatus: string): boolean => {
    const normalized = currentStatus.toUpperCase();
    return (
      normalized === 'COMPLETED' ||
      normalized === 'READY' ||
      normalized === 'FAILED' ||
      normalized === 'RETAKE_REQUIRED'
    );
  };

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (timeoutTimer !== null) {
      clearTimeout(timeoutTimer);
      timeoutTimer = null;
    }
    isPolling.value = false;
  };

  const poll = async () => {
    const id = unref(materialId);
    if (!id) {
      return;
    }

    if (startTime > 0 && Date.now() - startTime >= maxTimeout) {
      stopPolling();
      return;
    }

    try {
      const res = await fetchMaterialStatus(id);
      const data = res.data;
      if (data) {
        materialData.value = data;
        status.value = data.status;

        if (onStatusChange && data.status) {
          onStatusChange(data.status);
        }

        const normalized = String(data.status || '').toUpperCase();
        if (isTerminalStatus(normalized)) {
          stopPolling();
          if ((normalized === 'COMPLETED' || normalized === 'READY') && onComplete) {
            onComplete(data);
          }
        }
      }
    } catch (err: unknown) {
      error.value = err;
      if (onError) {
        onError(err);
      }
    }
  };

  const startPolling = () => {
    if (isPolling.value) {
      return;
    }

    isPolling.value = true;
    error.value = null;
    startTime = Date.now();

    timeoutTimer = setTimeout(() => {
      stopPolling();
    }, maxTimeout);

    if (immediate) {
      void poll();
    }

    pollTimer = setInterval(() => {
      void poll();
    }, interval);
  };

  if (getCurrentInstance()) {
    onUnmounted(() => {
      stopPolling();
    });
  }

  return {
    status,
    materialData,
    material: materialData,
    isPolling,
    error,
    startPolling,
    stopPolling,
  };
}
