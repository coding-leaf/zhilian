import { computed, ref, watch } from 'vue'
import { apiGetMasteryOverview, apiGetStudyGuidesStatus } from '@/api'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { useMaterialStore } from '@/stores/material'
import { safeShowToast, withBlockingLoading } from '@/utils/loadingGuard'
import { canStartMaterialParse, isMaterialParsing } from '@/utils/materialState'
import { describeFailure, RequestError } from '@/utils/requestError'
import type {
  KnowledgeSnippet,
  KnowledgeTreeNode,
  MaterialItem,
  StudyGuidePrewarmStatusResult,
} from '@/types'
import { buildMasteryMap, flattenTreeWithParents, type MasteryEntry } from '../utils/courseStudy'

/** 资料详情、知识树展开、掌握度映射、重新解析同步与考点切片加载编排。 */
export function useCourseDetail() {
  const materialStore = useMaterialStore()
  const taskStore = useBackgroundTaskStore()

  const materialId = ref('')
  const material = ref<MaterialItem | null>(null)
  const knowledgeNodes = ref<KnowledgeTreeNode[]>([])
  const generatedQuestionCount = ref(0)
  const masteryMap = ref<Record<string, MasteryEntry>>({})

  const showPointModal = ref(false)
  const selectedPoint = ref<KnowledgeTreeNode | null>(null)
  const pointSnippets = ref<KnowledgeSnippet[]>([])
  const isLoading = ref(false)
  const isRefreshing = ref(false)
  const isLoadingSnippets = ref(false)
  const snippetLoadFailed = ref(false)
  const prewarmStatus = ref<StudyGuidePrewarmStatusResult | null>(null)
  const isStartingPrewarm = ref(false)

  const selectedPointDetail = computed(() => materialStore.activeKnowledgePoint)
  const canStartParse = computed(() => canStartMaterialParse(material.value))
  const isParsing = computed(() => isMaterialParsing(material.value))
  const isParseTimedOut = computed(() =>
    Boolean(materialId.value && taskStore.materialTasks.get(materialId.value)?.timedOut),
  )

  const parseProgressText = computed(() => {
    const progress = material.value?.progress_percentage
    return typeof progress === 'number' && progress > 0
      ? `正在提取知识点与原文切片，已完成 ${Math.round(progress)}%...`
      : '智能解析中，正在提取结构化考点与原文切片...'
  })

  const pointHierarchy = computed(() => {
    const point = selectedPointDetail.value || selectedPoint.value
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

  const refreshMastery = async () => {
    if (!materialId.value) return
    try {
      const folderScope = material.value?.folder_id ?? '__none__'
      let overview = await apiGetMasteryOverview(folderScope).catch(() => null)
      if (!overview) {
        overview = await apiGetMasteryOverview().catch(() => null)
      }
      masteryMap.value = buildMasteryMap(overview)
    } catch {
      masteryMap.value = {}
    }
  }

  const refreshKnowledgeTree = async () => {
    if (!materialId.value) return
    const tree = await materialStore.loadKnowledgeTree(materialId.value)
    if (tree?.nodes) {
      knowledgeNodes.value = flattenTreeWithParents(tree.nodes)
    } else {
      knowledgeNodes.value = []
    }
  }

  const loadPrewarmStatus = async (silent = true) => {
    if (!materialId.value) return
    try {
      const status = await apiGetStudyGuidesStatus(
        materialId.value,
        material.value?.current_version_id,
        { silentToast: silent },
      )
      prewarmStatus.value = status
      if (status.status === 'queued' || status.status === 'running') {
        taskStore.trackStudyGuidePrewarm(status, material.value?.title || '考前精讲')
      }
    } catch {
      // 忽略旧环境或瞬时查询失败，不影响页面主流程
    }
  }

  const startPrewarmAll = async () => {
    if (!materialId.value || isStartingPrewarm.value) return
    const currentStatus = prewarmStatus.value?.status
    if (currentStatus === 'queued' || currentStatus === 'running') return
    isStartingPrewarm.value = true
    try {
      const res = await taskStore.startStudyGuidePrewarm(
        materialId.value,
        material.value?.title || '考前精讲',
        { version_id: material.value?.current_version_id },
      )
      prewarmStatus.value = {
        material_id: res.material_id,
        version_id: res.version_id,
        status: res.status,
        total_kps: res.total_kps,
        ready_kps: res.ready_kps,
        failed_kps: 0,
        current_kp_name: null,
      }
      if (res.status === 'completed') {
        await refreshKnowledgeTree()
        safeShowToast('全章精讲已就绪', 'success')
      } else {
        safeShowToast('已启动全章精讲生成', 'success')
      }
    } catch (err: any) {
      if (!(err instanceof RequestError)) {
        safeShowToast(describeFailure(err, '启动精讲预热失败'))
      }
    } finally {
      isStartingPrewarm.value = false
    }
  }

  const loadReadyAssets = async () => {
    await refreshKnowledgeTree()
    await Promise.all([loadGeneratedQuestionCount(), refreshMastery(), loadPrewarmStatus(true)])
  }

  const loadDetail = async () => {
    if (!materialId.value) return
    isLoading.value = true
    try {
      const fetched = await materialStore.fetchMaterialDetail(materialId.value)
      material.value = fetched
      if (fetched.status === 'ready') {
        await loadReadyAssets()
      } else if (isMaterialParsing(fetched)) {
        taskStore.trackMaterialParse(fetched)
      }
    } catch (err) {
      console.error(err)
    } finally {
      isLoading.value = false
    }
  }

  const refreshParseProgress = async () => {
    if (!materialId.value || isRefreshing.value) return
    isRefreshing.value = true
    try {
      const refreshed = await taskStore.refreshMaterialTask(materialId.value)
      if (!refreshed) {
        safeShowToast('刷新进度失败，请稍后重试')
        return
      }
      material.value = refreshed
      if (refreshed.status === 'ready') {
        await loadReadyAssets()
        safeShowToast('讲义已解析完成', 'success')
      } else if (refreshed.status === 'failed' || refreshed.status === 'retake_required') {
        safeShowToast(refreshed.error_message || '解析未能完成')
      } else {
        safeShowToast('已同步最新解析进度')
      }
    } finally {
      isRefreshing.value = false
    }
  }

  watch(
    () => materialStore.currentMaterial,
    async (next) => {
      if (!next || next.id !== materialId.value || isLoading.value) return
      const prevStatus = material.value?.status
      material.value = next
      if (next.status === 'ready' && prevStatus !== 'ready') {
        await loadReadyAssets()
      }
    },
  )

  watch(
    () => (materialId.value ? taskStore.studyGuidePrewarmTasks.get(materialId.value) : undefined),
    async (nextTask) => {
      if (!nextTask) return
      const prevStatus = prewarmStatus.value?.status
      const prevReady = prewarmStatus.value?.ready_kps ?? 0
      prewarmStatus.value = {
        material_id: nextTask.materialId,
        version_id: nextTask.versionId ?? '',
        status: nextTask.status,
        total_kps: nextTask.totalKps,
        ready_kps: nextTask.readyKps,
        failed_kps: nextTask.failedKps,
        current_kp_name: nextTask.currentKpName,
      }
      if (
        (nextTask.status === 'completed' && prevStatus !== 'completed')
        || nextTask.readyKps > prevReady
      ) {
        await refreshKnowledgeTree()
      }
    },
  )

  const initCourse = async (id: string) => {
    materialId.value = id
    await loadDetail()
  }

  const startParse = async (force = false) => {
    if (!materialId.value) return
    const prevMaterial = material.value
    const title = prevMaterial?.title || '学习资料'
    try {
      await withBlockingLoading(force ? '启动重新解析...' : '启动解析流水线...', async () => {
        await taskStore.startMaterialParse(materialId.value, title, force)
      })
      if (prevMaterial) {
        const queuedState: MaterialItem = {
          ...prevMaterial,
          status: 'parsing',
          parse_status: 'queued',
          progress_percentage: 0,
        }
        material.value = queuedState
        materialStore.currentMaterial = queuedState
      }
      safeShowToast(force ? '已启动重新解析' : '已启动后台解析', 'success')
    } catch (err: any) {
      if (!(err instanceof RequestError)) {
        safeShowToast(describeFailure(err, '解析启动失败'))
      }
    }
  }

  const confirmAndReparse = () => {
    if (!materialId.value) return
    if (material.value?.status === 'failed' || material.value?.status === 'retake_required') {
      void startParse(true)
      return
    }
    uni.showModal({
      title: '重新解析讲义',
      content: '重新解析将重新提取原文切片，并重建本讲义的知识点、关联题库与考点掌握度（历史练习作答记录仍会保留），确定继续？',
      confirmText: '重新解析',
      success: ({ confirm }) => {
        if (confirm) void startParse(true)
      },
    })
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
    // 后台解析轮询由全局 backgroundTaskStore 接管，离开页面不中断
  }

  return {
    materialId,
    material,
    knowledgeNodes,
    generatedQuestionCount,
    masteryMap,
    showPointModal,
    selectedPoint,
    selectedPointDetail,
    pointHierarchy,
    pointSnippets,
    isLoading,
    isRefreshing,
    isLoadingSnippets,
    snippetLoadFailed,
    prewarmStatus,
    isStartingPrewarm,
    canStartParse,
    isParsing,
    isParseTimedOut,
    parseProgressText,
    initCourse,
    loadDetail,
    refreshKnowledgeTree,
    loadPrewarmStatus,
    startPrewarmAll,
    refreshParseProgress,
    refreshMastery,
    startParse,
    confirmAndReparse,
    openPointDetail,
    dispose,
  }
}
