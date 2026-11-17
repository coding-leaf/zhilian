import { ref, type ComputedRef } from 'vue'
import type { FolderItem } from '@/types'

interface FolderModalDeps {
  activeFolderDetail: ComputedRef<FolderItem | null>
  createFolder: (name: string) => Promise<FolderItem>
  renameFolder: (folderId: string, name: string) => Promise<FolderItem>
  archiveFolder: (folderId: string) => Promise<void>
  onSwitched: (folderId: string) => Promise<void>
  onArchived: () => Promise<void>
}

/** 课程文件夹创建/重命名弹窗与归档确认编排。 */
export function useFolderModal(deps: FolderModalDeps) {
  const showFolderModal = ref(false)
  const initialFolderName = ref('')
  const folderToRename = ref<{ id: string; name: string } | null>(null)
  const isCreatingFolder = ref(false)

  const openCreateFolderModal = () => {
    folderToRename.value = null
    initialFolderName.value = ''
    showFolderModal.value = true
  }

  const openRenameFolder = () => {
    const active = deps.activeFolderDetail.value
    if (!active) return
    folderToRename.value = { id: active.id, name: active.name }
    initialFolderName.value = active.name
    showFolderModal.value = true
  }

  const closeFolderModal = () => {
    showFolderModal.value = false
  }

  const submitFolderModal = async (rawName: string) => {
    const name = rawName.trim()
    if (!name) {
      uni.showToast({ title: '请输入课程名称', icon: 'none' })
      return
    }
    isCreatingFolder.value = true
    try {
      const folder = folderToRename.value
        ? await deps.renameFolder(folderToRename.value.id, name)
        : await deps.createFolder(name)
      uni.showToast({ title: folderToRename.value ? '课程已重命名' : '创建成功', icon: 'success' })
      closeFolderModal()
      await deps.onSwitched(folder.id)
    } catch (err: any) {
      uni.showToast({ title: err?.message || '创建失败', icon: 'none' })
    } finally {
      isCreatingFolder.value = false
    }
  }

  const confirmArchiveFolder = () => {
    const folder = deps.activeFolderDetail.value
    if (!folder) return
    uni.showModal({
      title: '归档课程',
      content: `归档「${folder.name}」？课程资料仍会保留。`,
      confirmColor: '#b91c1c',
      success: async ({ confirm }) => {
        if (!confirm) return
        await deps.archiveFolder(folder.id)
        await deps.onArchived()
        uni.showToast({ title: '课程已归档', icon: 'success' })
      },
    })
  }

  return {
    showFolderModal,
    initialFolderName,
    folderToRename,
    isCreatingFolder,
    openCreateFolderModal,
    openRenameFolder,
    closeFolderModal,
    submitFolderModal,
    confirmArchiveFolder,
  }
}
