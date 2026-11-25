import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { requestMock, uploadFileMock } = vi.hoisted(() => ({
  requestMock: vi.fn(),
  uploadFileMock: vi.fn(),
}))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: (...args: any[]) => uploadFileMock(...args),
}))

import { useFolderStore } from '@/stores/folder'
import { useMaterialStore } from '@/stores/material'
import type { PollerHandle } from '@/utils/poller'

describe('useMaterialStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
    uploadFileMock.mockReset()
  })

  it('uploads a material, normalizes its status, and prepends it to materialList', async () => {
    uploadFileMock.mockResolvedValueOnce({
      id: 'm-1',
      title: '数据结构',
      status: 'PENDING',
      created_at: '2026-11-17T08:00:00',
    })
    const store = useMaterialStore()

    const item = await store.upload('/tmp/ds.pdf', '数据结构', 'f-1')

    expect(uploadFileMock).toHaveBeenCalledWith('/tmp/ds.pdf', 'file', {
      title: '数据结构',
      folder_id: 'f-1',
    })
    expect(item.status).toBe('pending')
    expect(store.currentMaterial?.id).toBe('m-1')
    expect(store.materialList.map((m) => m.id)).toEqual(['m-1'])
  })

  it('triggers parse, fetches detail into list, and loads questions', async () => {
    requestMock.mockImplementation(async ({ url, method }: { url: string; method?: string }) => {
      if (url === '/materials/m-1/parse' && method === 'POST') return { message: 'queued' }
      if (url === '/materials/m-1') {
        return { id: 'm-1', title: '操作系统', status: 'READY', created_at: '2026-11-17' }
      }
      if (url === '/materials/m-new') {
        return { id: 'm-new', title: '新讲义', status: 'parsing', created_at: '2026-11-17' }
      }
      if (url === '/questions?material_id=m-1') {
        return {
          items: [
            { id: 'q-1', question_type: 'single_choice', stem: '题干' },
          ],
        }
      }
      throw new Error(`unexpected: ${url}`)
    })
    const store = useMaterialStore()
    store.materialList = [{ id: 'm-1', title: '操作系统', status: 'parsing', created_at: '2026-11-17' }]

    await expect(store.triggerParse('m-1')).resolves.toEqual({ message: 'queued' })

    const updated = await store.fetchMaterialDetail('m-1')
    expect(updated.status).toBe('ready')
    expect(store.materialList[0].status).toBe('ready')

    const nonListed = await store.fetchMaterialDetail('m-new')
    expect(nonListed.id).toBe('m-new')
    expect(store.materialList).toHaveLength(1)

    const questions = await store.loadQuestions('m-1')
    expect(questions).toHaveLength(1)
    expect(questions[0].type).toBe('single_choice')
  })

  it('loads material list with folder/status filters and returns [] on error', async () => {
    requestMock.mockResolvedValueOnce({
      items: [{ id: 'm-1', title: '讲义', status: 'ready' }],
    })
    const store = useMaterialStore()

    const list = await store.loadMaterialList('all', 'ready')
    expect(requestMock).toHaveBeenCalledWith({ url: '/materials?status=ready', method: 'GET' })
    expect(list).toHaveLength(1)

    requestMock.mockResolvedValueOnce([{ id: 'm-2', title: '讲义2', status: 'pending' }])
    await store.loadMaterialList('f-2')
    expect(requestMock).toHaveBeenLastCalledWith({ url: '/materials?folder_id=f-2', method: 'GET' })

    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    requestMock.mockRejectedValueOnce(new Error('network'))
    expect(await store.loadMaterialList()).toEqual([])
    expect(errSpy).toHaveBeenCalled()
    errSpy.mockRestore()
  })

  it('handles pollMaterialStatus completion, cancellation, and timeout', async () => {
    requestMock
      .mockResolvedValueOnce({ id: 'm-1', title: 'A', status: 'parsing' })
      .mockResolvedValueOnce({ id: 'm-1', title: 'A', status: 'ready' })
    const store = useMaterialStore()

    const ready = await store.pollMaterialStatus('m-1', 5, 0)
    expect(ready.status).toBe('ready')

    const stoppedWithLast: PollerHandle = {
      isDisposed: true,
      stop: vi.fn(),
      dispose: vi.fn(),
      run: vi.fn().mockResolvedValue({
        status: 'stopped',
        lastValue: { id: 'm-1', title: 'A', status: 'parsing', created_at: '2026-11-17' },
      }),
    }
    await expect(store.pollMaterialStatus('m-1', 5, 0, stoppedWithLast)).resolves.toMatchObject({
      status: 'parsing',
    })

    const stoppedEmpty: PollerHandle = {
      isDisposed: true,
      stop: vi.fn(),
      dispose: vi.fn(),
      run: vi.fn().mockResolvedValue({ status: 'stopped', lastValue: undefined }),
    }
    await expect(store.pollMaterialStatus('m-1', 5, 0, stoppedEmpty)).rejects.toThrow('资料轮询已取消')

    requestMock.mockResolvedValue({ id: 'm-1', title: 'A', status: 'parsing' })
    await expect(store.pollMaterialStatus('m-1', 2, 0)).rejects.toThrow('资料解析超时，请稍后刷新')
  })

  it('loads knowledge tree and snippets and returns null on failure', async () => {
    requestMock.mockImplementation(async ({ url }: { url: string }) => {
      if (url === '/materials/m-1/knowledge-tree?version_id=v-2') {
        return { material_id: 'm-1', version_id: 'v-2', nodes: [] }
      }
      if (url === '/knowledge/kp-1') {
        return { id: 'kp-1', name: '调度', level: 1, children: [] }
      }
      if (url === '/knowledge/kp-1/snippets') {
        return {
          knowledge_point_id: 'kp-1',
          snippets: [{ id: 's-1', page_index: 2, chapter_title: '第二章', content: '原文' }],
        }
      }
      throw new Error(`unexpected: ${url}`)
    })
    const store = useMaterialStore()

    const tree = await store.loadKnowledgeTree('m-1', 'v-2')
    expect(tree?.version_id).toBe('v-2')

    const kpRes = await store.loadKnowledgePointWithSnippets('kp-1')
    expect(kpRes?.detail.id).toBe('kp-1')
    expect(kpRes?.snippets.snippets[0].page_index).toBe(2)
    expect(store.activeKnowledgePoint?.id).toBe('kp-1')

    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    requestMock.mockRejectedValue(new Error('fail'))
    expect(await store.loadKnowledgeTree('m-1')).toBeNull()
    expect(await store.loadKnowledgePointWithSnippets('kp-1')).toBeNull()
    errSpy.mockRestore()
  })
})

