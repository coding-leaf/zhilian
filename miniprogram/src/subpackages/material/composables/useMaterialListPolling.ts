/**
 * 资料列表页多条目解析状态轮询组合式函数。
 *
 * 与 useMaterialPolling（单条目）互补：本组合式函数对列表内所有 pending/parsing
 * 条目并发轮询，遵循自适应指数退避（1.5x，上限 8000ms）与 180s 超时熔断。
 * 页面隐藏或列表进入终态时即刻清除定时器。
 */

import { onUnmounted, getCurrentInstance, type Ref } from 'vue';
import { fetchMaterialStatus } from '../../../api/material';
import type { MaterialItem } from '../../../types/material';

export interface UseMaterialListPollingOptions {
  /** 列表数据源（原地合并轮询结果）。 */
  items: Ref<MaterialItem[]>;
  /** 页面可见性；为 false 时停止轮询。 */
  isPageVisible: Ref<boolean>;
  /** 单条目状态刷新回调（用于同步全局 store）。 */
  onItemUpdated?: (item: MaterialItem) => void;
}

export function useMaterialListPolling(options: UseMaterialListPollingOptions) {
  const { items, isPageVisible, onItemUpdated } = options;
  const backoffFactor = 1.5;
  const maxPollInterval = 8000;
  const maxTimeoutMs = 180000;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let currentPollInterval = 1500;
  let pollStartTime = 0;

  function isPending(item: MaterialItem): boolean {
    return item.status === 'parsing' || item.status === 'pending';
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function scheduleNextPoll(): void {
    stopPolling();
    const delay = currentPollInterval;
    currentPollInterval = Math.min(
      Math.round(currentPollInterval * backoffFactor),
      maxPollInterval,
    );

    pollTimer = setTimeout(async () => {
      if (!isPageVisible.value || Date.now() - pollStartTime > maxTimeoutMs) {
        stopPolling();
        return;
      }
      await pollPendingItems();
    }, delay);
  }

  async function pollPendingItems(): Promise<void> {
    const pendingItems = items.value.filter(isPending);
    if (pendingItems.length === 0) {
      stopPolling();
      return;
    }

    try {
      const results = await Promise.allSettled(
        pendingItems.map((item) => fetchMaterialStatus(item.id)),
      );
      for (const res of results) {
        if (res.status === 'fulfilled' && res.value?.data) {
          const updated = res.value.data;
          const targetIndex = items.value.findIndex((m) => m.id === updated.id);
          if (targetIndex >= 0) {
            items.value[targetIndex] = { ...items.value[targetIndex], ...updated };
            onItemUpdated?.(items.value[targetIndex]);
          }
        }
      }
    } catch {
      // 忽略偶发网络轮询异常
    }

    const stillPending = items.value.some(isPending);
    if (stillPending && isPageVisible.value && Date.now() - pollStartTime <= maxTimeoutMs) {
      scheduleNextPoll();
    } else {
      stopPolling();
    }
  }

  function checkAndStartPolling(): void {
    stopPolling();
    if (!isPageVisible.value) {
      return;
    }
    if (!items.value.some(isPending)) {
      return;
    }
    pollStartTime = Date.now();
    currentPollInterval = 1500;
    scheduleNextPoll();
  }

  if (getCurrentInstance()) {
    onUnmounted(() => stopPolling());
  }

  return { stopPolling, checkAndStartPolling, isPending };
}
