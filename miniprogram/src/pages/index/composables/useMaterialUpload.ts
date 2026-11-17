import type { MaterialItem } from '@/types'

interface MaterialUploadDeps {
  getCurrentFolderId: () => string
  uploadMaterial: (filePath: string, title?: string, folderId?: string) => Promise<MaterialItem>
  onUploaded: (item: MaterialItem) => void
}

/** 资料上传入口（优先微信聊天文档，回退本地图片选择）。 */
export function useMaterialUpload(deps: MaterialUploadDeps) {
  const uploadSelectedFile = async (
    filePath: string,
    title: string | undefined,
    targetFolderId: string | undefined,
    showSuccessToast: boolean,
  ) => {
    uni.showLoading({ title: '正在上传讲义...' })
    try {
      const item = await deps.uploadMaterial(filePath, title, targetFolderId)
      uni.hideLoading()
      if (showSuccessToast) {
        uni.showToast({ title: '上传成功', icon: 'success' })
      }
      deps.onUploaded(item)
    } catch {
      uni.hideLoading()
    }
  }

  const chooseFile = () => {
    const currentFolderId = deps.getCurrentFolderId()
    const targetFolderId =
      currentFolderId === 'all' || currentFolderId === '__none__' ? undefined : currentFolderId

    // #ifdef MP-WEIXIN
    const wxAny = (globalThis as any).wx || (typeof wx !== 'undefined' ? wx : null)
    if (wxAny && wxAny.chooseMessageFile) {
      wxAny.chooseMessageFile({
        count: 1,
        type: 'all',
        success: async (res: any) => {
          const file = res.tempFiles?.[0]
          if (file) {
            await uploadSelectedFile(file.path, file.name, targetFolderId, true)
          }
        },
        fail: () => {},
      })
      return
    }
    // #endif

    uni.chooseImage({
      count: 1,
      success: async (res: any) => {
        const path = res.tempFilePaths?.[0]
        if (path) {
          await uploadSelectedFile(path, '学习讲义', targetFolderId, false)
        }
      },
    })
  }

  return { chooseFile }
}
