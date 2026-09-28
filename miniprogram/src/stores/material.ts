import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { MaterialItem, QuestionItem } from '@/types'
import {
  apiUploadMaterial,
  apiGetMaterialDetail,
  apiGetMaterialList,
  apiGenerateQuestions,
  apiGetQuestionsByMaterial,
} from '@/api'

export const useMaterialStore = defineStore('material', () => {
  const currentMaterial = ref<MaterialItem | null>(null)
  const materialList = ref<MaterialItem[]>([])
  const questions = ref<QuestionItem[]>([])
  const isUploading = ref<boolean>(false)
  const isGenerating = ref<boolean>(false)

  // 1. 上传资料并加入列表
  const upload = async (filePath: string, title?: string): Promise<MaterialItem> => {
    isUploading.value = true
    try {
      const item = await apiUploadMaterial(filePath, title)
      currentMaterial.value = item
      materialList.value.unshift(item)
      return item
    } finally {
      isUploading.value = false
    }
  }

  // 2. 轮询资料解析状态
  const pollMaterialStatus = async (id: string, maxAttempts = 15, interval = 2000): Promise<MaterialItem> => {
    for (let i = 0; i < maxAttempts; i++) {
      const item = await apiGetMaterialDetail(id)
      currentMaterial.value = item
      if (item.status === 'PARSED' || item.status === 'FAILED') {
        return item
      }
      await new Promise((r) => setTimeout(r, interval))
    }
    throw new Error('资料解析超时，请稍后刷新')
  }

  // 3. 获取资料列表
  const loadMaterialList = async () => {
    try {
      const list = await apiGetMaterialList()
      materialList.value = list
    } catch (err) {
      console.error('Failed to load materials', err)
    }
  }

  // 4. 触发智能出题
  const generateQuestions = async (materialId: string, count = 5) => {
    isGenerating.value = true
    try {
      await apiGenerateQuestions({ material_id: materialId, count })
      // 成功后拉取题目列表
      questions.value = await apiGetQuestionsByMaterial(materialId)
      return questions.value
    } finally {
      isGenerating.value = false
    }
  }

  // 5. 获取题目
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
    upload,
    pollMaterialStatus,
    loadMaterialList,
    generateQuestions,
    loadQuestions,
  }
})
