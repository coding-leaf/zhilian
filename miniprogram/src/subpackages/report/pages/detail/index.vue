<template>
  <view class="report-detail-page">
    <!-- 骨架屏加载状态 -->
    <view v-if="loading" class="skeleton-wrapper">
      <view class="skeleton-card">
        <view class="skeleton-line short" />
        <view class="skeleton-line tall" />
        <view class="skeleton-line medium" />
      </view>
      <view class="skeleton-card">
        <view class="skeleton-line medium" />
        <view class="skeleton-line short" />
      </view>
    </view>

    <!-- 异常状态 -->
    <view v-else-if="error" class="error-state">
      <text class="error-text">{{ error }}</text>
      <view class="retry-btn" @tap="handleRetry">
        <text>重新加载</text>
      </view>
    </view>

    <!-- 报告内容主体 -->
    <view v-else-if="currentReport" class="report-content">
      <!-- 概览摘要卡片 -->
      <DiagnosisSummaryCard :report="currentReport" :duration-seconds="durationSeconds" />

      <!-- 薄弱知识点诊断卡片 -->
      <WeakKnowledgeCard
        v-if="currentReport.weak_points && currentReport.weak_points.length > 0"
        :weak-points="currentReport.weak_points"
      />

      <!-- 逐题判题结果列表 -->
      <GradingResultList
        :items="items"
        @view-snippet="handleViewSnippet"
        @self-grade="handleOpenSelfGrade"
        @regrade="handleOpenRegrade"
      />
    </view>

    <!-- 吸底一键继续练习操作栏 -->
    <view v-if="!loading && currentReport" class="bottom-action-bar">
      <view class="continue-btn" @tap="handleContinuePractice">
        <text>一键强化薄弱点练习</text>
      </view>
    </view>

    <!-- 原文切片溯源抽屉 -->
    <OriginalSnippetDrawer
      :visible="snippetDrawerVisible"
      :snippet-content="activeSnippet?.snippet_content || ''"
      :chapter-title="activeSnippet?.chapter_title || ''"
      :page-index="activeSnippet?.page_index || 0"
      :highlight-keywords="snippetKeywords"
      @update:visible="snippetDrawerVisible = $event"
      @close="snippetDrawerVisible = false"
    />

    <!-- 主观题自评弹窗 -->
    <SelfGradeModal
      :visible="selfGradeVisible"
      :attempt-item-id="activeGradeItem?.attempt_item_id || ''"
      :stem="activeGradeItem?.question_snapshot?.stem || ''"
      :user-answer="formatUserAnswer(activeGradeItem?.user_answer)"
      :standard-answer="activeGradeItem?.question_snapshot?.answer || ''"
      :max-score="activeGradeItem?.max_score ?? 5.0"
      :current-score="activeGradeItem?.score ?? 0"
      :rubric="
        (activeGradeItem?.question_snapshot?.grading_rubric as Record<string, unknown>) || {}
      "
      @update:visible="selfGradeVisible = $event"
      @success="onSelfGradeSuccess"
    />

    <!-- 申请重判弹窗 -->
    <RegradeModal
      :visible="regradeVisible"
      :attempt-item-id="activeRegradeItem?.attempt_item_id || ''"
      :stem="activeRegradeItem?.question_snapshot?.stem || ''"
      @update:visible="regradeVisible = $event"
      @success="onRegradeSuccess"
    />
  </view>
</template>

<script setup lang="ts">
/**
 * index.vue (subpackages/report/pages/detail)
 * Diagnostic Report Assembly Page.
 * Integrates summary card, weakness card, grading results, snippet drawer, and modals.
 * Complies with docs/DESIGN.md & spec ZL-135.
 * Zero-Emoji Policy enforced.
 */

import { ref, computed, onMounted } from 'vue';
import { onLoad } from '@dcloudio/uni-app';
import { useReportStore } from '@/stores/reportStore';
import { fetchDiagnosisReport, continuePractice } from '@/api/diagnosis';
import { fetchPracticeSession } from '@/api/practice';
import type { AttemptGradingItem, OriginalSnippet } from '@/types/report';

import DiagnosisSummaryCard from '../../components/DiagnosisSummaryCard.vue';
import WeakKnowledgeCard from '../../components/WeakKnowledgeCard.vue';
import GradingResultList from '../../components/GradingResultList.vue';
import OriginalSnippetDrawer from '../../components/OriginalSnippetDrawer.vue';
import SelfGradeModal from '../../components/SelfGradeModal.vue';
import RegradeModal from '../../components/RegradeModal.vue';

interface Props {
  practiceId?: string;
}

const props = withDefaults(defineProps<Props>(), {
  practiceId: '',
});

const reportStore = useReportStore();

const loading = ref(true);
const error = ref<string | null>(null);
const currentPracticeId = ref(props.practiceId || '');
const durationSeconds = ref(0);
const materialId = ref('');
const items = ref<AttemptGradingItem[]>([]);

