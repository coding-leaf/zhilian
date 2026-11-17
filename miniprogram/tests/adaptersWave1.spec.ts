import { beforeEach, describe, expect, it, vi } from 'vitest'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/utils/request', () => ({
  request: (options: any) => requestMock(options),
  uploadFile: vi.fn(),
}))

import {
  adaptPractice,
  adaptQuestion,
  apiCreateQuestionJob,
  apiGetKnowledgePointDetail,
  apiGetKnowledgeTree,
  apiGetMasteryOverview,
  apiGetQuestionJob,
  apiListQuestionJobs,
  apiParseMaterial,
  buildAttemptResults,
  wrongSnapshotKnowledgePointName,
} from '@/api'

describe('Wave 1 adapters & API contracts', () => {
  beforeEach(() => {
    requestMock.mockReset()
  })

  it('parses JSON array strings for multiple_choice user_answer on practice resume', () => {
    const session = adaptPractice({
      id: 'p-mc',
      practice_id: 'p-mc',
      title: '多选续练测试',
      status: 'in_progress',
      total_count: 2,
      items: [
        {
          attempt_item_id: 'a-1',
          question_id: 'q-mc',
          order_index: 1,
          status: 'answered',
          is_answered: true,
          user_answer: '["A","C"]',
          max_score: 2,
          question_snapshot: {
            id: 'q-mc',
            question_type: 'multiple_choice',
            knowledge_point_name: '条件独立假设',
            stem: '下列成立的是？',
            options: [
              { key: 'A.', content: 'A. 选项一' },
              { key: 'B', content: '（B）选项二' },
              { key: 'C', content: 'C、选项三' },
            ],
            answer: 'A,C',
          },
        },
        {
          attempt_item_id: 'a-2',
          question_id: 'q-sa',
          order_index: 2,
          status: 'answered',
          is_answered: true,
          user_answer: '["保留主观原文"]',
          max_score: 5,
          question_snapshot: {
            id: 'q-sa',
            question_type: 'short_answer',
            stem: '简述原理',
            options: [],
            answer: '答案',
          },
        },
      ],
    } as any)

    expect(session.user_answers?.['q-mc']).toEqual(['A', 'C'])
    expect(session.items?.[0].user_answer).toEqual(['A', 'C'])
    expect(session.questions[0].knowledge_point_name).toBe('条件独立假设')
    expect(session.questions[0].options).toEqual([
      { key: 'A', content: '选项一' },
      { key: 'B', content: '选项二' },
      { key: 'C', content: '选项三' },
    ])
    // 非多选题不得把普通文本解析为数组
    expect(session.user_answers?.['q-sa']).toBe('["保留主观原文"]')

    const results = buildAttemptResults(session)
    expect(results[0].userAnswer).toEqual(['A', 'C'])
    expect(results[0].knowledgePointName).toBe('条件独立假设')
  })

  it('strips duplicated prefixes and maps knowledge_point_name in adaptQuestion and wrong records', () => {
    const q = adaptQuestion({
      id: 'q-1',
      question_type: 'single_choice',
      knowledge_point_name: '拉普拉斯平滑',
      stem: '题干',
      options: [{ key: 'A', content: 'A. A. 分子加一' }],
    })
    expect(q.options?.[0]).toEqual({ key: 'A', content: '分子加一' })
    expect(q.knowledge_point_name).toBe('拉普拉斯平滑')

    expect(
      wrongSnapshotKnowledgePointName({
        id: 'w-1',
        practice_id: null,
        attempt_item_id: null,
        knowledge_point_id: 'kp-1',
        knowledge_point_name: '朴素贝叶斯',
        is_mastered: false,
        question_snapshot: {},
      }),
    ).toBe('朴素贝叶斯')
  })

  it('adapts structured_content and sort_order on knowledge tree & detail cleanly with null fallback', async () => {
    requestMock.mockImplementation(async ({ url }: { url: string }) => {
      if (url === '/materials/m-1/knowledge-tree') {
        return {
          material_id: 'm-1',
          version_id: 'v-1',
          nodes: [
            {
              id: 'kp-1',
              name: '朴素贝叶斯',
              sort_order: 2,
              level: 1,
              structured_content: {
                core_summary: '条件独立假设下的贝叶斯分类。',
                key_takeaways: ['条件独立', '拉普拉斯平滑'],
                key_formulas: ['P(Y=c_k|X) \\propto P(Y=c_k)'],
                boundary_notes: ['特征强相关时精度下降'],
              },
              children: [
                { id: 'kp-2', name: '旧格式节点', level: 2, structured_content: null },
              ],
            },
          ],
        }
      }
      if (url === '/knowledge/kp-1') {
        return {
          id: 'kp-1',
          name: '朴素贝叶斯',
          sort_order: 2,
          level: 1,
          structured_content: null,
        }
      }
      throw new Error(`unexpected: ${url}`)
    })

    const tree = await apiGetKnowledgeTree('m-1')
    expect(tree.nodes[0].sort_order).toBe(2)
    expect(tree.nodes[0].structured_content?.core_summary).toBe('条件独立假设下的贝叶斯分类。')
    expect(tree.nodes[0].children?.[0].structured_content).toBeNull()

    const detail = await apiGetKnowledgePointDetail('kp-1')
    expect(detail.structured_content).toBeNull()
    expect(detail.sort_order).toBe(2)
  })

  it('supports force=true on apiParseMaterial, mastery folder_id filter, and question jobs APIs', async () => {
    requestMock.mockImplementation(async ({ url }: { url: string }) => {
      if (url.startsWith('/mastery')) {
        return {
          total_points: 7,
          mastered_count: 2,
          learning_count: 3,
          weak_count: 2,
          overall_score: 0.62,
          points: [
            {
              knowledge_point_id: 'kp-1',
              knowledge_name: '贝叶斯定理',
              mastery_score: 0.4,
              level: 'weak',
              practice_count: 3,
              correct_count: 1,
            },
          ],
        }
      }
      if (url === '/questions/jobs' || url.startsWith('/questions/jobs/')) {
        return { id: 'job-1', status: 'queued', total_kps: 3, completed_kps: 0, generated_count: 0, question_ids: [] }
      }
      if (url.startsWith('/questions/jobs?')) {
        return { items: [{ id: 'job-1', status: 'running', total_kps: 3, completed_kps: 1, generated_count: 1 }], total: 1 }
      }
      return { message: 'ok' }
    })

    await apiParseMaterial('m-1')
    expect(requestMock).toHaveBeenLastCalledWith({ url: '/materials/m-1/parse', method: 'POST' })

    await apiParseMaterial('m-1', true)
    expect(requestMock).toHaveBeenLastCalledWith({ url: '/materials/m-1/parse?force=true', method: 'POST' })

    const masteryAll = await apiGetMasteryOverview('all')
    expect(requestMock).toHaveBeenLastCalledWith({ url: '/mastery', method: 'GET' })
    expect(masteryAll.total_knowledge_points).toBe(7)
    expect(masteryAll.points[0].level).toBe('weak')

    await apiGetMasteryOverview('__none__')
    expect(requestMock).toHaveBeenLastCalledWith({ url: '/mastery?folder_id=__none__', method: 'GET' })

    await apiCreateQuestionJob({ material_id: 'm-1', knowledge_point_ids: ['kp-1'], count: 3 })
    expect(requestMock).toHaveBeenLastCalledWith({
      url: '/questions/jobs',
      method: 'POST',
      data: { material_id: 'm-1', knowledge_point_ids: ['kp-1'], count: 3 },
    })

    const jobs = await apiListQuestionJobs({ active_only: true, folder_id: 'f-1' })
    expect(requestMock).toHaveBeenLastCalledWith({
      url: '/questions/jobs?active_only=true&folder_id=f-1',
      method: 'GET',
    })
    expect(jobs.items[0].status).toBe('running')

    const job = await apiGetQuestionJob('job-1')
    expect(job.id).toBe('job-1')
  })
})
