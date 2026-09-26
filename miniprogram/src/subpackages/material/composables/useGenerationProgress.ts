/**
 * 出题生成流程示意进度组合式函数。
 *
 * 该组合式函数仅驱动前端界面动画（阶段文案轮播 + 已耗时秒数），
 * 不代表后端真实进度百分比，避免误导用户。
 * 生命周期守护：
 * - `start` 前会先清理旧定时器，避免重复提交造成定时器泄漏；
 * - 请求结束或组件卸载时必须调用 `stop` 释放定时器；
 * - 绑定 onUnmounted 钩子，组件销毁时强力清理。
 * 单文件 <= 300 行，零 Emoji。
 */

import { ref, computed, onUnmounted, getCurrentInstance, type Ref, type ComputedRef } from 'vue';

/** 默认阶段文案，按出题流水线顺序排列。 */
export const GENERATION_STAGES: string[] = ['检索切片', '命制题目', '质检门禁'];

export interface UseGenerationProgressOptions {
  /** 阶段文案列表，默认 {@link GENERATION_STAGES}。 */
  stages?: string[];
  /** 阶段切换间隔毫秒数，默认 4000ms。 */
  stageInterval?: number;
  /** 计时器自增间隔毫秒数，默认 1000ms。 */
  tickInterval?: number;
}

export interface UseGenerationProgressReturn {
  stages: string[];
  stageIndex: Ref<number>;
  elapsedSeconds: Ref<number>;
  isRunning: Ref<boolean>;
  currentStage: ComputedRef<string>;
  start: () => void;
  stop: () => void;
}

/**
 * 创建生成进度示意动画状态。
 *
 * @param options 可选的阶段文案与定时配置。
 * @returns 阶段索引、已耗时秒数、运行状态与控制方法。
 */
export function useGenerationProgress(
  options: UseGenerationProgressOptions = {},
): UseGenerationProgressReturn {
  const stages = options.stages ?? GENERATION_STAGES;
  const stageInterval = options.stageInterval ?? 4000;
  const tickInterval = options.tickInterval ?? 1000;

  const stageIndex = ref<number>(0);
  const elapsedSeconds = ref<number>(0);
  const isRunning = ref<boolean>(false);

  let stageTimer: ReturnType<typeof setInterval> | null = null;
  let tickTimer: ReturnType<typeof setInterval> | null = null;

  const currentStage = computed<string>(() => stages[stageIndex.value] ?? stages[0]);

  /** 停止所有定时器并复位运行状态。 */
  function stop(): void {
    if (stageTimer !== null) {
      clearInterval(stageTimer);
      stageTimer = null;
    }
    if (tickTimer !== null) {
      clearInterval(tickTimer);
      tickTimer = null;
    }
    isRunning.value = false;
  }

  /** 启动阶段轮播与计时。重复调用会先清理旧定时器。 */
  function start(): void {
    stop();
    stageIndex.value = 0;
    elapsedSeconds.value = 0;
    isRunning.value = true;

    stageTimer = setInterval(() => {
      if (stageIndex.value < stages.length - 1) {
        stageIndex.value += 1;
      }
    }, stageInterval);

    tickTimer = setInterval(() => {
      elapsedSeconds.value += 1;
    }, tickInterval);
  }

  if (getCurrentInstance()) {
    onUnmounted(() => {
      stop();
    });
  }

  return { stages, stageIndex, elapsedSeconds, isRunning, currentStage, start, stop };
}
