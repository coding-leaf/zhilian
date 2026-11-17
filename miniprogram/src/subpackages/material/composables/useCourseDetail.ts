import { computed, ref } from 'vue'
import { useMaterialStore } from '@/stores/material'
import { flattenKnowledgeTree } from '@/utils/knowledgeTree'
import { canStartMaterialParse, isMaterialParsing } from '@/utils/materialState'
import { createPoller } from '@/utils/poller'
import type { KnowledgeSnippet, KnowledgeTreeNode, MaterialItem } from '@/types'

/** 资料详情、知识树展开、轮询同步与考点切片加载编排。 */
export function useCourseDetail() {
  const materialStore = useMaterialStore()
  const parsePoller = createPoller()

  const materialId = ref('')
  const material = ref<MaterialItem | null>(null)
  const knowledgeNodes = ref<KnowledgeTreeNode[]>([])
  const generatedQuestionCount = ref(0)

  const showPointModal = ref(false)
  const selectedPoint = ref<KnowledgeTreeNode | null>(null)
  const pointSnippets = ref<KnowledgeSnippet[]>([])
  const isLoadingSnippets = ref(false)
  const snippetLoadFailed = ref(false)

  const selectedPointDetail = computed(() => materialStore.activeKnowledgePoint)
  const canStartParse = computed(() => canStartMaterialParse(material.value))
  const isParsing = computed(() => isMaterialParsing(material.value))

  const parseProgressText = computed(() => {
    const progress = material.value?.progress_percentage
    return typeof progress === 'number'
      ? `正在提取知识点与原文切片，已完成 ${Math.round(progress)}%...`
      : '智能解析中，正在提取关键知识点与切片...'
  })

  const pointHierarchy = computed(() => {
    const point = selectedPointDetail.value
    if (!point) return ''
    const names = [point.name]
    let parentId = point.parent_id
    while (parentId) {
      const parent = knowledgeNodes.value.find((node) => node.id === parentId)
      if (!parent) break
      names.unshift(parent.name)
      parentId = parent.parent_id
    }
    return names.join(' / ')
  })

  const loadGeneratedQuestionCount = async () => {
    if (!materialId.value) return
    try {
      const list = await materialStore.loadQuestions(materialId.value)
      generatedQuestionCount.value = list.length
    } catch (err) {
      console.error(err)
    }
  }

  const loadReadyAssets = async () => {
    const tree = await materialStore.loadKnowledgeTree(materialId.value)
    if (tree?.nodes) {
      knowledgeNodes.value = flattenKnowledgeTree(tree.nodes)
    }
    await loadGeneratedQuestionCount()
  }

  const loadDetail = async () => {
    if (!materialId.value) return
    try {
      material.value = await materialStore.fetchMaterialDetail(materialId.value)
      if (material.value.status === 'ready') {
        await loadReadyAssets()
      }
    } catch (err) {
      console.error(err)
    }
  }

  const syncParseProgress = async () => {
    if (!materialId.value) return
    try {
      material.value = await materialStore.pollMaterialStatus(
        materialId.value,
        20,
        1500,
        parsePoller,
      )
    } catch {
      material.value = materialStore.currentMaterial
    }
    if (material.value?.status === 'ready') {
      await loadReadyAssets()
    }
  }

  const initCourse = async (id: string) => {
    materialId.value = id
    await loadDetail()
    if (material.value && isMaterialParsing(material.value)) {
      await syncParseProgress()
    }
  }

  const startParse = async () => {
    if (!materialId.value) return
    uni.showLoading({ title: '启动流水线...' })
    try {
      await materialStore.triggerParse(materialId.value)
      uni.hideLoading()
      uni.showToast({ title: '开始解析', icon: 'success' })
      await syncParseProgress()
    } catch (err: any) {
      uni.hideLoading()
      uni.showToast({ title: err?.message || '解析启动失败', icon: 'none' })
    }
  }

  const openPointDetail = async (node: KnowledgeTreeNode) => {
    selectedPoint.value = node
    showPointModal.value = true
    pointSnippets.value = []
    snippetLoadFailed.value = false
    isLoadingSnippets.value = true
    try {
      const res = await materialStore.loadKnowledgePointWithSnippets(node.id)
      if (res?.snippets) pointSnippets.value = res.snippets.snippets || []
      else snippetLoadFailed.value = true
    } catch {
      snippetLoadFailed.value = true
    } finally {
      isLoadingSnippets.value = false
    }
  }

  const dispose = () => {
    parsePoller.dispose()
  }

  return {
    materialId,
    material,
    knowledgeNodes,
    generatedQuestionCount,
    showPointModal,
    selectedPoint,
    selectedPointDetail,
    pointHierarchy,
    pointSnippets,
    isLoadingSnippets,
    snippetLoadFailed,
    canStartParse,
    isParsing,
    parseProgressText,
    initCourse,
    loadDetail,
    startParse,
    openPointDetail,
    dispose,
  }
}
