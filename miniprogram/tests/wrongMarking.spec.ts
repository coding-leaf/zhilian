/**
 * 题库「记入错题 / 取消标记」与手工错题进入举一反三的契约测试。
 *
 * 覆盖 PRD `09-29-manual-wrong-mark` 的前端部分：
 * - AC-8 动作分道：未标记 → 创建；手工记录 → 删除；判题记录 → 引导「已掌握」而非删除；
 *   请求在途禁用；失败可见且可重试。
 * - AC-6（**有界**）手工错题进入再生题范围：断言再生题请求的 `knowledge_point_ids`
 *   **包含**该手工错题的知识点。**不**据此断言该考点真的被练到——`regenerateFromWrongPoints`
 *   按 `question_count` 截断（PRD F8），修复属 09-29-question-bank-tab。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import { useWrongMarking } from '@/pages/review/composables/useWrongMarking'
import {
  groupKnowledgePointIds,
  resolveWrongMarkAction,
  wrongMarkLabel,
} from '@/pages/review/reviewView'
import { usePracticeStore } from '@/stores/practice'
import type { WrongRecordItem } from '@/types'

/** 手工标记记录：practice_id 为 NULL 就是「手工创建」的定义。 */
function manualRecord(overrides: Partial<WrongRecordItem> = {}): WrongRecordItem {
  return {
    id: 'w-manual',
    question_id: 'q-1',
    knowledge_point_id: 'k-manual',
    practice_id: null,
    attempt_item_id: null,
    is_mastered: false,
    question_snapshot: {
      stem: 'TCP 建立连接需要几次握手？',
      question_type: 'single_choice',
      options: [
        { key: 'A', content: '一次' },
        { key: 'B', content: '三次' },
      ],
      answer: 'B',
    },
    ...overrides,
  }
}

/** 判题写入的记录：带真实练习归属。 */
function judgedRecord(overrides: Partial<WrongRecordItem> = {}): WrongRecordItem {
  return manualRecord({
    id: 'w-judged',
    question_id: 'q-2',
    practice_id: 'p-1',
    attempt_item_id: 'a-1',
    error_type: 'conceptual',
    ...overrides,
  })
}

const calls = (url: string, method?: string) =>
  requestMock.mock.calls.filter(
    ([options]: any[]) =>
      options.url === url && (method === undefined || options.method === method),
  )

describe('wrong mark action routing', () => {
  it('routes by provenance: 未标记创建、手工删除、判题引导已掌握', () => {
    expect(resolveWrongMarkAction(null)).toBe('mark')
    expect(resolveWrongMarkAction(manualRecord())).toBe('delete')
    expect(resolveWrongMarkAction(judgedRecord())).toBe('master')
    expect(resolveWrongMarkAction(judgedRecord({ is_mastered: true }))).toBe('none')

    expect(wrongMarkLabel(null)).toBe('记入错题')
    expect(wrongMarkLabel(manualRecord())).toBe('取消标记')
    expect(wrongMarkLabel(judgedRecord())).toBe('已标记')
    expect(wrongMarkLabel(judgedRecord({ is_mastered: true }))).toBe('已掌握')
  })
})

