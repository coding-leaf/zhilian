import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  MaterialItem,
  KnowledgePointDetail,
} from '@/types'
import {
  apiUploadMaterial,
  apiDeleteMaterial,
  apiGetMaterialDetail,
  apiGetMaterialList,
  apiTriggerMaterialParse,
  apiGetQuestionsByMaterial,
  apiGetKnowledgeTree,
  apiGetKnowledgePointDetail,
  apiGetKnowledgePointSnippets,
} from '@/api'
import { createPoller, type PollerHandle } from '@/utils/poller'

export const useMaterialStore = defineStore('material', () => {
  const currentMaterial = ref<MaterialItem | null>(null)
  const materialList = ref<MaterialItem[]>([])
  const isGenerating = ref<boolean>(false)
  const activeKnowledgePoint = ref<KnowledgePointDetail | null>(null)

  // 1. 上传资料并加入列表（支持关联课程文件夹）
  const upload = async (filePath: string, title?: string, folderId?: string): Promise<MaterialItem> => {
    const item = await apiUploadMaterial(filePath, title, folderId)
    currentMaterial.value = item
    materialList.value.unshift(item)
    return item
  }

  // 2. 手动触发资料解析流水线
  const triggerParse = async (materialId: string) => {
    return apiTriggerMaterialParse(materialId)
  }

  // 3. 单次拉取资料详情（不做终态判定，非终态也返回，供详情页直接渲染）
  const fetchMaterialDetail = async (id: string): Promise<MaterialItem> => {
    const item = await apiGetMaterialDetail(id)
    currentMaterial.value = item
    const idx = materialList.value.findIndex((m) => m.id === id)
    if (idx !== -1) {
      materialList.value[idx] = item
    }
    return item
  }

  // 4. 轮询资料解析状态（支持页面传入可取消 poller）
  const pollMaterialStatus = async (
    id: string,
    maxAttempts = 20,
    interval = 1500,
    poller: PollerHandle = createPoller(),
  ): Promise<MaterialItem> => {
    const result = await poller.run(() => fetchMaterialDetail(id), {
      maxAttempts,
      intervalMs: interval,
      isDone: (item) => ['ready', 'failed', 'retake_required'].includes(item.status),
    })
    if (result.status === 'completed') return result.value
    if (result.status === 'stopped') {
      if (result.lastValue) return result.lastValue
      throw new Error('资料轮询已取消')
    }
    throw new Error('资料解析超时，请稍后刷新')
  }

  // 5. 获取资料列表（支持课程筛选）
  const loadMaterialList = async (folderId?: string, status?: string) => {
    try {
      const list = await apiGetMaterialList({
        folder_id: folderId === 'all' ? undefined : folderId,
        status,
      })
      materialList.value = list
      return list
    } catch (err) {
      console.error('Failed to load materials', err)
      return []
    }
  }

  // 4.5 软删除资料：成功后就地从列表移除（后端保留历史作答记录）
  // 失败**必须向上抛**：吞掉错误会让「删除失败」与「已删除」在界面上一样，
  // 正是 spec 里点名禁止的「空态与故障态不可区分」。
  const deleteMaterial = async (id: string): Promise<void> => {
    await apiDeleteMaterial(id)
    materialList.value = materialList.value.filter((m) => m.id !== id)
    if (currentMaterial.value?.id === id) {
      currentMaterial.value = null
    }
  }

  // 5. 加载知识树
  const loadKnowledgeTree = async (materialId: string, versionId?: string) => {
    try {
      return await apiGetKnowledgeTree(materialId, versionId)
    } catch (err) {
      console.error('Failed to load knowledge tree', err)
      return null
    }
  }

  // 6. 加载知识点详情与切片溯源
  const loadKnowledgePointWithSnippets = async (pointId: string) => {
    try {
      const [detail, snippetsRes] = await Promise.all([
        apiGetKnowledgePointDetail(pointId),
        apiGetKnowledgePointSnippets(pointId),
      ])
      activeKnowledgePoint.value = detail
      return { detail, snippets: snippetsRes }
    } catch (err) {
      console.error('Failed to load knowledge point snippets', err)
      return null
    }
  }

  // 7. 获取题目
  const loadQuestions = async (materialId: string) => {
    return apiGetQuestionsByMaterial(materialId)
  }

  return {
    currentMaterial,
    materialList,
    isGenerating,
    activeKnowledgePoint,
    upload,
    triggerParse,
    fetchMaterialDetail,
    deleteMaterial,
    pollMaterialStatus,
    loadMaterialList,
    loadKnowledgeTree,
    loadKnowledgePointWithSnippets,
    loadQuestions,
  }
})
