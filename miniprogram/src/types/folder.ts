// 课程文件夹
export interface FolderItem {
  id: string
  name: string
  parent_id?: string | null
  sort_order: number
  is_archived: boolean
  archived_at?: string | null
  purge_after?: string | null
  material_count: number
  ready_material_count: number
  knowledge_point_count: number
  question_count: number
  last_practice_at?: string | null
  created_at: string
  updated_at: string
}

export interface FolderListResult {
  items: FolderItem[]
  total: number
}

export interface FolderKnowledgePointItem {
  id: string
  name: string
  level: number
  parent_id?: string | null
}

export interface FolderKnowledgePointGroup {
  material_id: string
  material_title: string
  knowledge_points: FolderKnowledgePointItem[]
}

export interface FolderKnowledgePointsResult {
  folder_id: string
  groups: FolderKnowledgePointGroup[]
  total: number
}
