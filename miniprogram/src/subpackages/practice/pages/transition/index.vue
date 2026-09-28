<template>
  <view class="transition-page">
    <!-- 顶部状态与动态光环 -->
    <view class="hero-section">
      <view class="pulse-ring-wrapper">
        <view class="pulse-ring" :class="{ 'pulse-ring-slow': isDegraded }" />
        <view class="core-indicator">
          <text class="core-icon">{{ isDegraded ? '...' : activeStep + '/3' }}</text>
        </view>
      </view>

      <text class="main-title">{{ isDegraded ? '诊断分析排队中' : 'AI 助教正在诊断' }}</text>
      <text class="sub-title">
        {{ isDegraded ? '后台正在加速处理您的试卷，您可稍后在学情页查看' : currentStepDescription }}
      </text>
    </view>

    <!-- 三阶段动效进度条 -->
    <view class="steps-card">
      <view
        v-for="(st, index) in steps"
        :key="st.key"
        class="step-row"
        :class="{
          'step-completed': activeStep > index + 1 || isCompleted,
          'step-active': activeStep === index + 1 && !isCompleted && !isDegraded,
          'step-pending': activeStep < index + 1 && !isCompleted,
        }"
      >
        <view class="step-badge">
          <text v-if="activeStep > index + 1 || isCompleted" class="step-check">✓</text>
          <text v-else class="step-number">{{ index + 1 }}</text>
        </view>
        <view class="step-info">
          <text class="step-title">{{ st.title }}</text>
          <text class="step-desc">{{ st.desc }}</text>
        </view>
        <view
          v-if="activeStep === index + 1 && !isCompleted && !isDegraded"
          class="step-loading-dot"
        />
      </view>
    </view>

    <!-- 超时/降级容灾操作区 -->
    <view v-if="isDegraded" class="degraded-actions">
      <view class="btn-primary" @tap="handleGoReview">
        <text class="btn-text">前往学情看板</text>
      </view>
      <view class="btn-secondary" @tap="handleRetryPolling">
        <text class="btn-secondary-text">继续等待生成</text>
      </view>
      <view class="btn-text-link" @tap="handleGoHome">
        <text class="link-text">返回工作台</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * transition/index.vue
 * Stepwise animation transition and diagnostic report polling page.
 * Zero-Emoji Policy enforced. Lines strictly <= 300.
 */

import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { onLoad } from '@dcloudio/uni-app';
import { fetchDiagnosisReport } from '../../../../api/diagnosis';

const props = withDefaults(defineProps<{ practiceId?: string }>(), {
  practiceId: '',
});

const steps = [
  { key: 'step1', title: '客观题精准核验', desc: '单选、多选与判断快速比对' },
  { key: 'step2', title: '主观题多维采分对齐', desc: '比对采分要点与讲义引文' },
  { key: 'step3', title: '学情诊断画像构建', desc: '提炼薄弱知识点与掌握度' },
];

const currentPracticeId = ref<string>('');
const activeStep = ref<number>(1);
const isCompleted = ref<boolean>(false);
const isDegraded = ref<boolean>(false);
const pollCount = ref<number>(0);

const maxPollCount = 20; // 20 * 1500ms = 30s
let pollTimer: ReturnType<typeof setInterval> | null = null;
let stepTimer: ReturnType<typeof setInterval> | null = null;

const currentStepDescription = computed(() => {
  if (activeStep.value === 1) return '正在进行客观题快速核验与计分...';
  if (activeStep.value === 2) return '正在比对主观题采分点与讲义原文出处...';
  return '正在合成知识点掌握度与薄弱点画像...';
});

function advanceStepsAnimation(): void {
  stepTimer = setInterval(() => {
    if (activeStep.value < 3 && !isDegraded.value) {
      activeStep.value += 1;
    }
  }, 2400);
}

async function checkReportStatus(): Promise<void> {
  const pid = currentPracticeId.value;
  if (!pid) return;

  pollCount.value += 1;
  try {
    const res = await fetchDiagnosisReport(pid);
    if (res.code === 0 && res.data && res.data.id) {
      isCompleted.value = true;
      activeStep.value = 3;
      stopTimers();
      setTimeout(() => {
        uni.redirectTo({
          url: `/subpackages/report/pages/detail/index?practice_id=${pid}`,
        });
      }, 500);
      return;
    }
  } catch {
    // Keep polling on transient errors
  }

  if (pollCount.value >= maxPollCount) {
    isDegraded.value = true;
    stopTimers();
  }
}

function startPolling(): void {
  stopTimers();
  pollCount.value = 0;
  isDegraded.value = false;
  advanceStepsAnimation();
  void checkReportStatus();
  pollTimer = setInterval(() => {
    void checkReportStatus();
  }, 1500);
}

function stopTimers(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (stepTimer) {
    clearInterval(stepTimer);
    stepTimer = null;
  }
}

function handleGoReview(): void {
  uni.switchTab({
    url: '/pages/review/index',
  });
}

function handleGoHome(): void {
  uni.switchTab({
    url: '/pages/index/index',
  });
}

function handleRetryPolling(): void {
  startPolling();
}

onLoad((query) => {
  const pid = (query?.practice_id as string) || (query?.id as string) || props.practiceId || '';
  if (pid) {
    currentPracticeId.value = pid;
    startPolling();
  } else if (!props.practiceId) {
    isDegraded.value = true;
  }
});

onMounted(() => {
  const pid = props.practiceId || currentPracticeId.value;
  if (pid && !pollTimer) {
    currentPracticeId.value = pid;
    startPolling();
  }
});

onBeforeUnmount(() => {
  stopTimers();
});
</script>

<style lang="scss" scoped>
@import './transition.scss';
</style>
