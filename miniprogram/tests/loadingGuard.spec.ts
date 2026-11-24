import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  extractUserErrorMessage,
  isBlockingLoadingActive,
  resetLoadingGuardForTest,
  safeShowToast,
  withBlockingLoading,
} from '@/utils/loadingGuard'
import { request, uploadFile } from '@/utils/request'
import { RequestError } from '@/utils/requestError'

const uniGlobal = globalThis as any

describe('loadingGuard ref-counted blocking loading', () => {
  let events: string[] = []

  beforeEach(() => {
    resetLoadingGuardForTest()
    events = []
    vi.spyOn(uniGlobal.uni, 'showLoading').mockImplementation(() => {
      events.push('showLoading')
    })
    vi.spyOn(uniGlobal.uni, 'hideLoading').mockImplementation(() => {
      events.push('hideLoading')
    })
    vi.spyOn(uniGlobal.uni, 'showToast').mockImplementation((opts: any) => {
      events.push(`showToast:${opts.title}`)
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    resetLoadingGuardForTest()
  })

  it('pairs showLoading and hideLoading 1:1 on single, nested, and concurrent calls', async () => {
    let resolveA!: (v: string) => void
    let resolveB!: (v: string) => void

    const pA = withBlockingLoading('加载 A...', () => new Promise<string>((r) => { resolveA = r }))
    const pB = withBlockingLoading('加载 B...', () => new Promise<string>((r) => { resolveB = r }))

    expect(isBlockingLoadingActive()).toBe(true)
    expect(events).toEqual(['showLoading'])

    resolveA('okA')
    expect(await pA).toBe('okA')
    expect(isBlockingLoadingActive()).toBe(true)
    expect(events).toEqual(['showLoading'])

    resolveB('okB')
    expect(await pB).toBe('okB')
    expect(isBlockingLoadingActive()).toBe(false)
    expect(events).toEqual(['showLoading', 'hideLoading'])
  })

  it('hides loading BEFORE rethrowing so caller toast never collides', async () => {
    await expect(
      withBlockingLoading('提交中...', async () => {
        throw new Error('submit failed')
      }),
    ).rejects.toThrow('submit failed')

    expect(isBlockingLoadingActive()).toBe(false)
    safeShowToast('提交失败')
    expect(events).toEqual(['showLoading', 'hideLoading', 'showToast:提交失败'])
  })

  it('auto-downgrades icon to none when toast title exceeds 7 characters and preserves icon otherwise', () => {
    const toastSpy = vi.spyOn(uniGlobal.uni, 'showToast')

    safeShowToast('上传成功，已开始后台解析', 'success')
    expect(toastSpy).toHaveBeenLastCalledWith({
      title: '上传成功，已开始后台解析',
      icon: 'none',
    })

    safeShowToast({ title: '头像已更新', icon: 'success', duration: 2000, mask: true })
    expect(toastSpy).toHaveBeenLastCalledWith({
      title: '头像已更新',
      icon: 'success',
      duration: 2000,
      mask: true,
    })

    safeShowToast({ title: '试卷已就绪（10 题）', icon: 'success' })
    expect(toastSpy).toHaveBeenLastCalledWith({
      title: '试卷已就绪（10 题）',
      icon: 'none',
    })
  })

  it('extractUserErrorMessage prefers RequestError.userMessage and strips leaked URLs', () => {
    const reqErr = new RequestError(
      'http',
      'http://127.0.0.1:8000/api/v1/folders/1',
      'PUT',
      '课程名称已存在',
      { statusCode: 409 },
    )
    expect(reqErr.message).toContain('http://127.0.0.1:8000')
    expect(extractUserErrorMessage(reqErr, '保存失败')).toBe('课程名称已存在')

    expect(
      extractUserErrorMessage(
        new Error('网络错误 [POST http://127.0.0.1:8000/api/v1/users/me]'),
        '保存失败',
      ),
    ).toBe('网络错误')
    expect(extractUserErrorMessage(new Error('http://127.0.0.1:8000/x'), '保存失败')).toBe('保存失败')
    expect(extractUserErrorMessage(null, '兜底提示')).toBe('兜底提示')
  })
})

describe('request silentToast integration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    uni.clearStorageSync()
    resetLoadingGuardForTest()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    resetLoadingGuardForTest()
  })

  it('suppresses uni.showToast when silentToast is true on HTTP and fail paths', async () => {
    const toastSpy = vi.spyOn(uniGlobal.uni, 'showToast')
    const hideSpy = vi.spyOn(uniGlobal.uni, 'hideLoading')
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    uniGlobal.uni.request = (opts: any) => opts.success({ statusCode: 500, data: { detail: 'server error' } })

    await expect(
      withBlockingLoading('处理中...', () =>
        request({ url: '/materials/m-1/parse', method: 'POST', silentToast: true }),
      ),
    ).rejects.toThrow('server error')

    expect(toastSpy).not.toHaveBeenCalled()
    expect(hideSpy).toHaveBeenCalledTimes(1)
    expect(errSpy).toHaveBeenCalled()

    uniGlobal.uni.uploadFile = (opts: any) => opts.fail({ errMsg: 'uploadFile:fail timeout' })
    await expect(
      uploadFile('/tmp/a.pdf', 'file', undefined, '/materials/upload', { silentToast: true }),
    ).rejects.toThrow('超时')
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('dismisses active blocking loading before showing transport toast when silentToast is not set', async () => {
    const order: string[] = []
    vi.spyOn(uniGlobal.uni, 'showLoading').mockImplementation(() => order.push('showLoading'))
    vi.spyOn(uniGlobal.uni, 'hideLoading').mockImplementation(() => order.push('hideLoading'))
    vi.spyOn(uniGlobal.uni, 'showToast').mockImplementation(() => order.push('showToast'))
    vi.spyOn(console, 'error').mockImplementation(() => undefined)

    uniGlobal.uni.request = (opts: any) => opts.fail({ errMsg: 'request:fail timeout' })

    await expect(
      withBlockingLoading('加载中...', () => request({ url: '/slow' })),
    ).rejects.toThrow('超时')

    expect(order).toEqual(['showLoading', 'hideLoading', 'showToast'])
  })
})
