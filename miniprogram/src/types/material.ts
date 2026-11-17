// 资料状态机：与 backend/app/models/material.py 的主状态保持一致
export type MaterialStatus = 'pending' | 'parsing' | 'ready' | 'failed' | 'retake_required'

export interface MaterialItem {
  id: string
  title: string
  file_format?: string
  file_size?: number
  source_type?: string
  status: MaterialStatus
  created_at: string
  updated_at?: string
  error_message?: string
  page_count?: number
  current_version_id?: string
  folder_id?: string | null
  parse_status?: string | null
  progress_percentage?: number | null
  key_points_count?: number | null
}

export interface MaterialListQuery {
  folder_id?: string
  status?: string
}

export interface MaterialListResult {
  items: MaterialItem[]
  total: number
  limit: number
  offset: number
}

// 当前用户未删除且 ready 的全部资料，包含未分类与归档课程。
export interface MaterialStatistics {
  ready_material_count: number
  knowledge_point_count: number
}

export type LearningStatisticsState =
  | { status: 'logged-out' | 'loading' | 'error' }
  | ({ status: 'ready'; course_count: number } & MaterialStatistics)
