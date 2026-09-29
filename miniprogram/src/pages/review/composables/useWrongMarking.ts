/**
 * 题库题目行「记入错题 / 取消标记」的动作编排。
 *
 * 错题列表的**事实源在页面**（`review/index.vue` 已为「错题巩固」区块拉取全量错题，
 * 并据此决定分组与举一反三范围），本 composable 只是按 `question_id` 建索引并执行动作，
 * 不自己再拉一份——同一份数据在一个页面里存两份，必然出现「题库显示已标记、错题列表
 * 里没有」这类漂移。
 *
 * 三条硬约束：
 * - **已标记必须回显**：没有回显，用户无法区分「标记没生效」与「已经标记过了」，
 *   会重复点击，而重复点击走的是 upsert 累加，`error_count` 会虚高；
 * - **请求在途禁用**：双击会打出「标记 + 取消」两次往返；
 * - **取消按来源分道**：手工记录（`practice_id == null`）删除，判题来源的记录只引导到
 *   「已掌握」，绝不删除——那是真实作答历史（见 `reviewView.resolveWrongMarkAction`）。
 */

import { computed, ref } from 'vue'
import type { ComputedRef } from 'vue'
import { apiDeleteWrongRecord, apiMarkQuestionWrong, apiMarkWrongRecordMastered } from '@/api'
import type { WrongRecordItem } from '@/types'
import { describeFailure } from '@/utils/requestError'
import { resolveWrongMarkAction, type WrongMarkAction } from '../reviewView'

export interface WrongMarking {
  /** question_id → 该题当前的错题记录（无记录即未标记）。 */
  marksById: ComputedRef<Map<string, WrongRecordItem>>
  /** 正在请求中的题目 ID，用于禁用动作位。 */
  pendingIds: ComputedRef<string[]>
  isPending: (questionId: string) => boolean
  /**
   * 切换一道题的错题标记。
   *
   * Returns:
   *   Promise<boolean>: 错题数据是否已变化（true 时调用方应重新拉取错题列表）。
   */
  toggle: (questionId: string) => Promise<boolean>
}

/** 动作成功文案，按分道结果穷尽取值（新增动作必须在这里显式表态）。 */
function successText(action: Exclude<WrongMarkAction, 'none'>): string {
  switch (action) {
    case 'mark':
      return '已记入错题本'
    case 'delete':
      return '已取消标记'
    case 'master':
      return '已标记为已掌握'
  }
}

/** 判题来源记录的「取消标记」替代路径确认：不删除，改标已掌握。 */
function confirmMasterForJudged(): Promise<boolean> {
  return new Promise((resolve) => {
    uni.showModal({
      title: '该题已有作答记录',
      content: '直接移除会销毁真实作答历史。是否改为标记「已掌握」？',
      success: (result: { confirm?: boolean }) => resolve(Boolean(result?.confirm)),
      fail: () => resolve(false),
    })
  })
}

export function useWrongMarking(records: () => WrongRecordItem[]): WrongMarking {
  const pending = ref<string[]>([])

  const marksById = computed(() => {
    const map = new Map<string, WrongRecordItem>()
    for (const record of records()) {
      if (record.question_id) map.set(record.question_id, record)
    }
    return map
  })
  const pendingIds = computed(() => pending.value)
  const isPending = (questionId: string): boolean => pending.value.includes(questionId)

  /** 执行分道后的动作；`mark` 之外的动作都需要已有记录才成立。 */
  const runAction = async (
    action: WrongMarkAction,
    questionId: string,
    record: WrongRecordItem | null,
  ): Promise<void> => {
    switch (action) {
      case 'mark':
        await apiMarkQuestionWrong(questionId)
        return
      case 'delete':
        if (record) await apiDeleteWrongRecord(record.id)
        return
      case 'master':
        if (record) await apiMarkWrongRecordMastered(record.id)
        return
      case 'none':
        return
    }
  }

  const toggle = async (questionId: string): Promise<boolean> => {
    if (isPending(questionId)) return false
    const record = marksById.value.get(questionId) ?? null
    const action = resolveWrongMarkAction(record)

    if (action === 'none') {
      uni.showToast({ title: '该错题已标记为已掌握', icon: 'none' })
      return false
    }
    // 判题来源的记录不能删：先让用户明确改走「已掌握」，取消则什么都不做。
    if (action === 'master' && !(await confirmMasterForJudged())) return false

    pending.value = [...pending.value, questionId]
    try {
      await runAction(action, questionId, record)
      uni.showToast({ title: successText(action), icon: 'none' })
      return true
    } catch (error) {
      // 失败必须可见且可重试：按钮留在原地，用户再点一次就是重试。
      console.error('Failed to update wrong mark', error)
      uni.showToast({ title: describeFailure(error, '操作失败，请重试'), icon: 'none' })
      return false
    } finally {
      pending.value = pending.value.filter((id) => id !== questionId)
    }
  }

  return { marksById, pendingIds, isPending, toggle }
}
