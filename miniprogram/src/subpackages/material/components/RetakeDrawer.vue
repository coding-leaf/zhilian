<template>
  <view v-if="isOpen" class="drawer-mask" @tap="handleClose">
    <view class="drawer-body" @tap.stop>
      <view class="drawer-header">
        <text class="drawer-title">单页重新拍摄</text>
        <text class="close-btn" @tap="handleClose">关闭</text>
      </view>

      <view class="drawer-content">
        <view v-if="pages.length === 0" class="empty-tip"> 暂无需要重新拍摄的页面 </view>

        <view
          v-for="page in pages"
          :key="page.page_no"
          class="page-item"
          :class="{ 'item-fused': isMaxReached(page) }"
        >
          <view class="item-header">
            <text class="page-badge">第 {{ page.page_no }} 页</text>
            <text class="limit-tag" :class="isMaxReached(page) ? 'tag-danger' : 'tag-warning'">
              剩余可重拍次数: {{ getRemainingCount(page) }} 次
            </text>
          </view>

          <view class="item-body">
            <text class="issue-desc">{{ formatIssue(page) }}</text>
            <text v-if="isMaxReached(page)" class="fuse-tip">
              已达最大重拍限制，建议重新上传更清晰的原文件
            </text>
          </view>

          <view class="item-footer">
            <button
              class="retake-btn"
              :class="{
                disabled: isMaxReached(page) || submittingPageNo === page.page_no,
                loading: submittingPageNo === page.page_no,
              }"
              :disabled="isMaxReached(page) || submittingPageNo === page.page_no"
              @tap="handleRetake(page)"
            >
              <text v-if="submittingPageNo === page.page_no">提交中...</text>
              <text v-else-if="isMaxReached(page)">已达最大重拍限制</text>
              <text v-else>重新拍摄</text>
            </button>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import type { PageOCRStatus } from '@/types/material';
import { retakeMaterialPage } from '@/api/material';
import { formatOcrIssue } from '@/utils/copywriting';
import { generateIdempotencyKey } from '../utils/file';

interface Props {
  visible?: boolean;
  modelValue?: boolean;
  materialId?: string;
  pages?: PageOCRStatus[];
}

interface Emits {
  (e: 'update:visible', val: boolean): void;
  (e: 'update:modelValue', val: boolean): void;
  (e: 'close'): void;
  (e: 'retake-success', payload: { page_no: number; data?: unknown }): void;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  modelValue: false,
  materialId: '',
  pages: () => [],
});

const emit = defineEmits<Emits>();

const isOpen = computed(() => props.visible || props.modelValue);
const submittingPageNo = ref<number | null>(null);

function handleClose(): void {
  emit('update:visible', false);
  emit('update:modelValue', false);
  emit('close');
}

function isMaxReached(page: PageOCRStatus): boolean {
  const limit = page.max_retakes ?? 3;
  return (page.retake_count || 0) >= limit;
}

function getRemainingCount(page: PageOCRStatus): number {
  const limit = page.max_retakes ?? 3;
  return Math.max(0, limit - (page.retake_count || 0));
}

function formatIssue(page: PageOCRStatus): string {
  return formatOcrIssue(page.page_no, page.issue_type || '', page.issue_description || undefined);
}

function handleRetake(page: PageOCRStatus): void {
  if (isMaxReached(page) || submittingPageNo.value === page.page_no) {
    return;
  }

  uni.chooseImage({
    count: 1,
    sizeType: ['compressed', 'original'],
    sourceType: ['camera', 'album'],
    success: async (res) => {
      const paths = Array.isArray(res.tempFilePaths) ? res.tempFilePaths : [res.tempFilePaths];
      const filePath = paths[0];
      if (!filePath) return;
      await submitRetake(page.page_no, filePath);
    },
    fail: () => {
      // 用户取消选取无需处理
    },
  });
}

async function submitRetake(pageNo: number, filePath: string): Promise<void> {
  submittingPageNo.value = pageNo;
  try {
    const idempotencyKey = generateIdempotencyKey();
    const res = await retakeMaterialPage(props.materialId, pageNo, filePath, idempotencyKey);
    uni.showToast({ title: '重拍提交成功', icon: 'success' });
    emit('retake-success', { page_no: pageNo, data: res?.data });
  } catch {
    uni.showToast({ title: '重拍提交失败，请重试', icon: 'none' });
  } finally {
    submittingPageNo.value = null;
  }
}
</script>

<style lang="scss" scoped>
@import './RetakeDrawer.scss';
</style>