// Snippet drawer state
const snippetDrawerVisible = ref(false);
const activeSnippet = ref<OriginalSnippet | null>(null);
const snippetKeywords = ref<string[]>([]);

// Modals state
const selfGradeVisible = ref(false);
const activeGradeItem = ref<AttemptGradingItem | null>(null);

const regradeVisible = ref(false);
const activeRegradeItem = ref<AttemptGradingItem | null>(null);

const currentReport = computed(() => reportStore.currentReport);

function formatUserAnswer(ans?: unknown): string {
  if (ans === null || ans === undefined || ans === '') return '';
  if (Array.isArray(ans)) return ans.join(', ');
  return String(ans);
}

async function loadReportData(pid: string): Promise<void> {
  if (!pid) return;
  loading.value = true;
  error.value = null;
  try {
    const [reportRes, practiceRes] = await Promise.all([
      fetchDiagnosisReport(pid),
      fetchPracticeSession(pid).catch(() => null),
    ]);

    if (reportRes.code === 0 && reportRes.data) {
      reportStore.setReport(reportRes.data);
    } else {
      error.value = reportRes.message || '获取诊断报告失败';
      return;
    }

    const repData = reportRes.data as unknown as { items?: AttemptGradingItem[] };
    const pracData = practiceRes?.data as unknown as
      | {
          items?: AttemptGradingItem[];
          material_id?: string;
          time_elapsed_seconds?: number;
        }
      | undefined;

    if (Array.isArray(repData.items) && repData.items.length > 0) {
      items.value = repData.items;
    } else if (Array.isArray(pracData?.items)) {
      items.value = pracData.items;
    }

    if (pracData?.material_id) {
      materialId.value = pracData.material_id;
    }
    if (pracData?.time_elapsed_seconds) {
      durationSeconds.value = pracData.time_elapsed_seconds;
    }
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : '网络请求异常';
  } finally {
    loading.value = false;
  }
}

function handleRetry(): void {
  if (currentPracticeId.value) {
    loadReportData(currentPracticeId.value);
  }
}

function handleViewSnippet(item: AttemptGradingItem): void {
  activeSnippet.value = item.question_snapshot?.source_snippet || null;
  snippetKeywords.value = [
    ...(item.question_snapshot?.hit_keywords || []),
    ...(item.question_snapshot?.missing_keywords || []),
  ];
  snippetDrawerVisible.value = true;
}

function handleOpenSelfGrade(item: AttemptGradingItem): void {
  activeGradeItem.value = item;
  selfGradeVisible.value = true;
}

function handleOpenRegrade(item: AttemptGradingItem): void {
  activeRegradeItem.value = item;
  regradeVisible.value = true;
}

function onSelfGradeSuccess(payload: { attempt_item_id: string; score: number }): void {
  const target = items.value.find((it) => it.attempt_item_id === payload.attempt_item_id);
  if (target) {
    target.score = payload.score;
    target.status = 'graded';
  }
  if (currentPracticeId.value) {
    fetchDiagnosisReport(currentPracticeId.value)
      .then((res) => {
        if (res.code === 0 && res.data) {
          reportStore.setReport(res.data);
        }
      })
      .catch(() => {});
  }
}

function onRegradeSuccess(payload: { attempt_item_id: string }): void {
  const target = items.value.find((it) => it.attempt_item_id === payload.attempt_item_id);
  if (target) {
    target.status = 'pending_regrade';
  }
  if (currentPracticeId.value) {
    fetchDiagnosisReport(currentPracticeId.value)
      .then((res) => {
        if (res.code === 0 && res.data) {
          reportStore.setReport(res.data);
        }
      })
      .catch(() => {});
  }
}

async function handleContinuePractice(): Promise<void> {
  const rep = reportStore.currentReport;
  if (!rep) return;
  const weakIds = rep.weak_points?.map((p) => p.knowledge_point_id) || [];
  try {
    const res = await continuePractice({
      material_id: materialId.value,
      knowledge_point_ids: weakIds,
      source_report_id: rep.id,
      title: '薄弱点强化练习',
    });
    if (res.data?.id) {
      uni.navigateTo({
        url: `/subpackages/practice/pages/session/index?id=${res.data.id}`,
      });
    } else {
      uni.showToast({ title: '无法创建强化练习', icon: 'none' });
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : '创建强化练习异常';
    uni.showToast({ title: msg, icon: 'none' });
  }
}

onMounted(() => {
  const pid = props.practiceId || currentPracticeId.value;
  if (pid) {
    currentPracticeId.value = pid;
    loadReportData(pid);
  } else {
    loading.value = false;
  }
});

onLoad((query?: Record<string, string>) => {
  const pid = query?.practice_id || query?.id;
  if (pid) {
    currentPracticeId.value = pid;
    loadReportData(pid);
  }
});
</script>

<style lang="scss" scoped>
@import './detail.scss';
</style>
