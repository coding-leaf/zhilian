import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { FolderItem, FolderKnowledgePointsResult } from '@/types'
import {
  apiListFolders,
  apiCreateFolder,
  apiRenameFolder,
  apiArchiveFolder,
  apiGetFolderKnowledgePoints,
} from '@/api'

export const useFolderStore = defineStore('folder', () => {
  const folders = ref<FolderItem[]>([])
  const currentFolderId = ref<string>('all') // 'all' | '__none__' | folder_id
  const currentFolderKnowledgePoints = ref<FolderKnowledgePointsResult | null>(null)
  const isLoading = ref<boolean>(false)

  // 1. 获取课程文件夹列表
  const loadFolders = async (includeArchived = false) => {
    isLoading.value = true
    try {
      const res = await apiListFolders(includeArchived)
      folders.value = res.items || []
      return folders.value
    } catch (err) {
      console.error('Failed to load folders:', err)
      return []
    } finally {
      isLoading.value = false
    }
  }

  // 2. 创建课程文件夹
  const createFolder = async (name: string): Promise<FolderItem> => {
    const newFolder = await apiCreateFolder(name)
    folders.value.unshift(newFolder)
    currentFolderId.value = newFolder.id
    return newFolder
  }

  // 3. 重命名文件夹
  const renameFolder = async (folderId: string, name: string): Promise<FolderItem> => {
    const updated = await apiRenameFolder(folderId, name)
    const idx = folders.value.findIndex((f) => f.id === folderId)
    if (idx !== -1) {
      folders.value[idx] = updated
    }
    return updated
  }

  // 4. 归档文件夹
  const archiveFolder = async (folderId: string) => {
    await apiArchiveFolder(folderId)
    folders.value = folders.value.filter((f) => f.id !== folderId)
    if (currentFolderId.value === folderId) {
      currentFolderId.value = 'all'
    }
  }

  // 5. 加载课程下按资料分组的知识点列表
  const loadFolderKnowledgePoints = async (folderId: string): Promise<FolderKnowledgePointsResult> => {
    isLoading.value = true
    try {
      const result = await apiGetFolderKnowledgePoints(folderId)
      currentFolderKnowledgePoints.value = result
      return result
    } finally {
      isLoading.value = false
    }
  }

  const setCurrentFolderId = (folderId: string) => {
    currentFolderId.value = folderId
  }

  return {
    folders,
    currentFolderId,
    currentFolderKnowledgePoints,
    isLoading,
    loadFolders,
    createFolder,
    renameFolder,
    archiveFolder,
    loadFolderKnowledgePoints,
    setCurrentFolderId,
  }
})
