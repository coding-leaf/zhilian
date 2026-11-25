import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { resetLoadingGuardForTest } from '@/utils/loadingGuard'
import { SAFE_PAGE_STACK_LIMIT, safeNavigateTo } from '@/utils/navigation'
import { useMaterialUpload } from '@/pages/index/composables/useMaterialUpload'
import { useAuthStore } from '@/stores/auth'

const uniGlobal = globalThis as any

describe('safeNavigateTo page stack guard', () => {
  beforeEach(() => {
    resetLoadingGuardForTest()
  })

  afterEach(() => {
    delete uniGlobal.getCurrentPages
    vi.restoreAllMocks()
  })

  it('uses uni.navigateTo when page stack depth is below SAFE_PAGE_STACK_LIMIT', () => {
    uniGlobal.getCurrentPages = () => Array.from({ length: SAFE_PAGE_STACK_LIMIT - 1 }, () => ({}))
    const navSpy = vi.spyOn(uniGlobal.uni, 'navigateTo')
    const redirectSpy = vi.spyOn(uniGlobal.uni, 'redirectTo')

    safeNavigateTo('/subpackages/material/pages/course/index?id=m-1')

    expect(navSpy).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/subpackages/material/pages/course/index?id=m-1' }),
    )
    expect(redirectSpy).not.toHaveBeenCalled()
  })

  it('falls back to uni.redirectTo when page stack depth reaches SAFE_PAGE_STACK_LIMIT', () => {
    uniGlobal.getCurrentPages = () => Array.from({ length: SAFE_PAGE_STACK_LIMIT }, () => ({}))
    const navSpy = vi.spyOn(uniGlobal.uni, 'navigateTo')
    const redirectSpy = vi.spyOn(uniGlobal.uni, 'redirectTo')

    safeNavigateTo('/subpackages/material/pages/questions/index?id=m-1')

    expect(redirectSpy).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/subpackages/material/pages/questions/index?id=m-1' }),
    )
    expect(navSpy).not.toHaveBeenCalled()
  })

  it('invokes custom fail callback or shows fallback toast when navigation fails', () => {
    uniGlobal.getCurrentPages = () => [{}]
    const customFail = vi.fn()
    const toastSpy = vi.spyOn(uniGlobal.uni, 'showToast')

    vi.spyOn(uniGlobal.uni, 'navigateTo').mockImplementationOnce((opts: any) => {
      opts.fail?.({ errMsg: 'navigateTo:fail' })
    })
    safeNavigateTo('/pages/auth/login', { fail: customFail })
    expect(customFail).toHaveBeenCalledTimes(1)
    expect(toastSpy).not.toHaveBeenCalled()

    vi.spyOn(uniGlobal.uni, 'navigateTo').mockImplementationOnce((opts: any) => {
      opts.fail?.({ errMsg: 'navigateTo:fail' })
    })
    safeNavigateTo('/pages/auth/login', { failMessage: '打开登录页失败' })
    expect(toastSpy).toHaveBeenCalledWith({ title: '打开登录页失败', icon: 'none' })
  })
})

describe('useMaterialUpload mp-weixin chooseMedia and privacy fail handling', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetLoadingGuardForTest()
  })

  afterEach(() => {
    delete uniGlobal.uni.showActionSheet
    delete uniGlobal.uni.chooseMedia
    delete uniGlobal.wx
    vi.restoreAllMocks()
  })

  it('redirects to login without opening picker when unauthenticated', () => {
    const navSpy = vi.spyOn(uniGlobal.uni, 'navigateTo')
    const toastSpy = vi.spyOn(uniGlobal.uni, 'showToast')
    uniGlobal.uni.chooseMedia = vi.fn()

    const { chooseFile } = useMaterialUpload({
      getCurrentFolderId: () => 'all',
      uploadMaterial: vi.fn(),
      onUploaded: vi.fn(),
    })

    chooseFile()
    expect(uniGlobal.uni.chooseMedia).not.toHaveBeenCalled()
    expect(navSpy).toHaveBeenCalledWith(expect.objectContaining({ url: '/pages/auth/login' }))
    expect(toastSpy).toHaveBeenCalledWith(expect.objectContaining({ title: '请先登录后再上传资料' }))
  })

  it('ignores user cancel errors and surfaces privacy/permission errors via safeShowToast', () => {
    useAuthStore().setToken('tok-upload')
    const toastSpy = vi.spyOn(uniGlobal.uni, 'showToast')
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    let failCb: ((err: unknown) => void) | null = null

    uniGlobal.uni.chooseMedia = vi.fn(({ fail }: any) => {
      failCb = fail
    })

    const { chooseFile } = useMaterialUpload({
      getCurrentFolderId: () => 'all',
      uploadMaterial: vi.fn(),
      onUploaded: vi.fn(),
    })

    chooseFile()
    expect(uniGlobal.uni.chooseMedia).toHaveBeenCalledWith(
      expect.objectContaining({
        count: 1,
        mediaType: ['image'],
      }),
    )

    failCb!({ errMsg: 'chooseMedia:fail cancel' })
    expect(toastSpy).not.toHaveBeenCalled()

    failCb!({ errno: 104, errMsg: 'chooseMedia:fail privacy permission is not authorized' })
    expect(toastSpy).toHaveBeenCalledWith({
      title: '请先同意隐私协议并开启相册/文件权限',
      icon: 'none',
    })
    expect(errSpy).toHaveBeenCalled()
  })
})
