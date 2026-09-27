/**
 * ZhiLian Mini-Program Course Folder Data Contracts
 * Mirrors backend `FolderDetailResponse` / `FolderListResponse` field names exactly.
 * A field-name drift (e.g. `is_archived` vs `archived`) renders `undefined` silently.
 */

/** 未分类资料的虚拟课程过滤标识（与后端 material.py `_parse_folder_filter` 约定一致）。 */
export const UNCLASSIFIED_FOLDER_ID = '__none__';

export interface FolderItem {
  id: string;
  name: string;
  parent_id?: string | null;
  sort_order?: number;
  is_archived: boolean;
  archived_at?: string | null;
  purge_after?: string | null;
  material_count: number;
  ready_material_count: number;
  knowledge_point_count: number;
  question_count: number;
  last_practice_at?: string | null;
  created_at: string;
  updated_at?: string;
}

export interface FolderListQuery {
  include_archived?: boolean;
  limit?: number;
  offset?: number;
}

export interface FolderListResult {
  items: FolderItem[];
  total: number;
}

export interface FolderDeleteResult {
  id: string;
  is_deleted: boolean;
  archived_at?: string | null;
  purge_after?: string | null;
  message: string;
}

/** 课程内单个考点条目（与后端 `FolderKnowledgePointItem` 逐字一致）。 */
export interface FolderKnowledgePointItem {
  id: string;
  name: string;
  level: number;
  parent_id?: string | null;
}

/** 课程内按来源资料分组的考点集合（与后端 `FolderKnowledgePointGroup` 逐字一致）。 */
export interface FolderKnowledgePointGroup {
  material_id: string;
  material_title: string;
  knowledge_points: FolderKnowledgePointItem[];
}

/** 课程考点列表响应（与后端 `FolderKnowledgePointsResponse` 逐字一致）。 */
export interface FolderKnowledgePointsResult {
  folder_id: string;
  groups: FolderKnowledgePointGroup[];
  total: number;
}
