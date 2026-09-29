/**
 * 资料删除入口的契约测试（PRD `09-29-material-delete-entry`）。
 *
 * 覆盖：
 * - AC-2 走**软删除** `DELETE /materials/{id}`，断言**不是** `/{id}/hard`；
 * - AC-3 确认文案不含「回收站」（后端没有恢复接口，说了就是空头承诺），
 *   且写明「历史作答记录保留」+「无法在应用内恢复」；
 * - AC-4 失败可见且不吞错误；
 * - AC-5 取消确认时不发任何请求；
 * - AC-6 在途连点不会发第二次。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import {
  buildMaterialDeleteConfirmContent,
  useMaterialDelete,
} from '@/pages/index/composables/useMaterialDelete'
import { useMaterialStore } from '@/stores/material'
import type { MaterialItem } from '@/types'

function material(overrides: Partial<MaterialItem> = {}): MaterialItem {
  return {
    id: 'm-1',
    title: '计算机网络讲义',
    status: 'ready',
    ...overrides,
  } as MaterialItem
}

/** 取 showModal 收到的配置，并让调用方决定点确认还是取消。 */
function capturedModal(spy: any) {
  expect(spy).toHaveBeenCalledTimes(1)
  return spy.mock.calls[0][0]
}

const deleteCalls = () =>
  requestMock.mock.calls.filter(([o]: any[]) => o.method === 'DELETE')

describe('material delete API contract', () => {
  beforeEach(() => {
    requestMock.mockReset()
    setActivePinia(createPinia())
  })

  it('AC-2 走软删除 DELETE /materials/{id}，绝不能碰 /hard', async () => {
    requestMock.mockResolvedValue({ material_id: 'm-1', is_deleted: true, permanent: false, message: 'x' })
    const store = useMaterialStore()

    await store.deleteMaterial('m-1')

    expect(deleteCalls()).toHaveLength(1)
    expect(deleteCalls()[0][0].url).toBe('/materials/m-1')
    // 硬删除会级联销毁对象存储文件并影响历史数据引用，本任务刻意不做入口
    const urls = requestMock.mock.calls.map(([o]: any[]) => o.url)
    expect(urls.some((u: string) => u.endsWith('/hard'))).toBe(false)
  })

  it('成功后从列表移除；失败必须向上抛（不吞）', async () => {
    requestMock.mockResolvedValue({ material_id: 'm-1', is_deleted: true, permanent: false, message: 'x' })
    const store = useMaterialStore()
    store.materialList = [material(), material({ id: 'm-2', title: '线性代数' })]

    await store.deleteMaterial('m-1')
    expect(store.materialList.map((m) => m.id)).toEqual(['m-2'])

    requestMock.mockRejectedValue(new Error('boom'))
    await expect(store.deleteMaterial('m-2')).rejects.toThrow('boom')
    // 失败时不得把条目从列表里抹掉，否则「删除失败」与「已删除」长得一样
    expect(store.materialList.map((m) => m.id)).toEqual(['m-2'])
  })
})

describe('material delete interaction', () => {
  let modal: any
  let toast: any

  beforeEach(() => {
    setActivePinia(createPinia())
    modal = vi.spyOn(uni as any, 'showModal').mockImplementation(() => undefined as any)
    toast = vi.spyOn(uni as any, 'showToast').mockImplementation(() => undefined as any)
  })

  it('AC-3 确认文案不提「回收站」，且写明保留作答记录与无法在应用内恢复', () => {
    const content = buildMaterialDeleteConfirmContent('计算机网络讲义')

    // 后端没有恢复接口 —— 说「回收站」就是空头承诺
    expect(content).not.toContain('回收站')
    expect(content).toContain('无法在应用内恢复')
    expect(content).toContain('历史作答记录会保留')
    expect(content).toContain('计算机网络讲义')
  })

  it('AC-3 无标题资料也能给出可读文案', () => {
    const content = buildMaterialDeleteConfirmContent(null)
    expect(content).toContain('无标题资料')
    expect(content).not.toContain('回收站')
  })

  it('AC-5 取消确认时一个请求都不发', async () => {
    const del = vi.fn()
    const { requestDelete } = useMaterialDelete({ deleteMaterial: del })

    requestDelete({ id: 'm-1', title: '讲义' })
    await capturedModal(modal).success({ confirm: false })

    expect(del).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it('确认后调用删除并给出成功反馈', async () => {
    const del = vi.fn().mockResolvedValue(undefined)
    const { requestDelete, deletingId } = useMaterialDelete({ deleteMaterial: del })

    requestDelete({ id: 'm-1', title: '讲义' })
    await capturedModal(modal).success({ confirm: true })

    expect(del).toHaveBeenCalledWith('m-1')
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: '资料已删除' }))
    // 在途标志必须归零，否则后续删除会被连点守卫永久挡掉
    expect(deletingId.value).toBe('')
  })

  it('AC-4 失败可见且错误不被吞：给出失败提示，在途标志归零', async () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const del = vi.fn().mockRejectedValue(new Error('network down'))
    const { requestDelete, deletingId } = useMaterialDelete({ deleteMaterial: del })

    requestDelete({ id: 'm-1', title: '讲义' })
    await capturedModal(modal).success({ confirm: true })

    expect(err).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ icon: 'none' }))
    expect(deletingId.value).toBe('')
    err.mockRestore()
  })

  it('AC-6 在途连点不再弹第二个确认框，也不重复删除', async () => {
    let release: () => void = () => {}
    const del = vi.fn(() => new Promise<void>((resolve) => { release = resolve }))
    const { requestDelete } = useMaterialDelete({ deleteMaterial: del })

    requestDelete({ id: 'm-1', title: '讲义' })
    const first = capturedModal(modal).success({ confirm: true })
    // 第一次仍在途：此时再点不应打开新确认框
    requestDelete({ id: 'm-2', title: '线性代数' })
    expect(modal).toHaveBeenCalledTimes(1)

    release()
    await first
    expect(del).toHaveBeenCalledTimes(1)
  })
})
