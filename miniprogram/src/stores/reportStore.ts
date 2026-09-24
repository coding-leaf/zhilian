/**
 * Report Store
 * Manages diagnostic reports, user mastery overview, and weak points state.
 * Enforces pure state mutation without direct network API calls.
 */

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { DiagnosisReport, UserMasteryOverview, WeakPoint, MasteryTier } from '../types/report';

export type MasteryOverview = UserMasteryOverview;

export const useReportStore = defineStore('report', () => {
  // State
  const currentReport = ref<DiagnosisReport | null>(null);
  const masteryOverview = ref<UserMasteryOverview | null>(null);
  const weakPoints = ref<WeakPoint[]>([]);

  // Getters
  const currentReportId = computed(() => currentReport.value?.id ?? null);
  const overallMasteryRate = computed(() => currentReport.value?.mastery_rate ?? 0);
  const weakPointCount = computed(() => weakPoints.value.length);

  const masteryTier = computed<MasteryTier>(() => {
    const rate = overallMasteryRate.value;
    if (rate >= 85) {
      return 'mastered';
    }
    if (rate >= 70) {
      return 'proficient';
    }
    if (rate >= 40) {
      return 'weak';
    }
    return 'unlearned';
  });

  // Actions
  function setReport(report: DiagnosisReport | null): void {
    currentReport.value = report;
    if (report?.weak_points) {
      weakPoints.value = [...report.weak_points];
    }
  }

  function setReportSummary(report: DiagnosisReport | null): void {
    setReport(report);
  }

  function setMasteryOverview(overview: UserMasteryOverview | null): void {
    masteryOverview.value = overview;
  }

  function setWeakPoints(points: WeakPoint[]): void {
    weakPoints.value = [...points];
  }

  function clearReport(): void {
    currentReport.value = null;
    masteryOverview.value = null;
    weakPoints.value = [];
  }

  function resetReportState(): void {
    clearReport();
  }

  return {
    currentReport,
    masteryOverview,
    weakPoints,
    currentReportId,
    overallMasteryRate,
    weakPointCount,
    masteryTier,
    setReport,
    setReportSummary,
    setMasteryOverview,
    setWeakPoints,
    clearReport,
    resetReportState,
  };
});

export default useReportStore;
