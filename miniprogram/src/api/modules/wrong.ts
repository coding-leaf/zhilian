import { request } from '@/utils/request'
import type {
  DeleteWrongRecordResult,
  MarkWrongRecordMasteredResult,
  WrongRecordItem,
  WrongRecordListQuery,
  WrongRecordListResult,
} from '@/types'

export function apiListWrongRecords(params?: WrongRecordListQuery): Promise<WrongRecordListResult> {
  const queryParts: string[] = []
  if (params?.folder_id) queryParts.push(`folder_id=${encodeURIComponent(params.folder_id)}`)
  if (params?.unclassified !== undefined) queryParts.push(`unclassified=${params.unclassified}`)
  if (params?.material_id) queryParts.push(`material_id=${encodeURIComponent(params.material_id)}`)
  if (params?.knowledge_point_id) queryParts.push(`knowledge_point_id=${encodeURIComponent(params.knowledge_point_id)}`)
  if (params?.is_mastered !== undefined) queryParts.push(`is_mastered=${params.is_mastered}`)
  if (params?.page) queryParts.push(`page=${params.page}`)
  if (params?.page_size) queryParts.push(`page_size=${params.page_size}`)

  const qs = queryParts.length ? `?${queryParts.join('&')}` : ''
  return request<WrongRecordListResult>({
    url: `/wrong-records${qs}`,
    method: 'GET',
  })
}

/**
 * 手动把题库里的一道题记入错题本（无需先在 App 里做过这道题）。
 *
 * 只传 `question_id`：知识点归属由服务端从题目解析，客户端传知识点只会多一个
 * 「归错考点 → 举一反三练错方向」的失效面。
 */
export function apiMarkQuestionWrong(questionId: string): Promise<WrongRecordItem> {
  return request<WrongRecordItem>({
    url: '/wrong-records',
    method: 'POST',
    data: { question_id: questionId },
  })
}

/** 取消手工错题标记（仅手工记录；判题来源的记录不得删除）。 */
export function apiDeleteWrongRecord(recordId: string): Promise<DeleteWrongRecordResult> {
  return request<DeleteWrongRecordResult>({
    url: `/wrong-records/${recordId}`,
    method: 'DELETE',
  })
}

/** 标记/取消错题「已掌握」（判题来源记录的取消标记走这里，而非删除）。 */
export function apiMarkWrongRecordMastered(
  recordId: string,
  isMastered = true,
): Promise<MarkWrongRecordMasteredResult> {
  return request<MarkWrongRecordMasteredResult>({
    url: `/wrong-records/${recordId}/master`,
    method: 'POST',
    data: { is_mastered: isMastered },
  })
}
