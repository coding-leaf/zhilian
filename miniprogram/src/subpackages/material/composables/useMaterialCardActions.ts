/**
 * 资料卡片交互动作组合式函数。
 *
 * 封装资料详情跳转、删除、重试与手动触发解析，避免列表页体积超限。
 * 遵循「Store 不发请求」铁律：网络调用统一经 `src/api/`。
 */

import { useMaterialStore } from '@/stores/materialStore';
import { deleteMaterial, retryMaterial, triggerMaterialParse } from '../../../api/material';
import type { MaterialItem } from '../../../types/material';

export interface UseMaterialCardActionsOptions {
  /** 数据变更后的刷新回调（删除/重试/触发解析后重新拉取列表）。 */
  refresh: () => Promise<void>;
}

export function useMaterialCardActions(options: UseMaterialCardActionsOptions) {
  const { refresh } = options;
  const materialStore = useMaterialStore();

  function handleCardClick(item: MaterialItem): void {
    materialStore.setActiveMaterial(item.id, item.current_version_id || null);
    uni.navigateTo({
      url: `../detail/index?material_id=${item.id}`,
      fail: () => uni.showToast({ title: '页面打开失败', icon: 'none' }),
    });
  }

  async function handleCardDelete(item: MaterialItem): Promise<void> {
    try {
      await deleteMaterial(item.id);
      uni.showToast({ title: '已删除资料', icon: 'none' });
      await refresh();
    } catch {
      uni.showToast({ title: '删除失败', icon: 'none' });
    }
  }

  async function handleCardRetry(item: MaterialItem): Promise<void> {
    try {
      if (typeof uni !== 'undefined' && typeof uni.showLoading === 'function') {
        uni.showLoading({ title: '正在发起重试...' });
      }
      await retryMaterial(item.id);
      uni.showToast({ title: '已发起重新解析', icon: 'success' });
      await refresh();
    } catch {
      uni.showToast({ title: '重试失败，请稍后重试', icon: 'none' });
    } finally {
      if (typeof uni !== 'undefined' && typeof uni.hideLoading === 'function') {
        uni.hideLoading();
      }
    }
  }

  async function handleCardTriggerParse(item: MaterialItem): Promise<void> {
    try {
      if (typeof uni !== 'undefined' && typeof uni.showLoading === 'function') {
        uni.showLoading({ title: '正在开始解析...' });
      }
      await triggerMaterialParse(item.id);
      uni.showToast({ title: '已开始解析', icon: 'success' });
      await refresh();
    } catch {
      uni.showToast({ title: '发起解析失败，请稍后重试', icon: 'none' });
    } finally {
      if (typeof uni !== 'undefined' && typeof uni.hideLoading === 'function') {
        uni.hideLoading();
      }
    }
  }

  return { handleCardClick, handleCardDelete, handleCardRetry, handleCardTriggerParse };
}
