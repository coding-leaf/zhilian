<template>
  <view v-if="isOpen" class="drawer-mask" @tap="handleClose">
    <view class="drawer-body" @tap.stop>
      <view class="drawer-header">
        <text class="drawer-title">编辑题目</text>
        <text class="close-btn" @tap="handleClose">关闭</text>
      </view>

      <view class="drawer-content">
        <!-- 题干编辑区 -->
        <view class="form-group">
          <text class="form-label">题干内容</text>
          <textarea
            v-model="stem"
            class="form-textarea"
            placeholder="请输入题目题干..."
            :maxlength="1000"
          />
        </view>

        <!-- 参考答案编辑区 -->
        <view class="form-group">
          <text class="form-label">参考答案</text>
          <textarea
            v-model="answer"
            class="form-textarea form-textarea-sm"
            placeholder="请输入参考答案..."
            :maxlength="500"
          />
        </view>

        <!-- 题目解析编辑区 -->
        <view class="form-group">
          <text class="form-label">题目解析 (选填)</text>
          <textarea
            v-model="analysis"
            class="form-textarea form-textarea-sm"
            placeholder="请输入题目深度解析..."
            :maxlength="1000"
          />
        </view>

        <!-- 修改原因输入区 (必填，至少2字符) -->
        <view class="form-group">
          <view class="label-row">
            <text class="form-label required">修改原因</text>
            <text class="form-tip">必填，至少 2 个字符以留存审计记录</text>
          </view>
          <input
            v-model="reason"
            class="form-input"
            placeholder="如：修正错别字、修正参考答案、优化表述"
            :maxlength="100"
          />
        </view>
      </view>

      <view class="drawer-footer">
        <button
          class="submit-btn"
          :class="{ disabled: submitting }"
          :disabled="submitting"
          @tap="handleSubmit"
        >
          {{ submitting ? '正在保存...' : '保存修改' }}
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import type { QuestionItem } from '@/types/question';
import { updateQuestion } from '@/api/question';

interface Props {
  visible?: boolean;
  modelValue?: boolean;
  question?: QuestionItem | null;
}

interface Emits {
  (e: 'update:visible', val: boolean): void;
  (e: 'update:modelValue', val: boolean): void;
  (e: 'close'): void;
  (e: 'updated', question: QuestionItem): void;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  modelValue: false,
  question: null,
});

const emit = defineEmits<Emits>();

const isOpen = computed(() => props.visible || props.modelValue);
const stem = ref<string>('');
const answer = ref<string>('');
const analysis = ref<string>('');
const reason = ref<string>('');
const submitting = ref<boolean>(false);

watch(
  () => [props.question, isOpen.value] as const,
  ([currentQuestion, open]) => {
    if (open && currentQuestion) {
      stem.value = currentQuestion.stem || '';
      answer.value = currentQuestion.answer || '';
      analysis.value = currentQuestion.analysis || '';
      reason.value = '';
    }
  },
  { immediate: true },
);

function handleClose(): void {
  emit('update:visible', false);
  emit('update:modelValue', false);
  emit('close');
}

async function handleSubmit(): Promise<void> {
  if (submitting.value) return;

  if (!props.question?.id) {
    uni.showToast({ title: '题目信息不完整', icon: 'none' });
    return;
  }

  const trimmedStem = stem.value.trim();
  if (!trimmedStem) {
    uni.showToast({ title: '题干内容不能为空', icon: 'none' });
    return;
  }

  const trimmedAnswer = answer.value.trim();
  if (!trimmedAnswer) {
    uni.showToast({ title: '参考答案不能为空', icon: 'none' });
    return;
  }

  const trimmedReason = reason.value.trim();
  if (!trimmedReason || trimmedReason.length < 2) {
    uni.showToast({ title: '修改原因不得少于2个字符', icon: 'none' });
    return;
  }

  submitting.value = true;
  try {
    const res = await updateQuestion(props.question.id, {
      stem: trimmedStem,
      answer: trimmedAnswer,
      analysis: analysis.value.trim(),
      reason: trimmedReason,
    });

    const updatedItem: QuestionItem = res.data || {
      ...props.question,
      stem: trimmedStem,
      answer: trimmedAnswer,
      analysis: analysis.value.trim(),
    };

    uni.showToast({ title: '修改已保存', icon: 'success' });
    emit('updated', updatedItem);
    handleClose();
  } catch {
    uni.showToast({ title: '保存修改失败，请重试', icon: 'none' });
  } finally {
    submitting.value = false;
  }
}
</script>

<style lang="scss" scoped>
@import './QuestionEditDrawer.scss';
</style>
