import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  apiCreateQuestionJob,
  apiGetMaterialDetail,
  apiGetMaterialList,
  apiGetQuestionJob,
  apiListQuestionJobs,
  apiParseMaterial,
} from '@/api'
import type {
  GenerateQuestionsParams,
  MaterialItem,
  MaterialStatus,
  QuestionGenerationJob,
} from '@/types'
import { isMaterialParsing } from '@/utils/materialState'
import { createPoller, type PollerHandle } from '@/utils/poller'
import { useMaterialStore } from './material'

export interface MaterialParseTask {
  materialId: string
  title: string
  status: MaterialStatus
  parseStatus?: string | null
  progressPercentage: number
  updatedAt: number
  timedOut?: boolean
}

export interface BackgroundTaskItem {
  key: string
  kind: 'material_parse' | 'question_job'
  targetId: string
  status: 'active' | 'completed' | 'failed'
  title: string
  detailText: string
  progressPercent: number
  materialId?: string | null
  folderId?: string | null
  batchId?: string | null
  actionLabel?: string
  timedOut?: boolean
  dismissible: boolean
}

export const FAST_POLL_INTERVAL_MS = 2500
export const FAST_POLL_ATTEMPTS = 48
export const SLOW_POLL_INTERVAL_MS = 5000
export const SLOW_POLL_ATTEMPTS = 157

const TERMINAL_MATERIAL_STATUSES = new Set<MaterialStatus>([
  'ready',
  'failed',
  'retake_required',
])

export function isQuestionJobActive(job: Pick<QuestionGenerationJob, 'status'>): boolean {
  return job.status === 'queued' || job.status === 'running'
}

