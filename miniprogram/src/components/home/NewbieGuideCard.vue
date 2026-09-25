<template>
  <view v-if="visible" class="newbie-guide-card" role="region" aria-label="新手学习指南">
    <view class="guide-header">
      <text class="guide-title">新手学习指南</text>
      <text class="guide-desc">三步开启高效针对性备考</text>
    </view>

    <view class="guide-steps-list">
      <view v-for="step in steps" :key="step.number" class="step-item">
        <view class="step-badge" aria-hidden="true">
          <text class="step-num">{{ step.number }}</text>
        </view>
        <view class="step-content">
          <text class="step-title">{{ step.title }}</text>
          <text class="step-desc">{{ step.desc }}</text>
        </view>
      </view>
    </view>

    <view class="guide-action-box">
      <button class="guide-action-btn" @tap="handleStartFirst">立即体验导入资料</button>
    </view>
  </view>
</template>

<script setup lang="ts">
defineOptions({
  name: 'NewbieGuideCard',
});

interface Props {
  visible?: boolean;
}

interface Emits {
  (e: 'start-first'): void;
}

withDefaults(defineProps<Props>(), {
  visible: true,
});

const emit = defineEmits<Emits>();

interface StepItem {
  number: number;
  title: string;
  desc: string;
}

const steps: StepItem[] = [
  {
    number: 1,
    title: '导入学习资料',
    desc: '支持 PDF / Word / 照片，智能识别',
  },
  {
    number: 2,
    title: '考点智能提炼',
    desc: 'AI 结构化解析，建立专属知识图谱',
  },
  {
    number: 3,
    title: '自适应练习与诊断',
    desc: '基于薄弱点动态出题，艾宾浩斯强化',
  },
];

function handleStartFirst(): void {
  emit('start-first');
}
</script>

<style lang="scss" scoped>
@import './NewbieGuideCard.scss';
</style>
