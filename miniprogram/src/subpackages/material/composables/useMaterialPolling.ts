/**
 * 资料解析状态智能轮询组合式函数。
 *
 * 负责在资料处于 pending 或 parsing 阶段时定时查询最新解析状态。
 * 遵循生命周期守护与自适应退避原则：
 * - 初始 1500ms 轮询间隔，采用自适应指数退避 (1.5x，上限 8000ms)；
 * - 状态转为 COMPLETED / READY / FAILED / RETAKE_REQUIRED 时自动终止；
 * - 默认 180s (3分钟) 最大超时兜底熔断，超时自动停止并提醒用户；
 * - 绑定 onUnmounted 钩子，组件销毁时强力清理定时器；
 * - 单文件 <= 300 行，零 Emoji。
 */

import { ref, unref, onUnmounted, getCurrentInstance, type Ref } from 'vue';
import { fetchMaterialStatus } from '../../../api/material';
import type { MaterialItem, MaterialStatus } from '../../../types/material';

export interface UseMaterialPollingOptions {
  /** 初始轮询间隔毫秒数，默认 1500ms (1.5s) */
  interval?: number;
  /** 指数退避增量倍数，默认 1.5 */
  backoffFactor?: number;
  /** 最大单次轮询间隔毫秒数，默认 8000ms (8s) */
  maxInterval?: number;
  /** 最大轮询超时毫秒数，默认 180000ms (3分钟) */
  maxTimeout?: number;
  /** 是否在 startPolling 时立即触发首次请求，默认 true */
  immediate?: boolean;
  /** 状态变更回调 */
  onStatusChange?: (status: MaterialStatus) => void;
  /** 解析完成回调 */
  onComplete?: (data: MaterialItem) => void;
  /** 错误回调 */
  onError?: (err: unknown) => void;
  /** 超时兜底回调 */
  onTimeout?: () => void;
}

export function useMaterialPolling(
  materialId: Ref<string> | string,
  options: UseMaterialPollingOptions = {},
) {
  const {
    interval = 1500,
    backoffFactor = 1.5,
    maxInterval = 8000,
    maxTimeout = 180000,
    immediate = true,
    onStatusChange,
    onComplete,
    onError,
    onTimeout,
  } = options;

  const status = ref<MaterialStatus | null>(null);
  const materialData = ref<MaterialItem | null>(null);
  const isPolling = ref<boolean>(false);
  const error = ref<unknown | null>(null);

  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let timeoutTimer: ReturnType<typeof setTimeout> | null = null;
  let startTime = 0;
  let currentInterval = interval;

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
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    if (timeoutTimer !== null) {
      clearTimeout(timeoutTimer);
      timeoutTimer = null;
    }
    isPolling.value = false;
  };

  const handleTimeout = () => {
    stopPolling();
    if (onTimeout) {
      onTimeout();
    }
    if (typeof uni !== 'undefined' && typeof uni.showToast === 'function') {
      uni.showToast({
        title: '解析等待超时，请稍后刷新查看',
        icon: 'none',
      });
    }
  };

  const scheduleNext = () => {
    if (!isPolling.value) {
      return;
    }
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    const delay = currentInterval;
    currentInterval = Math.min(Math.round(currentInterval * backoffFactor), maxInterval);

    pollTimer = setTimeout(() => {
      void poll();
    }, delay);
  };

  const poll = async () => {
    const id = unref(materialId);
    if (!id || !isPolling.value) {
      return;
    }

    if (startTime > 0 && Date.now() - startTime >= maxTimeout) {
      handleTimeout();
      return;
    }

    try {
      const res = await fetchMaterialStatus(id);
      if (!isPolling.value) {
        return;
      }
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
          return;
        }
      }
      scheduleNext();
    } catch (err: unknown) {
      if (!isPolling.value) {
        return;
      }
      error.value = err;
      if (onError) {
        onError(err);
      }
      scheduleNext();
    }
  };

  const startPolling = () => {
    if (isPolling.value) {
      return;
    }

    isPolling.value = true;
    error.value = null;
    startTime = Date.now();
    currentInterval = interval;

    timeoutTimer = setTimeout(() => {
      handleTimeout();
    }, maxTimeout);

    if (immediate) {
      void poll();
    } else {
      scheduleNext();
    }
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
