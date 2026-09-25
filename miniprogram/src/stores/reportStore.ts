/**
 * Report Store
 * Manages diagnostic reports, user mastery overview, and weak points state.
 * Enforces pure state mutation without direct network API calls.
 */

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type {
  DiagnosisReport,
  UserMasteryOverview,
  WeakPoint,
  MasteryTier,
  WrongRecordItem,
  WrongRecordQueryParams,
} from '../types/report';

export type MasteryOverview = UserMasteryOverview;

export const useReportStore = defineStore('report', () => {
  // State
  const currentReport = ref<DiagnosisReport | null>(null);
  const masteryOverview = ref<UserMasteryOverview | null>(null);
  const weakPoints = ref<WeakPoint[]>([]);

  // Wrong Book State (In-memory only, no storage persistence)
  const wrongRecords = ref<WrongRecordItem[]>([]);
  const wrongBookList = wrongRecords; // Alias for wrongRecords
  const wrongRecordTotal = ref<number>(0);
  const selectedRecordIds = ref<string[]>([]);
  const wrongFilters = ref<WrongRecordQueryParams>({});
  const wrongPage = ref<number>(1);
  const wrongPageSize = ref<number>(20);
  const wrongHasMore = ref<boolean>(true);

  // Getters
  const currentReportId = computed(() => currentReport.value?.id ?? null);
  const overallMasteryRate = computed(() => currentReport.value?.mastery_rate ?? 0);
  const weakPointCount = computed(() => weakPoints.value.length);
  const selectedRecordCount = computed(() => selectedRecordIds.value.length);

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

  // Actions - Diagnosis Report
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

  // Actions - Wrong Book In-Memory Management
  function setWrongRecords(items: WrongRecordItem[], total: number): void {
    wrongRecords.value = items.map((it) => ({ ...it }));
    wrongRecordTotal.value = total;
    wrongHasMore.value = wrongRecords.value.length < total;
  }

  function setWrongBookList(items: WrongRecordItem[], total: number): void {
    setWrongRecords(items, total);
  }

  function appendWrongRecords(items: WrongRecordItem[], total?: number): void {
    wrongRecords.value = [...wrongRecords.value, ...items.map((it) => ({ ...it }))];
    if (typeof total === 'number') {
      wrongRecordTotal.value = total;
    }
    wrongHasMore.value = wrongRecords.value.length < wrongRecordTotal.value;
  }

  function updateWrongRecordMastered(
    id: string,
    isMastered: boolean,
    masteredAt?: string | null,
  ): void {
    const item = wrongRecords.value.find((r) => r.id === id);
    if (item) {
      item.is_mastered = isMastered;
      if (masteredAt !== undefined) {
        item.mastered_at = masteredAt;
      } else if (isMastered) {
        item.mastered_at = new Date().toISOString();
      } else {
        item.mastered_at = null;
      }
    }
  }

  function toggleSelectRecord(id: string): void {
    const idx = selectedRecordIds.value.indexOf(id);
    if (idx >= 0) {
      selectedRecordIds.value.splice(idx, 1);
    } else {
      selectedRecordIds.value.push(id);
    }
  }

  function selectAllRecords(ids: string[]): void {
    selectedRecordIds.value = [...ids];
  }

  function clearSelectedRecords(): void {
    selectedRecordIds.value = [];
  }

  function setWrongFilters(filters: WrongRecordQueryParams): void {
    wrongFilters.value = { ...filters };
  }

  function setWrongPage(page: number): void {
    wrongPage.value = page;
  }

  function setWrongHasMore(hasMore: boolean): void {
    wrongHasMore.value = hasMore;
  }

  function clearWrongRecords(): void {
    wrongRecords.value = [];
    wrongRecordTotal.value = 0;
    selectedRecordIds.value = [];
    wrongFilters.value = {};
    wrongPage.value = 1;
    wrongHasMore.value = true;
  }

  function resetWrongBookState(): void {
    clearWrongRecords();
  }

  function resetReportState(): void {
    clearReport();
    clearWrongRecords();
  }

  return {
    currentReport,
    masteryOverview,
    weakPoints,
    wrongRecords,
    wrongBookList,
    wrongRecordTotal,
    selectedRecordIds,
    wrongFilters,
    wrongPage,
    wrongPageSize,
    wrongHasMore,
    currentReportId,
    overallMasteryRate,
    weakPointCount,
    selectedRecordCount,
    masteryTier,
    setReport,
    setReportSummary,
    setMasteryOverview,
    setWeakPoints,
    clearReport,
    resetReportState,
    setWrongRecords,
    setWrongBookList,
    appendWrongRecords,
    updateWrongRecordMastered,
    toggleSelectRecord,
    selectAllRecords,
    clearSelectedRecords,
    setWrongFilters,
    setWrongPage,
    setWrongHasMore,
    clearWrongRecords,
    resetWrongBookState,
  };
});

export default useReportStore;