describe('useWrongMarking', () => {
  let records: ReturnType<typeof ref<WrongRecordItem[]>>

  beforeEach(() => {
    requestMock.mockReset()
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/wrong-records' && options.method === 'POST') return manualRecord()
      if (options.url.startsWith('/wrong-records/') && options.method === 'DELETE') {
        return { id: 'w-manual', success: true, removed: true, message: '已移除' }
      }
      if (options.url.endsWith('/master')) {
        return { id: 'w-judged', is_mastered: true, mastered_at: null, message: '已掌握' }
      }
      throw new Error(`unexpected request: ${options.url}`)
    })
    records = ref<WrongRecordItem[]>([])
  })

  it('未标记题目标记成功：POST /wrong-records 只带 question_id 并回报数据已变化', async () => {
    const marking = useWrongMarking(() => records.value)

    const changed = await marking.toggle('q-1')

    expect(changed).toBe(true)
    const call = calls('/wrong-records', 'POST')[0]
    expect(call[0].data).toEqual({ question_id: 'q-1' })
    // 知识点归属由服务端解析：客户端无权指定。
    expect(call[0].data).not.toHaveProperty('knowledge_point_id')
  })

  it('手工记录取消标记走 DELETE，不动「已掌握」接口', async () => {
    records.value = [manualRecord()]
    const marking = useWrongMarking(() => records.value)

    const changed = await marking.toggle('q-1')

    expect(changed).toBe(true)
    expect(calls('/wrong-records/w-manual', 'DELETE')).toHaveLength(1)
    expect(calls('/wrong-records/w-manual/master', 'POST')).toHaveLength(0)
  })

  it('判题来源记录绝不删除：确认后改走「已掌握」', async () => {
    records.value = [judgedRecord()]
    const marking = useWrongMarking(() => records.value)

    const changed = await marking.toggle('q-2')

    expect(changed).toBe(true)
    expect(calls('/wrong-records/w-judged', 'DELETE')).toHaveLength(0)
    const masterCall = calls('/wrong-records/w-judged/master', 'POST')[0]
    expect(masterCall[0].data).toEqual({ is_mastered: true })
  })

  it('判题来源记录在确认框里取消时什么请求都不发', async () => {
    records.value = [judgedRecord()]
    const showModal = vi
      .spyOn(uni as any, 'showModal')
      .mockImplementation(({ success }: any) => success && success({ confirm: false }))
    const marking = useWrongMarking(() => records.value)

    const changed = await marking.toggle('q-2')

    expect(changed).toBe(false)
    expect(requestMock).not.toHaveBeenCalled()
    showModal.mockRestore()
  })

  it('已标记且已掌握的题目不再发请求，只提示', async () => {
    records.value = [judgedRecord({ is_mastered: true })]
    const marking = useWrongMarking(() => records.value)

    expect(await marking.toggle('q-2')).toBe(false)
    expect(requestMock).not.toHaveBeenCalled()
  })

  it('连点两次只发一次请求：在途状态挡住第二次', async () => {
    const marking = useWrongMarking(() => records.value)

    const [first, second] = await Promise.all([marking.toggle('q-1'), marking.toggle('q-1')])

    expect(calls('/wrong-records', 'POST')).toHaveLength(1)
    expect([first, second]).toEqual([true, false])
  })

  it('失败可见且可重试：返回 false，不吞错误，随后再点仍可成功', async () => {
    const showToast = vi.spyOn(uni as any, 'showToast')
    const marking = useWrongMarking(() => records.value)
    requestMock.mockImplementationOnce(async () => {
      throw new Error('network down')
    })

    expect(await marking.toggle('q-1')).toBe(false)
    expect(showToast).toHaveBeenCalled()
    expect(marking.isPending('q-1')).toBe(false)

    expect(await marking.toggle('q-1')).toBe(true)
    showToast.mockRestore()
  })

  it('已标记题目回显：marksById 按 question_id 反查得到记录', () => {
    records.value = [manualRecord(), judgedRecord()]
    const marking = useWrongMarking(() => records.value)

    expect(marking.marksById.value.get('q-1')?.id).toBe('w-manual')
    expect(marking.marksById.value.get('q-2')?.id).toBe('w-judged')
    expect(marking.marksById.value.get('q-3')).toBeUndefined()
  })
})

describe('manual wrong record enters the regeneration scope (AC-6, bounded)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    requestMock.mockReset()
    requestMock.mockImplementation(async (options: any) => {
      if (options.url === '/questions/generate') {
        return {
          qualified_questions: [
            {
              id: 'g-1',
              question_type: 'single_choice',
              stem: '再生题',
              options: [
                { key: 'A', content: '一' },
                { key: 'B', content: '二' },
              ],
              answer: 'A',
            },
          ],
          pending_questions: [],
          quality_checks: [],
        }
      }
      if (options.url === '/practices') return { id: 'p-new', title: '错题巩固练习' }
      // apiCreatePractice 创建后会再拉一次会话详情，进作答页用的是这一份。
      if (options.url === '/practices/p-new') {
        return {
          id: 'p-new',
          title: '错题巩固练习',
          status: 'not_started',
          total_count: 1,
          questions: [],
          items: [],
        }
      }
      throw new Error(`unexpected request: ${options.url}`)
    })
  })

  it('手工错题的知识点出现在再生题请求的 knowledge_point_ids 里', async () => {
    const manual = manualRecord()
    const wrongRecords = [manual]

    // 1. 页面收集再生题考点（与 review/index.vue 同一条路径）。
    const kpIds = groupKnowledgePointIds(wrongRecords, {
      key: 'folder:f-1',
      label: '课程',
      folderId: 'f-1',
      count: 1,
      unclassified: false,
    })
    expect(kpIds).toContain(manual.knowledge_point_id)

    // 2. 举一反三发起再生题：请求里必须含该手工错题的考点。
    const store = usePracticeStore()
    await store.regenerateFromWrongPoints(kpIds, { folderId: 'f-1' })

    const generateCalls = calls('/questions/generate')
    expect(generateCalls.length).toBeGreaterThan(0)
    const requested = generateCalls.flatMap(([options]: any[]) => options.data.knowledge_point_ids)
    expect(requested).toContain(manual.knowledge_point_id)
  })
})