describe('useFolderStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
  })

  it('loads folders and returns [] on error', async () => {
    requestMock.mockResolvedValueOnce({
      items: [{ id: 'f-1', name: '高数', ready_material_count: 1, knowledge_point_count: 5 }],
    })
    const store = useFolderStore()

    const loaded = await store.loadFolders(true)
    expect(requestMock).toHaveBeenCalledWith({ url: '/folders?include_archived=true', method: 'GET' })
    expect(loaded).toHaveLength(1)

    requestMock.mockResolvedValueOnce({})
    expect(await store.loadFolders()).toEqual([])

    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    requestMock.mockRejectedValueOnce(new Error('network'))
    expect(await store.loadFolders()).toEqual([])
    expect(errSpy).toHaveBeenCalled()
    errSpy.mockRestore()
  })

  it('creates, renames, archives folders, and loads folder knowledge points', async () => {
    requestMock.mockImplementation(async ({ url, method, data }: { url: string; method?: string; data?: any }) => {
      if (url === '/folders' && method === 'POST') {
        return { id: 'f-1', name: data.name, ready_material_count: 0, knowledge_point_count: 0 }
      }
      if (url === '/folders/f-1' && method === 'PUT') {
        return { id: 'f-1', name: data.name, ready_material_count: 0, knowledge_point_count: 0 }
      }
      if (url === '/folders/f-missing' && method === 'PUT') {
        return { id: 'f-missing', name: data.name, ready_material_count: 0, knowledge_point_count: 0 }
      }
      if (url.startsWith('/folders/') && method === 'DELETE') {
        return { id: 'f-1', is_deleted: true }
      }
      if (url === '/folders/f-2/knowledge-points') {
        return { folder_id: 'f-2', groups: [] }
      }
      throw new Error(`unexpected: ${url}`)
    })
    const store = useFolderStore()
    store.folders = [
      {
        id: 'f-2',
        name: '线代',
        sort_order: 0,
        is_archived: false,
        material_count: 2,
        ready_material_count: 2,
        knowledge_point_count: 4,
        question_count: 10,
        created_at: '2026-11-17',
        updated_at: '2026-11-17',
      },
    ]

    const created = await store.createFolder('离散数学')
    expect(created.id).toBe('f-1')
    expect(store.currentFolderId).toBe('f-1')
    expect(store.folders.map((f) => f.id)).toEqual(['f-1', 'f-2'])

    await store.renameFolder('f-1', '离散数学进阶')
    expect(store.folders[0].name).toBe('离散数学进阶')
    await store.renameFolder('f-missing', '不存在')
    expect(store.folders).toHaveLength(2)

    await store.archiveFolder('f-2')
    expect(store.folders.map((f) => f.id)).toEqual(['f-1'])
    expect(store.currentFolderId).toBe('f-1')

    await store.archiveFolder('f-1')
    expect(store.folders).toEqual([])
    expect(store.currentFolderId).toBe('all')

    const kpRes = await store.loadFolderKnowledgePoints('f-2')
    expect(kpRes).toEqual({ folder_id: 'f-2', groups: [] })
  })
})
