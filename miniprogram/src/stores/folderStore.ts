/**
 * Folder (Course) Store
 *
 * 管理课程文件夹列表、归档课程、未分类资料计数与当前课程详情。
 * 铁律：Store 内严禁发网络请求，全部网络交互经 `src/api/folder.ts` 由组件调用。
 */

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { FolderItem } from '../types/folder';

export const useFolderStore = defineStore('folder', () => {
  // State
  const folders = ref<FolderItem[]>([]);
  const archivedFolders = ref<FolderItem[]>([]);
  const unclassifiedCount = ref<number>(0);
  const currentFolder = ref<FolderItem | null>(null);

  // Getters
  const activeFolders = computed(() => folders.value);
  const hasFolders = computed(() => folders.value.length > 0);
  const hasUnclassified = computed(() => unclassifiedCount.value > 0);
  const archivedCount = computed(() => archivedFolders.value.length);

  function setFolders(list: FolderItem[]): void {
    folders.value = [...list];
  }

  function setArchivedFolders(list: FolderItem[]): void {
    archivedFolders.value = [...list];
  }

  /** 按 is_archived 拆分一次全量（含归档）列表，避免两次请求。 */
  function setFolderList(list: FolderItem[]): void {
    folders.value = list.filter((item) => !item.is_archived);
    archivedFolders.value = list.filter((item) => item.is_archived);
  }

  function upsertFolder(folder: FolderItem): void {
    const target = folder.is_archived ? archivedFolders.value : folders.value;
    const index = target.findIndex((item) => item.id === folder.id);
    if (index >= 0) {
      target[index] = folder;
    } else {
      target.unshift(folder);
    }
  }

  function removeFolder(folderId: string): void {
    folders.value = folders.value.filter((item) => item.id !== folderId);
    archivedFolders.value = archivedFolders.value.filter((item) => item.id !== folderId);
    if (currentFolder.value?.id === folderId) {
      currentFolder.value = null;
    }
  }

  function setCurrentFolder(folder: FolderItem | null): void {
    currentFolder.value = folder;
  }

  function setUnclassifiedCount(count: number): void {
    unclassifiedCount.value = Math.max(0, count);
  }

  function reset(): void {
    folders.value = [];
    archivedFolders.value = [];
    unclassifiedCount.value = 0;
    currentFolder.value = null;
  }

  return {
    folders,
    archivedFolders,
    unclassifiedCount,
    currentFolder,
    activeFolders,
    hasFolders,
    hasUnclassified,
    archivedCount,
    setFolders,
    setArchivedFolders,
    setFolderList,
    upsertFolder,
    removeFolder,
    setCurrentFolder,
    setUnclassifiedCount,
    reset,
  };
});

export default useFolderStore;
