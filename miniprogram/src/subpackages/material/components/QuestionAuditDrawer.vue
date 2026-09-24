<template>
  <view v-if="isOpen" class="drawer-mask" @tap="handleClose">
    <view class="drawer-body" @tap.stop>
      <view class="drawer-header">
        <text class="drawer-title">题目修改审计记录</text>
        <text class="close-btn" @tap="handleClose">关闭</text>
      </view>

      <view class="drawer-content">
        <view v-if="loading" class="state-container">
          <text class="state-text">正在加载审计时间线...</text>
        </view>

        <view v-else-if="auditLogs.length === 0" class="state-container">
          <text class="state-text">暂无修改审计记录</text>
        </view>

        <view v-else class="timeline-list">
          <view v-for="log in auditLogs" :key="log.id" class="timeline-item">
            <view class="timeline-node">
              <view class="node-dot" />
              <view class="node-line" />
            </view>

            <view class="log-card">
              <view class="log-header">
                <text class="action-badge" :class="getActionClass(log.action)">
                  {{ formatAction(log.action) }}
                </text>
                <text class="log-time">{{ formatTime(log.created_at) }}</text>
              </view>

              <view v-if="log.reason" class="reason-section">
                <text class="reason-label">修改原因：</text>
                <text class="reason-content">{{ log.reason }}</text>
              </view>

              <view
                v-if="log.changed_fields && log.changed_fields.length > 0"
                class="fields-section"
              >
                <text class="fields-label">变更字段：</text>
                <text class="fields-tag">
                  {{ log.changed_fields.join('、') }}
                </text>
              </view>

              <!-- 修改前后对比视图 -->
              <view v-if="hasDiff(log)" class="diff-comparison">
                <view v-if="hasField(log.before_payload)" class="diff-block before-block">
                  <text class="diff-badge">修改前</text>
                  <text class="diff-text">{{ formatPayload(log.before_payload) }}</text>
                </view>
                <view v-if="hasField(log.after_payload)" class="diff-block after-block">
                  <text class="diff-badge">修改后</text>
                  <text class="diff-text">{{ formatPayload(log.after_payload) }}</text>
                </view>
              </view>
            </view>
          </view>
        </view>
      </view>

      <view class="drawer-footer">
        <button class="close-action-btn" @tap="handleClose">完成查看</button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import type { QuestionAuditItem } from '@/types/question';
import { fetchQuestionAuditLogs } from '@/api/question';

interface Props {
  visible?: boolean;
  modelValue?: boolean;
  questionId?: string;
}

interface Emits {
  (e: 'update:visible', val: boolean): void;
  (e: 'update:modelValue', val: boolean): void;
  (e: 'close'): void;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  modelValue: false,
  questionId: '',
});

const emit = defineEmits<Emits>();

const isOpen = computed(() => props.visible || props.modelValue);
const loading = ref<boolean>(false);
const auditLogs = ref<QuestionAuditItem[]>([]);

watch(
  () => [props.questionId, isOpen.value] as const,
  ([qid, open]) => {
    if (open && qid) {
      void loadAuditLogs(qid);
    }
  },
  { immediate: true },
);

async function loadAuditLogs(id: string): Promise<void> {
  if (!id) return;
  loading.value = true;
  try {
    const res = await fetchQuestionAuditLogs(id);
    auditLogs.value = res.data?.logs || [];
  } catch {
    uni.showToast({ title: '加载审计日志失败', icon: 'none' });
  } finally {
    loading.value = false;
  }
}

function handleClose(): void {
  emit('update:visible', false);
  emit('update:modelValue', false);
  emit('close');
}

function formatAction(action: string): string {
  switch (action) {
    case 'CREATE':
      return '生成入库';
    case 'EDIT':
      return '人工编辑';
    case 'DELETE':
      return '标记删除';
    case 'REGENERATE':
      return '重新抽选';
    default:
      return action;
  }
}

function getActionClass(action: string): string {
  switch (action) {
    case 'CREATE':
      return 'action-create';
    case 'EDIT':
      return 'action-edit';
    case 'DELETE':
      return 'action-delete';
    default:
      return 'action-default';
  }
}

function formatTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch {
    return iso;
  }
}

function hasField(payload?: Record<string, unknown>): boolean {
  return Boolean(payload && Object.keys(payload).length > 0);
}

function hasDiff(log: QuestionAuditItem): boolean {
  return hasField(log.before_payload) || hasField(log.after_payload);
}

function formatPayload(payload?: Record<string, unknown>): string {
  if (!payload) return '';
  if (typeof payload.stem === 'string') {
    return `题干: ${payload.stem}`;
  }
  if (typeof payload.answer === 'string') {
    return `答案: ${payload.answer}`;
  }
  return JSON.stringify(payload);
}
</script>

<style lang="scss" scoped>
@import './QuestionAuditDrawer.scss';
</style>
