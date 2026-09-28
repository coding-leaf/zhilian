<template>
  <view class="coach-section">
    <view class="coach-header">
      <view class="coach-title-group">
        <text class="coach-badge">AI 助教</text>
        <text class="coach-title">深度答疑追问</text>
      </view>
    </view>

    <!-- 快捷提问 chips -->
    <view class="coach-prompt-chips">
      <text
        v-for="(tip, idx) in defaultPromptTips"
        :key="idx"
        class="prompt-chip"
        @tap="handleSelectPromptTip(tip)"
      >
        {{ tip }}
      </text>
    </view>

    <!-- 输入追问 -->
    <view class="coach-input-box">
      <input
        v-model="coachPrompt"
        class="coach-input"
        placeholder="针对这道题输入您的困惑..."
        :disabled="isAskingCoach"
        @confirm="handleAskCoach"
      />
      <view
        class="coach-send-btn"
        :class="{ disabled: !coachPrompt.trim() || isAskingCoach }"
        @tap="handleAskCoach"
      >
        <text>{{ isAskingCoach ? '解答中' : '追问' }}</text>
      </view>
    </view>

    <!-- 助教回复展示 -->
    <view v-if="coachReply" class="coach-reply-box">
      <text class="reply-text">{{ coachReply }}</text>
      <view v-if="coachSuggestions.length > 0" class="suggestions-list">
        <text class="sug-title">延伸思考：</text>
        <text
          v-for="(sug, sidx) in coachSuggestions"
          :key="sidx"
          class="sug-chip"
          @tap="handleSelectPromptTip(sug)"
        >
          {{ sug }}
        </text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * AICoachCard.vue
 * Dedicated AI coach question follow-up card.
 * Zero-Emoji Policy enforced. Lines strictly <= 300.
 */

import { ref } from 'vue';
import { askCoach } from '@/api/question';

interface Props {
  questionId: string;
  userAnswer?: string;
  gradingPoints?: string[];
}

const props = withDefaults(defineProps<Props>(), {
  questionId: '',
  userAnswer: '',
  gradingPoints: () => [],
});

const defaultPromptTips = [
  '为什么我的答案遗漏了采分点？',
  '请用生动的通俗比喻解释本题核心概念',
  '这道题在考试中最常见的易错陷阱是什么？',
];

const coachPrompt = ref<string>('');
const isAskingCoach = ref<boolean>(false);
const coachReply = ref<string>('');
const coachSuggestions = ref<string[]>([]);

function handleSelectPromptTip(tip: string): void {
  coachPrompt.value = tip;
  void handleAskCoach();
}

async function handleAskCoach(): Promise<void> {
  const prompt = coachPrompt.value.trim();
  const qid = props.questionId;
  if (!prompt || !qid || isAskingCoach.value) return;

  isAskingCoach.value = true;
  try {
    const res = await askCoach(qid, {
      user_prompt: prompt,
      user_answer: props.userAnswer,
      grading_points: props.gradingPoints,
    });
    if (res.code === 0 && res.data) {
      coachReply.value = res.data.reply;
      coachSuggestions.value = res.data.suggestions || [];
    }
  } catch {
    uni.showToast({ title: 'AI 助教思考超时，请重试', icon: 'none' });
  } finally {
    isAskingCoach.value = false;
  }
}
</script>

<style lang="scss" scoped>
@import '@/uni.scss';

.coach-section {
  background: linear-gradient(135deg, #eff6ff 0%, #ffffff 100%);
  border: 1px solid #bfdbfe;
  border-radius: $radius-lg;
  padding: 28rpx;
  box-shadow: $shadow-card;
  margin-bottom: 24rpx;

  .coach-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16rpx;

    .coach-title-group {
      display: flex;
      align-items: center;
      gap: 12rpx;

      .coach-badge {
        font-size: 20rpx;
        padding: 4rpx 10rpx;
        background-color: $color-primary;
        color: #ffffff;
        border-radius: $radius-xs;
        font-weight: $font-weight-bold;
      }

      .coach-title {
        font-size: 30rpx;
        font-weight: $font-weight-bold;
        color: $color-text-main;
      }
    }
  }

  .coach-prompt-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
    margin-bottom: 18rpx;

    .prompt-chip {
      font-size: 22rpx;
      padding: 8rpx 18rpx;
      border-radius: $radius-pill;
      background-color: #ffffff;
      border: 1px solid #dbeafe;
      color: $color-primary;
    }
  }

  .coach-input-box {
    display: flex;
    gap: 14rpx;
    align-items: center;

    .coach-input {
      flex: 1;
      height: 76rpx;
      background-color: #ffffff;
      border: 1px solid #cbd5e1;
      border-radius: $radius-pill;
      padding: 0 24rpx;
      font-size: $font-size-body;
    }

    .coach-send-btn {
      height: 76rpx;
      padding: 0 32rpx;
      border-radius: $radius-pill;
      background-color: $color-primary;
      color: #ffffff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: $font-size-secondary;
      font-weight: $font-weight-medium;

      &.disabled {
        opacity: 0.5;
      }
    }
  }

  .coach-reply-box {
    margin-top: 24rpx;
    padding: 20rpx;
    border-radius: $radius-md;
    background-color: #ffffff;
    border: 1px solid #e2e8f0;

    .reply-text {
      font-size: $font-size-body;
      line-height: 1.65;
      color: $color-text-main;
    }

    .suggestions-list {
      margin-top: 16rpx;
      padding-top: 14rpx;
      border-top: 1px dashed #e2e8f0;

      .sug-title {
        font-size: 22rpx;
        color: $color-text-muted;
        margin-bottom: 8rpx;
        display: block;
      }

      .sug-chip {
        font-size: 22rpx;
        color: $color-primary;
        margin-right: 12rpx;
        display: inline-block;
        padding: 4rpx 12rpx;
        background-color: #f1f5f9;
        border-radius: $radius-pill;
      }
    }
  }
}
</style>
