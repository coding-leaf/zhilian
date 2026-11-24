import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import type { MaterialItem } from '@/types'
import { extractUserErrorMessage, safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import { RequestError } from '@/utils/requestError'

declare const wx:
  | {
      chooseMessageFile?: (options: Record<string, any>) => void
    }
  | undefined

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
const UPLOAD_NAVIGATE_DELAY_MS = 300

function buildFallbackImageName(): string {
  return `讲义图片_${Date.now()}.jpg`
}

function isUserCancelError(err: unknown): boolean {
  const errMsg =
    typeof (err as { errMsg?: unknown })?.errMsg === 'string'
      ? (err as { errMsg: string }).errMsg.toLowerCase()
      : ''
  return errMsg.includes('cancel')
}

function handlePickerFail(err: unknown, scene: 'media' | 'messageFile'): void {
  if (isUserCancelError(err)) return
  console.error(`[upload] ${scene} picker failed`, err)
  const errno = (err as { errno?: number })?.errno
  const errMsg =
    typeof (err as { errMsg?: unknown })?.errMsg === 'string'
      ? (err as { errMsg: string }).errMsg
      : ''
  if (errno === 104 || errno === 112 || /privacy|auth\s*deny|permission/i.test(errMsg)) {
    safeShowToast('请先同意隐私协议并开启相册/文件权限')
    return
  }
  safeShowToast(
    scene === 'media'
      ? '图片选择失败，请检查相册或相机权限'
      : '文件选择失败，请检查权限后重试',
  )
}

function getWechatMessageFilePicker(): ((options: Record<string, any>) => void) | null {
  if (typeof wx !== 'undefined' && wx && typeof wx.chooseMessageFile === 'function') {
    return wx.chooseMessageFile.bind(wx)
  }
  return null
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
      safeShowToast({
        title: parseStarted ? '上传成功，已开始后台解析' : '上传成功，可手动点击开始解析',
        icon: 'none',
      })
      setTimeout(() => {
        deps.onUploaded(item)
      }, UPLOAD_NAVIGATE_DELAY_MS)
    } catch (err: any) {
      if (!(err instanceof RequestError)) {
        safeShowToast(extractUserErrorMessage(err, '上传失败，请重试'))
      }
    }
  }

  const pickImageAndUpload = (targetFolderId: string | undefined) => {
    uni.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sizeType: IMAGE_SIZE_TYPES,
      sourceType: IMAGE_SOURCE_TYPES,
      success: async (res: any) => {
        const firstFile = res?.tempFiles?.[0]
        const filePath = firstFile?.tempFilePath || firstFile?.path || res?.tempFilePaths?.[0]
        if (!filePath) return
        const fileName = firstFile?.name || buildFallbackImageName()
        await uploadSelectedFile(filePath, fileName, targetFolderId)
      },
      fail: (err: unknown) => {
        handlePickerFail(err, 'media')
      },
    })
  }

  const pickWechatMessageFile = (
    chooseMessageFile: ((options: Record<string, any>) => void) | null,
    targetFolderId: string | undefined,
  ) => {
    if (!chooseMessageFile) {
      safeShowToast('当前环境不支持聊天文档选择，请拍照或从相册选择')
      return
    }
    chooseMessageFile({
      count: 1,
      type: 'file',
      extension: MESSAGE_FILE_EXTENSIONS,
      success: async (res: any) => {
        const file = res?.tempFiles?.[0]
        if (file?.path) {
          await uploadSelectedFile(file.path, file.name, targetFolderId)
        }
      },
      fail: (err: unknown) => {
        handlePickerFail(err, 'messageFile')
      },
    })
  }

  const chooseFile = () => {
    const currentFolderId = deps.getCurrentFolderId()
    const targetFolderId =
      currentFolderId === 'all' || currentFolderId === '__none__' ? undefined : currentFolderId

    // #ifdef MP-WEIXIN
    const messageFilePicker = getWechatMessageFilePicker()
    if (typeof uni.showActionSheet === 'function') {
      uni.showActionSheet({
        itemList: ['从微信聊天选择文档 (PDF/Word/TXT)', '拍照或从相册选择讲义图片'],
        success: ({ tapIndex }) => {
          if (tapIndex === 0) {
            pickWechatMessageFile(messageFilePicker, targetFolderId)
            return
          }
          if (tapIndex === 1) {
            pickImageAndUpload(targetFolderId)
          }
        },
        fail: (err: unknown) => {
          if (!isUserCancelError(err)) {
            console.error('[upload] showActionSheet failed', err)
          }
        },
      })
      return
    }
    // #endif

    pickImageAndUpload(targetFolderId)
  }

  return { chooseFile, uploadSelectedFile }
}
