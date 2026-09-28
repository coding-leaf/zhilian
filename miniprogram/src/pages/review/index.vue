<template>
  <view class="review-page">
    <!-- 顶部学情掌握度总览 (含攻克进度环) -->
    <view class="overview-section">
      <view class="overview-header">
        <text class="section-title">学情与掌握度</text>
        <text class="refresh-btn" @tap="loadData">刷新数据</text>
      </view>

      <view class="mastery-summary-card">
        <view class="mastery-rate-col">
          <view
            class="progress-ring-box"
            :style="{
              background: `conic-gradient(#2563EB ${masteryRateDisplay * 3.6}deg, #F1F5F9 ${masteryRateDisplay * 3.6}deg)`,
            }"
          >
            <view class="ring-inner">
              <text class="rate-value">{{ masteryRateDisplay }}%</text>
              <text class="rate-label">总体掌握</text>
            </view>
          </view>
        </view>

        <view class="mastery-stats-col">
          <view class="stat-item">
            <text class="stat-num text-success">{{ masteryCounts.mastered }}</text>
            <text class="stat-text">已掌握</text>
          </view>
          <view class="stat-item">
            <text class="stat-num text-warning">{{ masteryCounts.weak }}</text>
            <text class="stat-text">薄弱考点</text>
          </view>
          <view class="stat-item">
            <text class="stat-num text-muted">{{ masteryCounts.unlearned }}</text>
            <text class="stat-text">待学习</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 错题攻克看板与多维筛选 (J7) -->
    <view class="wrong-book-section">
      <view class="section-header">
        <view class="tab-group">
          <view
            class="tab-item"
            :class="{ active: currentTab === 'unmastered' }"
            @tap="switchTab('unmastered')"
          >
            <text class="tab-title">待攻克错题</text>
            <text class="badge">{{ unmasteredList.length }}</text>
          </view>
          <view
            class="tab-item"
            :class="{ active: currentTab === 'mastered' }"
            @tap="switchTab('mastered')"
          >
            <text class="tab-title">已攻克归档</text>
            <text class="badge">{{ masteredList.length }}</text>
          </view>
        </view>

        <view
          v-if="currentTab === 'unmastered' && filteredActiveList.length > 0"
          class="batch-toggle"
        >
          <text class="toggle-text" @tap="toggleSelectMode">
            {{ isSelectMode ? '取消勾选' : '多选组卷' }}
          </text>
        </view>
      </view>

      <!-- 多维筛选控制条 -->
      <view class="filter-bar">
        <view class="filter-row">
          <view
            class="filter-pill"
            :class="{ active: selectedType === 'all' }"
            @tap="selectedType = 'all'"
          >
            全部题型
          </view>
          <view
            class="filter-pill"
            :class="{ active: selectedType === 'single_choice' }"
            @tap="selectedType = 'single_choice'"
          >
            单选题
          </view>
          <view
            class="filter-pill"
            :class="{ active: selectedType === 'multiple_choice' }"
            @tap="selectedType = 'multiple_choice'"
          >
            多选题
          </view>
          <view
            class="filter-pill"
            :class="{ active: selectedType === 'short_answer' }"
            @tap="selectedType = 'short_answer'"
          >
            简答题
          </view>
        </view>

        <view class="filter-row">
          <view
            class="filter-pill"
            :class="{ active: selectedTime === 'all' }"
            @tap="selectedTime = 'all'"
          >
            全部时间
          </view>
          <view
            class="filter-pill"
            :class="{ active: selectedTime === '7d' }"
            @tap="selectedTime = '7d'"
          >
            近7天
          </view>
          <view
            class="filter-pill"
            :class="{ active: selectedTime === '30d' }"
            @tap="selectedTime = '30d'"
          >
            近30天
          </view>
          <view
            v-for="folder in folderStore.folders"
            :key="folder.id"
            class="filter-pill"
            :class="{ active: selectedCourse === folder.name }"
            @tap="selectedCourse = selectedCourse === folder.name ? 'all' : folder.name"
          >
            {{ folder.name }}
          </view>
        </view>
      </view>

      <!-- 错题列表 -->
      <view v-if="loading" class="loading-state">
        <wd-skeleton theme="paragraph" />
      </view>

      <view v-else-if="filteredActiveList.length === 0" class="empty-state">
        <text class="empty-text">
          {{ currentTab === 'unmastered' ? '暂无符合条件的待攻克错题' : '暂无已攻克错题记录' }}
        </text>
      </view>

      <view v-else class="record-list">
        <view
          v-for="record in filteredActiveList"
          :key="record.id"
          class="wrong-record-card"
          :class="{ selected: selectedRecordIds.has(record.id) }"
          @tap="handleCardTap(record)"
        >
          <view class="card-top-row">
            <view class="tag-group">
              <text class="type-tag">{{
                formatQuestionType(record.question_snapshot?.question_type as string | undefined)
              }}</text>
              <text v-if="record.course_name" class="course-tag">{{ record.course_name }}</text>
            </view>
            <view v-if="isSelectMode && currentTab === 'unmastered'" class="checkbox-col">
              <view class="checkbox" :class="{ checked: selectedRecordIds.has(record.id) }" />
            </view>
          </view>

          <text class="stem-text">{{ record.question_snapshot?.stem || '未知题干' }}</text>

          <view class="answer-compare">
            <view class="compare-row wrong-row">
              <text class="compare-label">学生作答：</text>
              <text class="compare-content">{{
                formatAnswer(record.last_user_answer) || '未作答'
              }}</text>
            </view>
            <view class="compare-row correct-row">
              <text class="compare-label">标准答案：</text>
              <text class="compare-content">{{
                formatAnswer(record.question_snapshot?.answer)
              }}</text>
            </view>
          </view>

          <view v-if="record.question_snapshot?.analysis" class="analysis-box">
            <text class="analysis-label">题目解析：</text>
            <text class="analysis-content">{{ record.question_snapshot.analysis }}</text>
          </view>

          <view class="card-action-row">
            <text class="action-time">记录时间: {{ formatTime(record.updated_at) }}</text>
            <view class="card-actions-right">
              <button
                v-if="record.question_id"
                class="btn-practice-single"
                @tap.stop="handlePracticeSingle(record)"
              >
                温习重练
              </button>
              <button
                class="btn-toggle-mastery"
                :class="{ 'btn-revert': record.is_mastered }"
                @tap.stop="handleToggleMastery(record)"
              >
                {{ record.is_mastered ? '移至未攻克' : '标记已掌握' }}
              </button>
            </view>
          </view>
        </view>
      </view>
    </view>

    <!-- 底部悬浮组卷购物车栏 -->
    <view
      v-if="isSelectMode && currentTab === 'unmastered' && filteredActiveList.length > 0"
      class="floating-batch-bar"
    >
      <view class="batch-info">
        <text class="select-count">已勾选 {{ selectedQuestionIds.length }} 题</text>
        <text class="select-all-btn" @tap="handleToggleSelectAll">
          {{ selectedQuestionIds.length === filteredActiveList.length ? '取消全选' : '全选' }}
        </text>
      </view>
      <button
        class="btn-create-practice"
        :disabled="selectedQuestionIds.length === 0 || creatingPractice"
        @tap="handleCreatePracticeFromSelection"
      >
        {{ creatingPractice ? '组卷中...' : '一键针对性重练' }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { onShow } from '@dcloudio/uni-app';
import { fetchMasteryOverview, fetchWrongBook, toggleWrongRecordResolved } from '@/api/diagnosis';
import { createPractice } from '@/api/practice';
import { useFolderStore } from '@/stores/folderStore';
import type { WrongRecordItem } from '@/types/report';

const folderStore = useFolderStore();

const loading = ref(false);
const creatingPractice = ref(false);
const currentTab = ref<'unmastered' | 'mastered'>('unmastered');
const isSelectMode = ref(false);
const selectedRecordIds = ref<Set<string>>(new Set());

const selectedType = ref<string>('all');
const selectedTime = ref<string>('all');
const selectedCourse = ref<string>('all');

const masteryRate = ref(0);
const masteryCounts = ref({
  mastered: 0,
  weak: 0,
  unlearned: 0,
});

const wrongRecords = ref<WrongRecordItem[]>([]);

const masteryRateDisplay = computed(() => {
  return Math.round(masteryRate.value * 100);
});

const unmasteredList = computed(() => {
  return wrongRecords.value.filter((r) => !r.is_mastered);
});

const masteredList = computed(() => {
  return wrongRecords.value.filter((r) => r.is_mastered);
});

const activeList = computed(() => {
  return currentTab.value === 'unmastered' ? unmasteredList.value : masteredList.value;
});

const filteredActiveList = computed(() => {
  let list = activeList.value;

  if (selectedType.value !== 'all') {
    list = list.filter((r) => {
      const qType = (r.question_snapshot?.question_type as string) || r.question_type;
      return qType === selectedType.value;
    });
  }

  if (selectedCourse.value !== 'all') {
    list = list.filter((r) => r.course_name === selectedCourse.value);
  }

  if (selectedTime.value !== 'all') {
    const now = Date.now();
    const days = selectedTime.value === '7d' ? 7 : 30;
    const threshold = now - days * 24 * 60 * 60 * 1000;
    list = list.filter((r) => {
      const timeStr = (r.updated_at || r.created_at) as string;
      return timeStr ? new Date(timeStr).getTime() >= threshold : true;
    });
  }

  return list;
});

const selectedQuestionIds = computed(() => {
  const ids: string[] = [];
  for (const record of filteredActiveList.value) {
    if (selectedRecordIds.value.has(record.id) && record.question_id) {
      ids.push(record.question_id);
    }
  }
  return ids;
});

function switchTab(tab: 'unmastered' | 'mastered'): void {
  currentTab.value = tab;
  selectedRecordIds.value.clear();
  if (tab === 'mastered') {
    isSelectMode.value = false;
  }
}

function toggleSelectMode(): void {
  isSelectMode.value = !isSelectMode.value;
  selectedRecordIds.value.clear();
}

function handleCardTap(record: WrongRecordItem): void {
  if (!isSelectMode.value || currentTab.value !== 'unmastered') {
    return;
  }
  const nextSet = new Set(selectedRecordIds.value);
  if (nextSet.has(record.id)) {
    nextSet.delete(record.id);
  } else {
    nextSet.add(record.id);
  }
  selectedRecordIds.value = nextSet;
}

function handleToggleSelectAll(): void {
  if (selectedRecordIds.value.size === filteredActiveList.value.length) {
    selectedRecordIds.value = new Set();
  } else {
    selectedRecordIds.value = new Set(filteredActiveList.value.map((r) => r.id));
  }
}

async function handleToggleMastery(record: WrongRecordItem): Promise<void> {
  const nextState = !record.is_mastered;
  try {
    const res = await toggleWrongRecordResolved(record.id, nextState);
    if (res.code === 0 || res.code === 200) {
      record.is_mastered = nextState;
      uni.showToast({
        title: nextState ? '已归档至已掌握' : '已移回待攻克',
        icon: 'success',
      });
    }
  } catch (error) {
    uni.showToast({
      title: '更新状态失败',
      icon: 'none',
    });
  }
}

async function handlePracticeSingle(record: WrongRecordItem): Promise<void> {
  if (!record.question_id) return;
  try {
    uni.showLoading({ title: '正在准备试卷...' });
    const res = await createPractice({
      title: '错题单题温习',
      question_ids: [record.question_id],
      source_type: 'wrong_record',
      mode: 'sequential',
    });
    uni.hideLoading();
    if (res.data?.id) {
      uni.navigateTo({
        url: `/subpackages/practice/pages/session/index?id=${res.data.id}`,
      });
    }
  } catch {
    uni.hideLoading();
    uni.showToast({ title: '准备练习失败', icon: 'none' });
  }
}

async function handleCreatePracticeFromSelection(): Promise<void> {
  if (selectedQuestionIds.value.length === 0) {
    uni.showToast({
      title: '请至少选择一道错题',
      icon: 'none',
    });
    return;
  }

  creatingPractice.value = true;
  try {
    const res = await createPractice({
      title: `错题针对性重练 (${selectedQuestionIds.value.length}题)`,
      question_ids: selectedQuestionIds.value,
      source_type: 'wrong_record',
      mode: 'sequential',
    });

    if (res.data?.id) {
      uni.showToast({
        title: '组卷成功，正在进入作答',
        icon: 'success',
      });
      setTimeout(() => {
        uni.navigateTo({
          url: `/subpackages/practice/pages/session/index?id=${res.data.id}`,
        });
      }, 500);
    }
  } catch (error) {
    uni.showToast({
      title: '组卷重练失败，请稍后重试',
      icon: 'none',
    });
  } finally {
    creatingPractice.value = false;
  }
}

async function loadData(): Promise<void> {
  loading.value = true;
  try {
    const [overviewRes, wrongRes] = await Promise.all([
      fetchMasteryOverview().catch(() => null),
      fetchWrongBook({ page_size: 50 }).catch(() => null),
    ]);

    if (overviewRes && overviewRes.data) {
      masteryRate.value = overviewRes.data.overall_mastery_score || 0;
      masteryCounts.value = {
        mastered: overviewRes.data.mastered_count || 0,
        weak: overviewRes.data.weak_count || 0,
        unlearned: overviewRes.data.unlearned_count || 0,
      };
    }

    if (wrongRes && wrongRes.data) {
      wrongRecords.value = wrongRes.data.items || [];
    }
  } finally {
    loading.value = false;
  }
}

function formatQuestionType(type?: string): string {
  switch (type) {
    case 'single_choice':
      return '单选题';
    case 'multiple_choice':
      return '多选题';
    case 'short_answer':
      return '简答题';
    case 'true_false':
      return '判断题';
    default:
      return '题目';
  }
}

function formatAnswer(val: unknown): string {
  if (val === null || val === undefined) return '';
  if (Array.isArray(val)) return val.join(', ');
  return String(val);
}

function formatTime(isoStr?: unknown): string {
  if (!isoStr || typeof isoStr !== 'string') return '';
  const date = new Date(isoStr);
  const m = (date.getMonth() + 1).toString().padStart(2, '0');
  const d = date.getDate().toString().padStart(2, '0');
  const h = date.getHours().toString().padStart(2, '0');
  const min = date.getMinutes().toString().padStart(2, '0');
  return `${m}-${d} ${h}:${min}`;
}

onMounted(() => {
  loadData();
});

onShow(() => {
  loadData();
});
</script>

<style lang="scss" scoped src="./review.scss"></style>
