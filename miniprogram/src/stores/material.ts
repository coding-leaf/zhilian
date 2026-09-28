import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  MaterialItem,
  QuestionItem,
  KnowledgeTreeResult,
  KnowledgePointDetail,
  PointSourceListResult,
} from '@/types'
import {
  apiUploadMaterial,
  apiGetMaterialDetail,
  apiGetMaterialList,
  apiTriggerMaterialParse,
  apiGenerateQuestions,
  apiGetQuestionsByMaterial,
  apiGetKnowledgeTree,
  apiGetKnowledgePointDetail,
  apiGetKnowledgePointSnippets,
  type GenerateQuestionsParams,
} from '@/api'

export const useMaterialStore = defineStore('material', () => {
  const currentMaterial = ref<MaterialItem | null>(null)
  const materialList = ref<MaterialItem[]>([])
  const questions = ref<QuestionItem[]>([])
  const isUploading = ref<boolean>(false)
  const isGenerating = ref<boolean>(false)
  const currentKnowledgeTree = ref<KnowledgeTreeResult | null>(null)
  const activeKnowledgePoint = ref<KnowledgePointDetail | null>(null)
  const activeSnippets = ref<PointSourceListResult | null>(null)

  // 1. 上传资料并加入列表（支持关联课程文件夹）
  const upload = async (filePath: string, title?: string, folderId?: string): Promise<MaterialItem> => {
    isUploading.value = true
    try {
      const item = await apiUploadMaterial(filePath, title, folderId)
      currentMaterial.value = item
      materialList.value.unshift(item)
      return item
    } finally {
      isUploading.value = false
    }
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

  // 4. 轮询资料解析状态
  const pollMaterialStatus = async (id: string, maxAttempts = 20, interval = 1500): Promise<MaterialItem> => {
    for (let i = 0; i < maxAttempts; i++) {
      const item = await fetchMaterialDetail(id)
      if (['ready', 'failed', 'retake_required'].includes(item.status)) {
        return item
      }
      await new Promise((r) => setTimeout(r, interval))
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

  // 5. 加载知识树
  const loadKnowledgeTree = async (materialId: string, versionId?: string) => {
    try {
      const tree = await apiGetKnowledgeTree(materialId, versionId)
      currentKnowledgeTree.value = tree
      return tree
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
      activeSnippets.value = snippetsRes
      return { detail, snippets: snippetsRes }
    } catch (err) {
      console.error('Failed to load knowledge point snippets', err)
      return null
    }
  }

  // 7. 触发智能出题（扩展支持多知识点与多题型）
  const generateQuestions = async (params: GenerateQuestionsParams | string, count = 5) => {
    isGenerating.value = true
    try {
      const req: GenerateQuestionsParams = typeof params === 'string'
        ? { material_id: params, count }
        : params

      const res = await apiGenerateQuestions(req)
      if (res && res.qualified_questions && res.qualified_questions.length > 0) {
        questions.value = res.qualified_questions
      } else if (req.material_id) {
        // 兜底拉取题目
        questions.value = await apiGetQuestionsByMaterial(req.material_id)
      }
      return questions.value
    } finally {
      isGenerating.value = false
    }
  }

  // 8. 获取题目
  const loadQuestions = async (materialId: string) => {
    questions.value = await apiGetQuestionsByMaterial(materialId)
    return questions.value
  }

  return {
    currentMaterial,
    materialList,
    questions,
    isUploading,
    isGenerating,
    currentKnowledgeTree,
    activeKnowledgePoint,
    activeSnippets,
    upload,
    triggerParse,
    fetchMaterialDetail,
    pollMaterialStatus,
    loadMaterialList,
    loadKnowledgeTree,
    loadKnowledgePointWithSnippets,
    generateQuestions,
    loadQuestions,
  }
})
