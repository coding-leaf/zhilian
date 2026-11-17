import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ProfilePage from '@/pages/profile/index.vue'
import { useAuthStore } from '@/stores/auth'
import type { FolderItem, FolderListResult, MaterialStatistics } from '@/types'

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  show: [] as Array<() => Promise<void>>,
  pull: [] as Array<() => Promise<void>>,
}))

vi.mock('@/utils/request', () => ({ request: mocks.request, uploadFile: vi.fn() }))
vi.mock('@dcloudio/uni-app', () => ({
  onShow: (callback: () => Promise<void>) => mocks.show.push(callback),
  onPullDownRefresh: (callback: () => Promise<void>) => mocks.pull.push(callback),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function folder(id: string): FolderItem {
  return {
    id, name: id, sort_order: 0, is_archived: false,
    material_count: 1, ready_material_count: 1, knowledge_point_count: 2,
    question_count: 0, created_at: '2026-10-04', updated_at: '2026-10-04',
  }
}

let folders: FolderListResult
let statistics: MaterialStatistics
let wrapper: VueWrapper | undefined
let stopPullDownRefresh: ReturnType<typeof vi.fn>

function mountPage(loggedIn = true): VueWrapper {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  if (loggedIn) {
    auth.setToken('account-a')
    auth.user = { id: 'user-a', nickname: '测试学员' }
  }
  wrapper = mount(ProfilePage, {
    global: { plugins: [pinia] },
  })
  return wrapper
}

function numbers(): string[] {
  return wrapper!.findAll('.grid-num').map(node => node.text())
}

beforeEach(() => {
  uni.clearStorageSync()
  mocks.request.mockReset()
  mocks.show.length = 0
  mocks.pull.length = 0
  stopPullDownRefresh = vi.fn()
  Object.assign(uni, { stopPullDownRefresh })
  folders = { items: [folder('course-1')], total: 1 }
  statistics = { ready_material_count: 4, knowledge_point_count: 51 }
  mocks.request.mockImplementation(async ({ url }: { url: string }) => {
    if (url === '/folders?include_archived=false') return folders
    if (url === '/materials/statistics') return statistics
    throw new Error(`Unexpected request: ${url}`)
  })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
})

describe('个人页学习足迹', () => {
  it('等待全组结果才显示数字，资料数不再是课程聚合字段之和', async () => {
    const pending = deferred<MaterialStatistics>()
    mocks.request.mockImplementation(async ({ url }: { url: string }) =>
      url === '/materials/statistics' ? pending.promise : folders)
    mountPage()
    expect(wrapper!.text()).toContain('正在加载学习足迹')
    expect(numbers()).toEqual([])

    const load = mocks.show[0]()
    await flushPromises()
    expect(numbers()).toEqual([])
    pending.resolve(statistics)
    await load
    await nextTick()

    expect(numbers()).toEqual(['1', '4', '51'])
    expect(wrapper!.text()).toContain('归档课程的就绪资料')
    expect(mocks.request).toHaveBeenCalledWith({ url: '/materials/statistics', method: 'GET' })
  })

  it('课程数沿用未归档列表长度，不改为 total 或资料总数', async () => {
    folders = { items: [folder('one'), folder('two')], total: 99 }
    mountPage()
    await mocks.show[0]()
    await nextTick()
    expect(numbers()).toEqual(['2', '4', '51'])
  })

  it('成功的空数据真实显示三个零，不显示加载失败', async () => {
    folders = { items: [], total: 0 }
    statistics = { ready_material_count: 0, knowledge_point_count: 0 }
    mountPage()
    await mocks.show[0]()
    await nextTick()
    expect(numbers()).toEqual(['0', '0', '0'])
    expect(wrapper!.text()).not.toContain('加载失败')
    expect(wrapper!.find('.retry-btn').exists()).toBe(false)
  })

  it.each(['/folders?include_archived=false', '/materials/statistics'])(
    '%s 失败显示可见提示，点重试后恢复', async failedUrl => {
      let failed = true
      mocks.request.mockImplementation(async ({ url }: { url: string }) => {
        if (url === failedUrl && failed) throw new Error('network unavailable')
        return url === '/materials/statistics' ? statistics : folders
      })
      mountPage()
      await mocks.show[0]()
      await nextTick()
      expect(wrapper!.text()).toContain('加载失败，可下拉重试')
      expect(numbers()).toEqual([])

      failed = false
      await wrapper!.get('.retry-btn').trigger('tap')
      await flushPromises()
      expect(numbers()).toEqual(['1', '4', '51'])
      expect(wrapper!.text()).not.toContain('加载失败')
    },
  )

  it('每次 onShow 重取，刷新失败后隐藏旧值且能再次成功', async () => {
    mountPage()
    await mocks.show[0]()
    mocks.request.mockRejectedValueOnce(new Error('refresh failed'))
    await mocks.show[0]()
    await nextTick()
    expect(numbers()).toEqual([])
    expect(wrapper!.text()).toContain('加载失败')

    statistics = { ready_material_count: 5, knowledge_point_count: 60 }
    await mocks.show[0]()
    await nextTick()
    expect(numbers()).toEqual(['1', '5', '60'])
  })

  it.each([false, true])('下拉刷新（失败=%s）总会停止刷新动画', async failed => {
    mountPage()
    if (failed) mocks.request.mockRejectedValueOnce(new Error('refresh failed'))
    await mocks.pull[0]()
    await nextTick()
    expect(stopPullDownRefresh).toHaveBeenCalledOnce()
    expect(numbers()).toEqual(failed ? [] : ['1', '4', '51'])
    if (failed) expect(wrapper!.text()).toContain('加载失败，可下拉重试')
  })

  it('同一账号同时 onShow 与下拉刷新合并在途请求', async () => {
    const pending = deferred<MaterialStatistics>()
    mocks.request.mockImplementation(async ({ url }: { url: string }) =>
      url === '/materials/statistics' ? pending.promise : folders)
    mountPage()
    const show = mocks.show[0]()
    const pull = mocks.pull[0]()
    await flushPromises()
    expect(mocks.request).toHaveBeenCalledTimes(2)
    expect(stopPullDownRefresh).not.toHaveBeenCalled()
    pending.resolve(statistics)
    await Promise.all([show, pull])
    await nextTick()
    expect(numbers()).toEqual(['1', '4', '51'])
    expect(stopPullDownRefresh).toHaveBeenCalledOnce()
  })

  it('未登录只显示登录提示，两个刷新入口都不请求统计', async () => {
    mountPage(false)
    await mocks.show[0]()
    await mocks.pull[0]()
    expect(wrapper!.text()).toContain('登录后查看学习足迹')
    expect(numbers()).toEqual([])
    expect(mocks.request).not.toHaveBeenCalled()
    expect(stopPullDownRefresh).toHaveBeenCalledOnce()
  })

  it('请求期间退出，旧响应不得恢复旧账号数字', async () => {
    const pending = deferred<MaterialStatistics>()
    mocks.request.mockImplementation(async ({ url }: { url: string }) =>
      url === '/materials/statistics' ? pending.promise : folders)
    mountPage()
    const load = mocks.show[0]()
    await flushPromises()
    useAuthStore().clearAuth()
    await nextTick()
    expect(wrapper!.text()).toContain('登录后查看学习足迹')

    pending.resolve(statistics)
    await load
    await nextTick()
    expect(numbers()).toEqual([])
    expect(wrapper!.text()).toContain('登录后查看学习足迹')
  })

  it.each(['resolve', 'reject'] as const)(
    '账号切换后旧请求 %s 不覆盖新账号结果', async result => {
      const pending = deferred<MaterialStatistics>()
      mocks.request.mockImplementation(async ({ url }: { url: string }) => {
        if (url !== '/materials/statistics') return folders
        return useAuthStore().token === 'account-a' ? pending.promise : statistics
      })
      mountPage()
      const oldLoad = mocks.show[0]()
      await flushPromises()
      statistics = { ready_material_count: 2, knowledge_point_count: 7 }
      folders = { items: [], total: 0 }
      useAuthStore().setToken('account-b')
      await flushPromises()
      expect(numbers()).toEqual(['0', '2', '7'])

      if (result === 'resolve') pending.resolve({ ready_material_count: 99, knowledge_point_count: 999 })
      else pending.reject(new Error('old account request failed'))
      await oldLoad
      await nextTick()
      expect(numbers()).toEqual(['0', '2', '7'])
      expect(wrapper!.text()).not.toContain('加载失败')
    },
  )

  it('课程请求期间切换账号，旧课程列表不会触发新账号的第二次统计查询', async () => {
    const pending = deferred<FolderListResult>()
    mocks.request.mockImplementation(async ({ url }: { url: string }) => {
      if (url === '/materials/statistics') return statistics
      return useAuthStore().token === 'account-a' ? pending.promise : folders
    })
    mountPage()
    const oldLoad = mocks.show[0]()
    useAuthStore().setToken('account-b')
    await flushPromises()
    pending.resolve({ items: [], total: 0 })
    await oldLoad
    await nextTick()
    expect(numbers()).toEqual(['1', '4', '51'])
    expect(mocks.request.mock.calls.filter(([options]) => options.url === '/materials/statistics'))
      .toHaveLength(1)
  })
})
