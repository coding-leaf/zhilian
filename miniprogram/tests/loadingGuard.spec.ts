import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  isBlockingLoadingActive,
  resetLoadingGuardForTest,
  safeShowToast,
  withBlockingLoading,
} from '@/utils/loadingGuard'
import { request, uploadFile } from '@/utils/request'

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
