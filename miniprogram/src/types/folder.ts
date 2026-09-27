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
