<template>
  <view class="paper-card wrong-item-card">
    <view class="item-header">
      <view class="item-header-left">
        <view
          v-if="!record.is_mastered"
          :class="['wrong-checkbox', selected ? 'checked' : '']"
          @tap="emit('toggle-select', record.id)"
        >
          <view v-if="selected" class="wrong-check-mark" />
        </view>
        <view class="kp-tag">
          <text class="kp-text">{{ knowledgePointLabel }}</text>
        </view>
        <text v-if="typeText" class="wrong-type-pill">{{ typeText }}</text>
      </view>
      <view :class="['mastered-badge', record.is_mastered ? 'is-mastered' : 'unmastered']">
        {{ record.is_mastered ? '已攻克' : '待巩固' }}
      </view>
    </view>

    <text v-if="record.material_title" class="wrong-material-sub">
      来源讲义：{{ record.material_title }}
    </text>

    <view class="item-stem-rich">
      <RichContent :content="stem" compact />
    </view>

    <view class="item-footer">
      <view class="item-meta-col">
        <text class="item-date">记录于：{{ record.created_at?.slice(0, 10) || '近期' }}</text>
        <text v-if="record.wrong_count && record.wrong_count > 1" class="item-wrong-count">
          累计错 {{ record.wrong_count }} 次
        </text>
      </view>
      <view class="item-actions">
        <button
          v-if="!record.is_mastered"
          class="master-btn"
          :disabled="marking"
          @tap="emit('mark-mastered', record)"
        >
          {{ marking ? '处理中...' : '标为已掌握' }}
        </button>
        <button
          v-if="record.knowledge_point_id"
          class="single-gen-btn"
          @tap="emit('practice', record)"
        >
          针对本考点出题
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RichContent from '@/components/RichContent.vue'
import type { WrongRecordItem } from '@/types'
import { wrongSnapshotStem, wrongSnapshotType } from '@/api/adapters/wrong'
import { questionTypeLabel } from '@/api'
import { wrongKnowledgePointLabel } from '../reviewView'

const props = defineProps<{
  record: WrongRecordItem
  selected?: boolean
  marking?: boolean
}>()

const emit = defineEmits<{
  (e: 'practice', record: WrongRecordItem): void
  (e: 'toggle-select', recordId: string): void
  (e: 'mark-mastered', record: WrongRecordItem): void
}>()

const stem = computed(() => wrongSnapshotStem(props.record))
const knowledgePointLabel = computed(() => wrongKnowledgePointLabel(props.record))
const typeText = computed(() => {
  const type = wrongSnapshotType(props.record)
  return type ? questionTypeLabel(type) : ''
})
</script>

<style lang="scss" scoped>
@import '../review.scss';
</style>
