import { computed, ref, watch } from 'vue'
import type { FolderItem } from '@/types'

/**
 * 工作台全局助教独立状态管理。
 * 默认不绑定任何课程（coachFocusedFolderId = undefined，即全局学习模式），
 * 与顶部讲义列表筛选态 folderStore.currentFolderId 彻底解耦。
 */
export function useHomeCoach(getFolders: () => FolderItem[]) {
  const showCoachDrawer = ref(false)
  const coachFocusedFolderId = ref<string | undefined>(undefined)

  const coachSelectableFolders = computed<FolderItem[]>(() =>
    getFolders().filter((folder) => !folder.is_archived),
  )

  const coachFocusedFolder = computed<FolderItem | null>(() => {
    if (!coachFocusedFolderId.value) return null
    return (
      coachSelectableFolders.value.find((folder) => folder.id === coachFocusedFolderId.value) ??
      null
    )
  })

  watch(coachSelectableFolders, (folders) => {
    if (
      coachFocusedFolderId.value &&
      !folders.some((folder) => folder.id === coachFocusedFolderId.value)
    ) {
      coachFocusedFolderId.value = undefined
    }
  })

  const coachTitle = computed(() =>
    coachFocusedFolder.value
      ? `课程助教 · ${coachFocusedFolder.value.name}`
      : '全局学习助教',
  )

  const coachContextText = computed(() => {
    if (coachFocusedFolder.value) {
      return `当前聚焦课程「${coachFocusedFolder.value.name}」，涵盖 ${coachFocusedFolder.value.knowledge_point_count} 个考点与 ${coachFocusedFolder.value.ready_material_count} 份就绪资料。`
    }
    return '当前处于全局学习模式（未限定课程），支持全库就绪资料检索、薄弱考点复习规划与通用学科答疑。'
  })

  const openCoachDrawer = () => {
    showCoachDrawer.value = true
  }

  const selectCoachFolder = (folderId?: string) => {
    if (!folderId || folderId === 'all') {
      coachFocusedFolderId.value = undefined
      return
    }
    const exists = coachSelectableFolders.value.some((folder) => folder.id === folderId)
    coachFocusedFolderId.value = exists ? folderId : undefined
  }

  return {
    showCoachDrawer,
    coachFocusedFolderId,
    coachSelectableFolders,
    coachFocusedFolder,
    coachTitle,
    coachContextText,
    openCoachDrawer,
    selectCoachFolder,
  }
}
