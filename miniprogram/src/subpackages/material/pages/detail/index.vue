<template>
  <view class="material-detail-page">
    <view v-if="loading && !detail" class="loading-state">
      <text class="loading-text">正在加载资料详情...</text>
    </view>

    <view v-else-if="detail" class="detail-container">
      <!-- 异常页告警横幅 -->
      <view v-if="isRetakeRequired" class="retake-banner">
        <view class="banner-content">
          <text class="banner-title">检测到部分页面文字模糊或存在缺陷</text>
          <text class="banner-desc">需要重新拍摄不合格页面以继续解析</text>
        </view>
        <button class="banner-btn" @tap="handleOpenRetakeDrawer">查看待重新拍摄页</button>
      </view>

      <!-- 资料基础信息卡片 -->
      <view class="info-card">
        <view class="card-header">
          <view class="format-badge">{{ formatLabel }}</view>
          <view class="title-wrap">
            <text class="detail-title">{{ detail.title }}</text>
          </view>
          <view :class="['status-capsule', 'status--' + statusTag.type]">
            {{ statusTag.text }}
          </view>
        </view>

        <view class="meta-grid">
          <view class="meta-item">
            <text class="meta-label">文件格式</text>
            <text class="meta-val">{{ formatLabel }}</text>
          </view>
          <view class="meta-item">
            <text class="meta-label">文件体积</text>
            <text class="meta-val">{{ formattedSize }}</text>
          </view>
          <view class="meta-item">
            <text class="meta-label">版本数量</text>
            <text class="meta-val">{{ detail.versions_count || 1 }} 个版本</text>
          </view>
          <view class="meta-item">
            <text class="meta-label">创建时间</text>
            <text class="meta-val">{{ formattedDate }}</text>
          </view>
        </view>
      </view>

      <!-- 考点与解析状态卡片 -->
      <view class="section-card">
        <view class="section-header">
          <text class="section-title">考点与解析概要</text>
          <text v-if="isPolling" class="polling-hint">正在实时同步最新状态...</text>
        </view>

        <view class="section-body">
          <view v-if="isParsing" class="parsing-tip-box">
            <text class="parsing-title">正在智能提取考点大纲</text>
            <text class="parsing-sub">系统正在进行切片向量化与考点质检，通常需要几秒钟...</text>
          </view>
          <view v-else-if="isReady" class="ready-box">
            <text class="ready-title">考点解析已完成</text>
            <text class="ready-sub">已生成知识点大纲树与练习索引</text>
          </view>
          <view v-else-if="isFailed" class="failed-box">
            <text class="failed-title">资料解析遇到异常</text>
            <text class="failed-sub"
              >解析过程意外中断或解析质量未达标，可点击下方按钮发起就地重试</text
            >
          </view>
          <view v-else-if="isRetakeRequired" class="warning-box">
            <text class="warning-title">等待重新拍摄</text>
            <text class="warning-sub"
              >有 {{ unqualifiedPages.length }} 个页面需要重拍，请尽快处理</text
            >
          </view>
          <view v-else class="normal-box">
            <text class="normal-sub">资料当前处于初始准备阶段</text>
          </view>
        </view>

        <view class="section-footer">
          <button
            v-if="isFailed"
            class="action-btn retry-action-btn"
            :loading="isRetrying"
            :disabled="isRetrying"
            @tap="handleRetryPipeline"
          >
            重试解析
          </button>
          <button
            v-else
            class="action-btn"
            :class="{ disabled: !isReady }"
            :disabled="!isReady"
            @tap="handleNavigateKnowledgeTree"
          >
            查看考点知识树
          </button>
        </view>
      </view>
    </view>

    <!-- 重拍抽屉组件 -->
    <RetakeDrawer
      v-model="isRetakeDrawerVisible"
      :material-id="targetId"
      :pages="unqualifiedPages"
      @retake-success="handleRetakeSuccess"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { onLoad } from '@dcloudio/uni-app';
import { useMaterialStore } from '@/stores/materialStore';
import { fetchMaterialDetail, retryMaterial } from '@/api/material';
import { resolveMaterialStatusTag } from '@/subpackages/material/utils/copywriting';
import { useMaterialPolling } from '../../composables/useMaterialPolling';
import RetakeDrawer from '../../components/RetakeDrawer.vue';
import type { MaterialItem, PageOCRStatus } from '@/types/material';

interface Props {
  id?: string;
}

const props = defineProps<Props>();
const materialStore = useMaterialStore();
const targetId = ref<string>(props.id || '');
const detail = ref<MaterialItem | null>(null);
const loading = ref<boolean>(false);
const isRetakeDrawerVisible = ref<boolean>(false);
const unqualifiedPages = ref<PageOCRStatus[]>([]);

