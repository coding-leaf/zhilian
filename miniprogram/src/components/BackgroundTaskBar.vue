<template>
  <view v-if="tasks.length > 0" class="task-bar-container">
    <view v-for="task in tasks" :key="task.key" :class="['task-strip', `task-${task.status}`]">
      <view class="task-row">
        <view class="task-left">
          <view :class="['task-dot', `dot-${task.status}`]" />
          <text class="task-text">{{ task.detailText }}</text>
        </view>
        <view class="task-actions">
          <text v-if="task.actionLabel" class="task-action-btn" @tap="handleOpenTask(task)">
            {{ task.actionLabel }}
          </text>
          <text v-if="task.dismissible" class="task-dismiss-btn" @tap="handleDismiss(task)">
            关闭
          </text>
        </view>
      </view>
      <view v-if="task.status === 'active' && task.progressPercent > 0" class="progress-track">
        <view class="progress-fill" :style="{ width: `${task.progressPercent}%` }" />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useBackgroundTaskStore, type BackgroundTaskItem } from '@/stores/backgroundTask'

defineOptions({ options: { virtualHost: true } })

const props = defineProps<{
  disableAutoNavigate?: boolean
  autoRefresh?: boolean
}>()

const emit = defineEmits<{
  (e: 'open-task', task: BackgroundTaskItem): void
  (e: 'dismiss', task: BackgroundTaskItem): void
}>()

const taskStore = useBackgroundTaskStore()
const tasks = computed(() => taskStore.visibleTasks)

onMounted(() => {
  if (props.autoRefresh) void taskStore.refreshActiveTasks()
})

const navigateToTask = (task: BackgroundTaskItem) => {
  if (task.kind === 'material_parse' && task.materialId) {
    uni.navigateTo({
      url: `/subpackages/material/pages/course/index?id=${task.materialId}`,
      fail: () => uni.showToast({ title: '打开讲义详情失败', icon: 'none' }),
    })
    return
  }
  if (task.kind !== 'question_job') return
  const query: string[] = ['view=generated']
  if (task.materialId) query.unshift(`material_id=${encodeURIComponent(task.materialId)}`)
  else if (task.folderId) query.unshift(`folder_id=${encodeURIComponent(task.folderId)}`)
  else {
    uni.switchTab({
      url: '/pages/review/index',
      fail: () => uni.showToast({ title: '跳转学情页失败', icon: 'none' }),
    })
    return
  }
  if (task.batchId) query.push(`batch_id=${encodeURIComponent(task.batchId)}`)
  uni.navigateTo({
    url: `/subpackages/material/pages/questions/index?${query.join('&')}`,
    fail: () => uni.showToast({ title: '打开出题结果失败', icon: 'none' }),
  })
}

const handleOpenTask = (task: BackgroundTaskItem) => {
  emit('open-task', task)
  if (task.timedOut && task.kind === 'material_parse' && task.materialId) {
    void taskStore.refreshMaterialTask(task.materialId)
    return
  }
  if (!props.disableAutoNavigate) navigateToTask(task)
  if (task.dismissible) taskStore.dismissTask(task.key)
}

const handleDismiss = (task: BackgroundTaskItem) => {
  taskStore.dismissTask(task.key)
  emit('dismiss', task)
}
</script>

<style lang="scss" scoped>
.task-bar-container {
  position: sticky; top: 0; z-index: var(--z-sticky);
  display: flex; flex-direction: column; gap: 8rpx; margin-bottom: 16rpx;
}
.task-strip {
  border-radius: 12rpx; padding: 14rpx 20rpx;
  border: 1px solid var(--color-paper-border); background: var(--color-bg-card);
  box-shadow: 0 4rpx 12rpx var(--color-scrim-light);
}
.task-active { background: var(--color-blue-bg); border-color: var(--color-blue-border); }
.task-completed { background: var(--color-success-bg); border-color: var(--color-success-border); }
.task-failed { background: var(--color-danger-bg); border-color: var(--color-danger-border); }
.task-row { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.task-left { flex: 1; min-width: 0; display: flex; align-items: center; gap: 12rpx; }
.task-dot { width: 14rpx; height: 14rpx; border-radius: 999rpx; flex-shrink: 0; }
.dot-active { background: var(--color-academic-blue); }
.dot-completed { background: var(--color-success); }
.dot-failed { background: var(--color-danger); }
.task-text {
  flex: 1; min-width: 0; font-size: 24rpx; color: var(--color-ink-primary);
  font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.task-actions { display: flex; align-items: center; gap: 12rpx; flex-shrink: 0; }
.task-action-btn {
  font-size: 22rpx; font-weight: 600; color: var(--color-ink-on-primary);
  background: var(--color-academic-blue); padding: 6rpx 16rpx; border-radius: 999rpx;
}
.task-dismiss-btn { font-size: 22rpx; color: var(--color-ink-subtle); padding: 6rpx 10rpx; }
.progress-track {
  margin-top: 10rpx; height: 6rpx; border-radius: 999rpx;
  background: var(--color-blue-border); overflow: hidden;
}
.progress-fill {
  height: 100%; background: var(--color-academic-blue);
  border-radius: 999rpx; transition: width 0.25s ease;
}
</style>