export const useBackgroundTaskStore = defineStore('backgroundTask', () => {
  const materialTasks = ref<Map<string, MaterialParseTask>>(new Map())
  const questionJobs = ref<Map<string, QuestionGenerationJob>>(new Map())
  const dismissedKeys = ref<Set<string>>(new Set())
  const isPolling = ref(false)
  let poller: PollerHandle = createPoller()
  let scheduleTimer: ReturnType<typeof setTimeout> | null = null

  const clearScheduleTimer = (): void => {
    if (scheduleTimer !== null) {
      clearTimeout(scheduleTimer)
      scheduleTimer = null
    }
  }

  const activeMaterialIds = computed(() =>
    Array.from(materialTasks.value.values())
      .filter((task) => !TERMINAL_MATERIAL_STATUSES.has(task.status))
      .map((task) => task.materialId),
  )

  const activeQuestionJobIds = computed(() =>
    Array.from(questionJobs.value.values())
      .filter((job) => isQuestionJobActive(job))
      .map((job) => job.id),
  )

  const hasActiveTasks = computed(
    () => activeMaterialIds.value.length > 0 || activeQuestionJobIds.value.length > 0,
  )

  const syncMaterialStoreItem = (item: MaterialItem): void => {
    try {
      const materialStore = useMaterialStore()
      if (materialStore.currentMaterial?.id === item.id) {
        materialStore.currentMaterial = item
      }
      const idx = materialStore.materialList.findIndex((m) => m.id === item.id)
      if (idx !== -1) {
        const nextList = [...materialStore.materialList]
        nextList[idx] = item
        materialStore.materialList = nextList
      }
    } catch {
      // ignore if pinia store not bound in isolated unit test
    }
  }

  const unDismiss = (key: string): void => {
    if (!dismissedKeys.value.has(key)) return
    const next = new Set(dismissedKeys.value)
    next.delete(key)
    dismissedKeys.value = next
  }

  const setMaterialTask = (task: MaterialParseTask): void => {
    const next = new Map(materialTasks.value)
    next.set(task.materialId, task)
    materialTasks.value = next
  }

  const setQuestionJob = (job: QuestionGenerationJob): void => {
    const next = new Map(questionJobs.value)
    next.set(job.id, job)
    questionJobs.value = next
  }

  const trackMaterialParse = (material: MaterialItem): void => {
    const key = `mat:${material.id}`
    if (isMaterialParsing(material)) {
      unDismiss(key)
    }
    setMaterialTask({
      materialId: material.id,
      title: material.title || '学习资料',
      status: material.status,
      parseStatus: material.parse_status ?? null,
      progressPercentage: Math.max(0, Math.min(100, material.progress_percentage ?? 0)),
      updatedAt: Date.now(),
      timedOut: false,
    })
    if (!TERMINAL_MATERIAL_STATUSES.has(material.status)) {
      schedulePolling()
    }
  }

  const trackQuestionJob = (job: QuestionGenerationJob): void => {
    const key = `job:${job.id}`
    if (isQuestionJobActive(job)) {
      unDismiss(key)
    }
    setQuestionJob(job)
    if (isQuestionJobActive(job)) {
      schedulePolling()
    }
  }

  const startMaterialParse = async (
    materialId: string,
    title = '学习资料',
    force = false,
  ): Promise<{ message: string }> => {
    const res = await apiParseMaterial(materialId, force)
    unDismiss(`mat:${materialId}`)
    setMaterialTask({
      materialId,
      title,
      status: 'parsing',
      parseStatus: 'queued',
      progressPercentage: 0,
      updatedAt: Date.now(),
      timedOut: false,
    })
    schedulePolling()
    return res
  }

  const startQuestionJob = async (
    params: GenerateQuestionsParams,
  ): Promise<QuestionGenerationJob> => {
    const job = await apiCreateQuestionJob(params)
    trackQuestionJob(job)
    return job
  }

  const pollOnce = async (): Promise<boolean> => {
    const matIds = [...activeMaterialIds.value]
    const jobIds = [...activeQuestionJobIds.value]

    await Promise.all([
      ...matIds.map(async (materialId) => {
        try {
          const item = await apiGetMaterialDetail(materialId)
          syncMaterialStoreItem(item)
          const existing = materialTasks.value.get(materialId)
          setMaterialTask({
            materialId: item.id,
            title: item.title || existing?.title || '学习资料',
            status: item.status,
            parseStatus: item.parse_status ?? null,
            progressPercentage: Math.max(0, Math.min(100, item.progress_percentage ?? 0)),
            updatedAt: Date.now(),
            timedOut: false,
          })
        } catch (err) {
          console.error('[backgroundTask] poll material failed', materialId, err)
        }
      }),
      ...jobIds.map(async (jobId) => {
        try {
          const job = await apiGetQuestionJob(jobId)
          setQuestionJob(job)
        } catch (err) {
          console.error('[backgroundTask] poll question job failed', jobId, err)
        }
      }),
    ])

    return !hasActiveTasks.value
  }

  const markActiveMaterialTasksTimedOut = (): void => {
    const next = new Map(materialTasks.value)
    let changed = false
    for (const [id, task] of next.entries()) {
      if (!TERMINAL_MATERIAL_STATUSES.has(task.status) && !task.timedOut) {
        next.set(id, { ...task, timedOut: true, updatedAt: Date.now() })
        changed = true
      }
    }
    if (changed) materialTasks.value = next
  }

  const refreshMaterialTask = async (materialId: string): Promise<MaterialItem | null> => {
    try {
      const item = await apiGetMaterialDetail(materialId)
      syncMaterialStoreItem(item)
      const existing = materialTasks.value.get(materialId)
      setMaterialTask({
        materialId: item.id,
        title: item.title || existing?.title || '学习资料',
        status: item.status,
        parseStatus: item.parse_status ?? null,
        progressPercentage: Math.max(0, Math.min(100, item.progress_percentage ?? 0)),
        updatedAt: Date.now(),
        timedOut: false,
      })
      if (!TERMINAL_MATERIAL_STATUSES.has(item.status)) {
        schedulePolling()
      }
      return item
    } catch (err) {
      console.error('[backgroundTask] refresh material failed', materialId, err)
      return null
    }
  }

  const ensurePolling = async (
    intervalMs = FAST_POLL_INTERVAL_MS,
    maxAttempts?: number,
  ): Promise<void> => {
    clearScheduleTimer()
    if (!hasActiveTasks.value || isPolling.value) return
    isPolling.value = true
    try {
      const useStagedSchedule = maxAttempts === undefined
      const resolvedAttempts = useStagedSchedule
        ? FAST_POLL_ATTEMPTS + SLOW_POLL_ATTEMPTS
        : maxAttempts
      const resolvedInterval = useStagedSchedule
        ? (attempt: number) =>
            attempt < FAST_POLL_ATTEMPTS ? intervalMs : Math.max(intervalMs, SLOW_POLL_INTERVAL_MS)
        : intervalMs
      const result = await poller.run(() => pollOnce(), {
        maxAttempts: resolvedAttempts,
        intervalMs: resolvedInterval,
        isDone: (allDone) => allDone,
      })
      if (result.status === 'timeout' && hasActiveTasks.value) {
        markActiveMaterialTasksTimedOut()
      }
    } finally {
      isPolling.value = false
    }
  }

  const schedulePolling = (delayMs = 2500): void => {
    if (!hasActiveTasks.value || isPolling.value || scheduleTimer !== null) return
    scheduleTimer = setTimeout(() => {
      scheduleTimer = null
      void ensurePolling(delayMs)
    }, delayMs)
  }

  const refreshActiveTasks = async (): Promise<void> => {
    try {
      const [materials, jobList] = await Promise.all([
        apiGetMaterialList().catch(() => [] as MaterialItem[]),
        apiListQuestionJobs({ active_only: true }).catch(() => ({ items: [], total: 0 })),
      ])

      for (const material of materials) {
        if (isMaterialParsing(material)) {
          trackMaterialParse(material)
        } else if (materialTasks.value.has(material.id)) {
          trackMaterialParse(material)
        }
      }

      for (const job of jobList.items) {
        trackQuestionJob(job)
      }

      if (hasActiveTasks.value) {
        schedulePolling()
      }
    } catch (err) {
      console.error('[backgroundTask] refresh active tasks failed', err)
    }
  }

  const dismissTask = (key: string): void => {
    const nextDismissed = new Set(dismissedKeys.value)
    nextDismissed.add(key)
    dismissedKeys.value = nextDismissed

    if (key.startsWith('mat:')) {
      const id = key.slice(4)
      const task = materialTasks.value.get(id)
      if (task && TERMINAL_MATERIAL_STATUSES.has(task.status)) {
        const next = new Map(materialTasks.value)
        next.delete(id)
        materialTasks.value = next
      }
    } else if (key.startsWith('job:')) {
      const id = key.slice(4)
      const job = questionJobs.value.get(id)
      if (job && !isQuestionJobActive(job)) {
        const next = new Map(questionJobs.value)
        next.delete(id)
        questionJobs.value = next
      }
    }
  }

  const stopPolling = (): void => {
    clearScheduleTimer()
    poller.stop()
    isPolling.value = false
  }

  const reset = (): void => {
    clearScheduleTimer()
    poller.dispose()
    poller = createPoller()
    isPolling.value = false
    materialTasks.value = new Map()
    questionJobs.value = new Map()
    dismissedKeys.value = new Set()
  }

  const visibleTasks = computed<BackgroundTaskItem[]>(() => {
    const list: BackgroundTaskItem[] = []

    for (const task of materialTasks.value.values()) {
      const key = `mat:${task.materialId}`
      if (dismissedKeys.value.has(key)) continue
      const isActive = !TERMINAL_MATERIAL_STATUSES.has(task.status)
      if (isActive) {
        const stageText = task.timedOut
          ? '进度同步已暂停（点击刷新）'
          : task.parseStatus === 'queued'
            ? '排队解析中...'
            : `解析中${task.progressPercentage > 0 ? ` (${task.progressPercentage}%)` : '...'}`
        list.push({
          key,
          kind: 'material_parse',
          targetId: task.materialId,
          status: 'active',
          title: task.title,
          detailText: `${task.title} · ${stageText}`,
          progressPercent: task.progressPercentage,
          materialId: task.materialId,
          actionLabel: task.timedOut ? '刷新' : undefined,
          timedOut: Boolean(task.timedOut),
          dismissible: false,
        })
      } else if (task.status === 'ready') {
        list.push({
          key,
          kind: 'material_parse',
          targetId: task.materialId,
          status: 'completed',
          title: task.title,
          detailText: `${task.title} 解析完毕`,
          progressPercent: 100,
          materialId: task.materialId,
          actionLabel: '去查看',
          dismissible: true,
        })
      } else {
        const failText =
          task.status === 'retake_required'
            ? `${task.title} 文字模糊，需重拍`
            : `${task.title} 解析失败`
        list.push({
          key,
          kind: 'material_parse',
          targetId: task.materialId,
          status: 'failed',
          title: task.title,
          detailText: failText,
          progressPercent: 0,
          materialId: task.materialId,
          actionLabel: '去查看',
          dismissible: true,
        })
      }
    }

    for (const job of questionJobs.value.values()) {
      const key = `job:${job.id}`
      if (dismissedKeys.value.has(key)) continue
      if (isQuestionJobActive(job)) {
        const progressPercent =
          job.total_kps > 0
            ? Math.min(100, Math.round((job.completed_kps / job.total_kps) * 100))
            : 0
        const detailText =
          job.total_kps > 0
            ? `正在后台出题 ${job.completed_kps}/${job.total_kps} 考点...`
            : job.status === 'queued'
              ? '正在排队出题...'
              : '正在后台出题...'
        list.push({
          key,
          kind: 'question_job',
          targetId: job.id,
          status: 'active',
          title: '后台智能出题',
          detailText,
          progressPercent,
          materialId: job.material_id,
          folderId: job.folder_id,
          batchId: job.batch_id,
          dismissible: false,
        })
      } else if (job.status === 'completed') {
        list.push({
          key,
          kind: 'question_job',
          targetId: job.id,
          status: 'completed',
          title: '后台智能出题',
          detailText: `题目已生成完毕（${job.generated_count} 题）`,
          progressPercent: 100,
          materialId: job.material_id,
          folderId: job.folder_id,
          batchId: job.batch_id,
          actionLabel: '去查看',
          dismissible: true,
        })
      } else {
        list.push({
          key,
          kind: 'question_job',
          targetId: job.id,
          status: 'failed',
          title: '后台智能出题',
          detailText: job.error_message ? `出题失败：${job.error_message}` : '后台出题失败',
          progressPercent: 0,
          materialId: job.material_id,
          folderId: job.folder_id,
          batchId: job.batch_id,
          dismissible: true,
        })
      }
    }

    // 进行中任务排在最前
    return list.sort((a, b) => {
      if (a.status === 'active' && b.status !== 'active') return -1
      if (a.status !== 'active' && b.status === 'active') return 1
      return 0
    })
  })

  return {
    materialTasks,
    questionJobs,
    isPolling,
    activeMaterialIds,
    activeQuestionJobIds,
    hasActiveTasks,
    visibleTasks,
    trackMaterialParse,
    trackQuestionJob,
    startMaterialParse,
    startQuestionJob,
    refreshActiveTasks,
    refreshMaterialTask,
    pollOnce,
    ensurePolling,
    stopPolling,
    dismissTask,
    reset,
  }
})
