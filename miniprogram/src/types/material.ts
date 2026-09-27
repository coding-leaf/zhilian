/**
 * ZhiLian Mini-Program Material Data Contracts
 * Defines material item metadata, parsing status, and snippet structures.
 */

export type MaterialStatus =
  | 'pending'
  | 'parsing'
  | 'ready'
  | 'failed'
  | 'retake_required'
  | 'completed'
  | 'PENDING'
  | 'PARSING'
  | 'READY'
  | 'FAILED'
  | 'RETAKE_REQUIRED'
  | 'COMPLETED';

export interface MaterialItem {
  id: string;
  title: string;
  file_format: string;
  file_size: number;
  source_type: string;
  status: MaterialStatus;
  current_version_id?: string | null;
  versions_count?: number;
  parse_status?: string | null;
  progress_percentage?: number | null;
  created_at: string;
  updated_at?: string;
}

export interface SnippetItem {
  id: string;
  material_id: string;
  version_id: string;
  snippet_index: number;
  content_preview?: string;
  char_count?: number;
  created_at?: string;
}

export interface MaterialListQueryParams {
  page?: number;
  page_size?: number;
  limit?: number;
  offset?: number;
  keyword?: string;
  status?: string;
}

export interface KnowledgeTreeNode {
  id: string;
  name?: string;
  title?: string;
  material_id?: string;
  version_id?: string;
  parent_id?: string | null;
  description?: string;
  level: number;
  is_low_confidence?: boolean;
  confidence_score?: number;
  batch_id?: string;
  order_index?: number;
  children?: KnowledgeTreeNode[];
}

export type KnowledgeTreeNodeItem = KnowledgeTreeNode;

export interface KnowledgeTreeResponse {
  material_id: string;
  version_id: string;
  nodes: KnowledgeTreeNode[];
}

/**
 * 单页 OCR 质检与识别状态
 */
export interface PageOCRStatus {
  page_no: number;
  is_qualified: boolean;
  issue_type?: string | null;
  issue_description?: string | null;
  retake_count: number;
  max_retakes: number;
}

/**
 * 资料上传响应 DTO
 */
export interface MaterialUploadResponse {
  id: string;
  version_id: string;
  title: string;
  file_format: string;
  file_size: number;
  source_type: string;
  status: MaterialStatus;
  created_at: string;
}

/**
 * 资料单页重拍响应 DTO (与后端对齐)
 */
export interface MaterialReshootResponse {
  material_id: string;
  version_id?: string;
  page_index: number;
  is_qualified: boolean;
  reshoot_count: number;
  parse_status: string;
  unqualified_reason?: string | null;
}

/**
 * 资料解析调度响应 DTO
 */
export interface MaterialParseResponse {
  material_id: string;
  version_id: string;
  parse_status: string;
  is_active: boolean;
  message: string;
}

/**
 * 单页 OCR 质检记录 (与后端 MaterialOCRPageItem 字段对齐)
 */
export interface MaterialOCRPageItem {
  page_number: number;
  is_qualified: boolean;
  reshoot_count: number;
  unqualified_reason?: string | null;
}

/**
 * 资料页级 OCR 质检列表响应 DTO (与后端 MaterialOCRPagesResponse 字段对齐)
 */
export interface MaterialOCRPagesResponse {
  material_id: string;
  version_id?: string | null;
  items: MaterialOCRPageItem[];
}