const { isPolling, startPolling, stopPolling } = useMaterialPolling(targetId, {
  onStatusChange: (status) => {
    if (detail.value) {
      detail.value.status = status;
      materialStore.updateMaterialStatus(detail.value.id, status);
    }
  },
  onComplete: (data) => {
    detail.value = data;
    materialStore.addMaterial(data);
  },
});

const isParsing = computed(() => {
  const s = String(detail.value?.status || '').toUpperCase();
  return s === 'PARSING' || s === 'PENDING';
});

const isReady = computed(() => {
  const s = String(detail.value?.status || '').toUpperCase();
  return s === 'READY' || s === 'COMPLETED';
});

const isFailed = computed(() => {
  const s = String(detail.value?.status || '').toUpperCase();
  return s === 'FAILED';
});

const isRetakeRequired = computed(() => {
  const s = String(detail.value?.status || '').toUpperCase();
  return s === 'RETAKE_REQUIRED' || unqualifiedPages.value.length > 0;
});

const formatLabel = computed(() => (detail.value?.file_format || 'DOC').toUpperCase());

const formattedSize = computed(() => {
  const bytes = detail.value?.file_size || 0;
  if (bytes < 1024) return `${bytes} B`;
  const isKb = bytes < 1048576;
  return `${(bytes / (isKb ? 1024 : 1048576)).toFixed(1)} ${isKb ? 'KB' : 'MB'}`;
});

const formattedDate = computed(() => {
  const d = new Date(detail.value?.created_at || '');
  if (Number.isNaN(d.getTime())) return detail.value?.created_at || '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
});

const statusTag = computed(() => {
  if (!detail.value) return { text: '未知', type: 'info' as const };
  return resolveMaterialStatusTag(detail.value.status);
});

async function loadDetail(): Promise<void> {
  if (!targetId.value) return;
  loading.value = true;
  try {
    const res = await fetchMaterialDetail(targetId.value);
    if (res && res.data) {
      detail.value = res.data;
      materialStore.setActiveMaterial(res.data.id, res.data.current_version_id || null);

      const statusUpper = String(res.data.status || '').toUpperCase();
      if (statusUpper === 'RETAKE_REQUIRED' && unqualifiedPages.value.length === 0) {
        unqualifiedPages.value = [
          {
            page_no: 1,
            is_qualified: false,
            issue_type: 'blur',
            issue_description: '文字模糊，需重新拍摄',
            retake_count: 0,
            max_retakes: 3,
          },
        ];
      }

      if (statusUpper === 'PARSING' || statusUpper === 'PENDING') {
        startPolling();
      }
    }
  } catch (err: unknown) {
    uni.showToast({ title: '加载详情失败', icon: 'none' });
  } finally {
    loading.value = false;
  }
}

function handleOpenRetakeDrawer(): void {
  isRetakeDrawerVisible.value = true;
}

function handleRetakeSuccess(payload: { page_no: number; data?: unknown }): void {
  uni.showToast({ title: '重拍提交成功', icon: 'none' });
  unqualifiedPages.value = unqualifiedPages.value.filter((p) => p.page_no !== payload.page_no);
  isRetakeDrawerVisible.value = false;
  startPolling();
  void loadDetail();
}

function handleNavigateKnowledgeTree(): void {
  if (!isReady.value) return;
  uni.navigateTo({
    url: `/subpackages/material/pages/knowledge-tree/index?material_id=${targetId.value}`,
    fail: () => {
      uni.showToast({ title: '知识树功能准备中', icon: 'none' });
    },
  });
}

const isRetrying = ref(false);

async function handleRetryPipeline(): Promise<void> {
  if (isRetrying.value || !targetId.value) return;
  isRetrying.value = true;
  try {
    const res = await retryMaterial(targetId.value);
    if (res && res.data) {
      detail.value = res.data;
      materialStore.updateMaterialStatus(res.data.id, res.data.status);
    }
    uni.showToast({ title: '已重新发起解析', icon: 'success' });
    startPolling();
    void loadDetail();
  } catch {
    uni.showToast({ title: '发起重试失败，请重试', icon: 'none' });
  } finally {
    isRetrying.value = false;
  }
}

onLoad((query?: Record<string, string | undefined>) => {
  if (query?.id) {
    targetId.value = query.id;
  }
});

onMounted(() => {
  if (targetId.value) {
    void loadDetail();
  }
});

defineExpose({
  targetId,
  detail,
  isRetakeDrawerVisible,
  unqualifiedPages,
  isPolling,
  isFailed,
  isRetrying,
  loadDetail,
  startPolling,
  stopPolling,
  handleOpenRetakeDrawer,
  handleRetakeSuccess,
  handleNavigateKnowledgeTree,
  handleRetryPipeline,
});
</script>

<style lang="scss" scoped src="./detail.scss"></style>
