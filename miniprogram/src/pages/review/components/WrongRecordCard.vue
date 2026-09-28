<template>
  <view class="paper-card wrong-item-card">
    <view class="item-header">
      <view class="kp-tag">
        <text class="kp-text">{{ knowledgePointLabel }}</text>
      </view>
      <view :class="['mastered-badge', record.is_mastered ? 'is-mastered' : 'unmastered']">
        {{ record.is_mastered ? '已攻克' : '待巩固' }}
      </view>
    </view>

    <text class="item-stem">{{ stem }}</text>

    <view class="item-footer">
      <text class="item-date">记录于：{{ record.created_at?.slice(0, 10) || '近期' }}</text>
      <button
        v-if="record.knowledge_point_id"
        class="single-gen-btn"
        @tap="emit('practice', record)"
      >
        针对本考点出题
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WrongRecordItem } from '@/types'
import { wrongSnapshotStem, wrongSnapshotType } from '@/api/adapters/wrong'
import { questionTypeLabel } from '@/api'

const props = defineProps<{ record: WrongRecordItem }>()

const emit = defineEmits<{
  (e: 'practice', record: WrongRecordItem): void
}>()

const stem = computed(() => wrongSnapshotStem(props.record))

const knowledgePointLabel = computed(() => {
  const type = wrongSnapshotType(props.record)
  return type ? questionTypeLabel(type) : '错题记录'
})
</script>

<style lang="scss" scoped>
@import '../review.scss';
</style>
