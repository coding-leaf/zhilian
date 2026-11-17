import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import type { MaterialItem } from '@/types'
import { safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import { describeFailure, RequestError } from '@/utils/requestError'

interface MaterialUploadDeps {
  getCurrentFolderId: () => string
  uploadMaterial: (filePath: string, title?: string, folderId?: string) => Promise<MaterialItem>
  startParse?: (materialId: string, title?: string) => Promise<unknown>
  refreshList?: () => Promise<unknown>
  onUploaded: (item: MaterialItem) => void
}

const IMAGE_SOURCE_TYPES: Array<'album' | 'camera'> = ['album', 'camera']
const IMAGE_SIZE_TYPES: Array<'compressed' | 'original'> = ['compressed', 'original']
const MESSAGE_FILE_EXTENSIONS = ['pdf', 'docx', 'doc', 'txt', 'md']

function buildFallbackImageName(): string {
  return `讲义图片_${Date.now()}.jpg`
}

/** 资料上传入口（微信小程序支持聊天文档与拍照/相册双通道，上传成功后自动触发后台解析）。 */
export function useMaterialUpload(deps: MaterialUploadDeps) {
  const triggerAutoParse = async (item: MaterialItem, fallbackTitle?: string): Promise<boolean> => {
    const title = item.title || fallbackTitle || '学习资料'
    try {
      if (deps.startParse) {
        await deps.startParse(item.id, title)
        return true
      }
      const taskStore = useBackgroundTaskStore()
      await taskStore.startMaterialParse(item.id, title)
      return true
    } catch (err) {
      console.error('[upload] auto-start parse failed', err)
      return false
    }
  }

  const uploadSelectedFile = async (
    filePath: string,
    title: string | undefined,
    targetFolderId: string | undefined,
  ) => {
    try {
      let parseStarted = false
      const item = await withBlockingLoading('正在上传讲义...', async () => {
        const uploaded = await deps.uploadMaterial(filePath, title, targetFolderId)
        parseStarted = await triggerAutoParse(uploaded, title)
        if (deps.refreshList) {
          await deps.refreshList().catch(() => undefined)
        }
        return uploaded
      })
      safeShowToast(
        parseStarted ? '上传成功，已开始后台解析' : '上传成功，可手动点击开始解析',
        'success',
      )
      deps.onUploaded(item)
    } catch (err: any) {
      if (!(err instanceof RequestError)) {
        safeShowToast(describeFailure(err, '上传失败，请重试'))
      }
    }
  }

  const pickImageAndUpload = (targetFolderId: string | undefined) => {
    uni.chooseImage({
      count: 1,
      sizeType: IMAGE_SIZE_TYPES,
      sourceType: IMAGE_SOURCE_TYPES,
      success: async (res: any) => {
        const filePath = res?.tempFilePaths?.[0] || res?.tempFiles?.[0]?.path
        if (!filePath) return
        const fileName = res?.tempFiles?.[0]?.name || buildFallbackImageName()
        await uploadSelectedFile(filePath, fileName, targetFolderId)
      },
      fail: () => {},
    })
  }

  const pickWechatMessageFile = (wxAny: any, targetFolderId: string | undefined) => {
    if (!wxAny?.chooseMessageFile) {
      safeShowToast('当前环境不支持聊天文档选择，请拍照或从相册选择')
      return
    }
    wxAny.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: MESSAGE_FILE_EXTENSIONS,
      success: async (res: any) => {
        const file = res?.tempFiles?.[0]
        if (file?.path) {
          await uploadSelectedFile(file.path, file.name, targetFolderId)
        }
      },
      fail: () => {},
    })
  }

  const chooseFile = () => {
    const currentFolderId = deps.getCurrentFolderId()
    const targetFolderId =
      currentFolderId === 'all' || currentFolderId === '__none__' ? undefined : currentFolderId

    // #ifdef MP-WEIXIN
    const wxAny = (globalThis as any).wx || (typeof wx !== 'undefined' ? wx : null)
    if (typeof uni.showActionSheet === 'function') {
      uni.showActionSheet({
        itemList: ['从微信聊天选择文档 (PDF/Word/TXT)', '拍照或从相册选择讲义图片'],
        success: ({ tapIndex }) => {
          if (tapIndex === 0) {
            pickWechatMessageFile(wxAny, targetFolderId)
            return
          }
          if (tapIndex === 1) {
            pickImageAndUpload(targetFolderId)
          }
        },
        fail: () => {},
      })
      return
    }
    // #endif

    pickImageAndUpload(targetFolderId)
  }

  return { chooseFile, uploadSelectedFile }
}
