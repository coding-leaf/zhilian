/**
 * 资料移动到课程的组合式函数。
 *
 * 维护移动目标选择状态、加载可用课程目标，执行 PATCH 移动并从本地列表剔除。
 * 遵循「Store 不发请求」铁律：网络调用统一经 `src/api/`。
 */

import { ref, type Ref } from 'vue';
import { moveMaterialFolder } from '../../../api/material';
import { fetchFolderList } from '../../../api/folder';
import { useFolderStore } from '@/stores/folderStore';
import { useMaterialStore } from '@/stores/materialStore';
import type { MaterialItem } from '../../../types/material';

export interface UseMaterialFolderMoveOptions {
  /** 当前页展示列表；移动成功后原地剔除。 */
  listData: Ref<MaterialItem[]>;
}

export function useMaterialFolderMove(options: UseMaterialFolderMoveOptions) {
  const { listData } = options;
  const folderStore = useFolderStore();
  const materialStore = useMaterialStore();
  const moveVisible = ref(false);
  const moveTarget = ref<MaterialItem | null>(null);

  async function loadMoveTargets(): Promise<void> {
    try {
      const res = await fetchFolderList();
      if (res?.data?.items) {
        folderStore.setFolders(res.data.items.filter((item) => !item.is_archived));
      }
    } catch {
      // 移动目标加载失败不阻断列表主流程
    }
  }

  function handleOpenMove(item: MaterialItem): void {
    moveTarget.value = item;
    moveVisible.value = true;
  }

  async function handleMoveSelect(folderId: string | null): Promise<void> {
    const target = moveTarget.value;
    if (!target) return;
    try {
      await moveMaterialFolder(target.id, folderId);
      listData.value = listData.value.filter((item) => item.id !== target.id);
      materialStore.updateMaterialFolder(target.id, folderId);
      uni.showToast({ title: '已移动资料', icon: 'success' });
    } catch {
      uni.showToast({ title: '移动失败，请重试', icon: 'none' });
    } finally {
      moveTarget.value = null;
    }
  }

  return { moveVisible, moveTarget, loadMoveTargets, handleOpenMove, handleMoveSelect };
}
