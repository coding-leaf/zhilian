/**
 * 学习资料管理 API 网络接口模块。
 *
 * 封装资料列表检索、详情查询、状态轮询、资料删除、归属移动与知识树拓扑获取。
 * 上传 / 单页重拍相关接口拆分至 `materialUpload.ts`，此处再导出以保持调用契约稳定。
 * 严格遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { request } from '../utils/request';
import type { ApiResponse, PageResult } from '../types/common';
import type {
  MaterialItem,
  MaterialListQueryParams,
  KnowledgeTreeResponse,
  MaterialParseResponse,
  MaterialOCRPagesResponse,
} from '../types/material';

/**
 * 分页检索当前用户的学习资料列表。
 *
 * @param params 分页与筛选条件（页码、条数、关键词、状态、课程）。
 * @returns 统一响应包，包含分页资料项列表与总数。
 */
export function fetchMaterialList(
  params?: MaterialListQueryParams,
): Promise<ApiResponse<PageResult<MaterialItem>>> {
  const cleaned: Record<string, unknown> = {};
  if (params) {
    for (const [key, val] of Object.entries(params)) {
      if (val !== undefined && val !== null && val !== '') {
        cleaned[key] = val;
      }
    }
  }
  return request<PageResult<MaterialItem>>({
    url: '/api/v1/materials',
    method: 'GET',
    data: Object.keys(cleaned).length > 0 ? cleaned : undefined,
  });
}

/**
 * 获取指定学习资料的元数据详情。
 *
 * @param materialId 目标资料主键 ID。
 * @returns 统一响应包，包含资料详细信息与激活版本信息。
 */
export function fetchMaterialDetail(materialId: string): Promise<ApiResponse<MaterialItem>> {
  return request<MaterialItem>({
    url: `/api/v1/materials/${materialId}`,
    method: 'GET',
  });
}

/**
 * 轮询查询指定学习资料的解析或处理状态。
 *
 * @param materialId 目标资料主键 ID。
 * @returns 统一响应包，包含当前资料最新状态与版本元数据。
 */
export function fetchMaterialStatus(materialId: string): Promise<ApiResponse<MaterialItem>> {
  return request<MaterialItem>({
    url: `/api/v1/materials/${materialId}`,
    method: 'GET',
  });
}

/**
 * 删除指定学习资料（支持软删除与物理级联硬删除）。
 *
 * @param materialId 目标资料主键 ID。
 * @param hard 是否物理彻底销毁，默认 false（软删除移至回收站）。
 * @returns 统一响应包，包含删除结果提示。
 */
export function deleteMaterial(
  materialId: string,
  hard = false,
): Promise<ApiResponse<{ material_id: string; is_deleted: boolean; permanent?: boolean }>> {
  return request<{ material_id: string; is_deleted: boolean; permanent?: boolean }>({
    url: hard ? `/api/v1/materials/${materialId}/hard` : `/api/v1/materials/${materialId}`,
    method: 'DELETE',
  });
}

/**
 * 一键重试解析失败的学习资料流水线。
 *
 * @param materialId 目标资料主键 ID。
 * @returns 统一响应包，包含重新进入处理态的资料最新详情。
 */
export function retryMaterial(materialId: string): Promise<ApiResponse<MaterialItem>> {
  return request<MaterialItem>({
    url: `/api/v1/materials/${materialId}/retry`,
    method: 'POST',
  });
}

/**
 * 触发或重新调度学习资料解析流水线。
 *
 * @param materialId 目标资料主键 ID。
 * @param options 可选参数（指定版本与是否同步阻塞）。
 * @returns 统一响应包，包含调度或执行结果。
 */
export function triggerMaterialParse(
  materialId: string,
  options?: { versionId?: string; sync?: boolean },
): Promise<ApiResponse<MaterialParseResponse>> {
  return request<MaterialParseResponse>({
    url: `/api/v1/materials/${materialId}/parse`,
    method: 'POST',
    data: {
      version_id: options?.versionId,
      sync: options?.sync ?? false,
    },
  });
}

/**
 * 获取指定学习资料的知识树树形拓扑结构。
 *
 * @param materialId 目标资料主键 ID。
 * @param versionId 可选指定的资料版本主键 ID，缺省使用最新版本。
 * @returns 统一响应包，包含层级嵌套的知识点树形拓扑。
 */
export function fetchKnowledgeTree(
  materialId: string,
  versionId?: string,
): Promise<ApiResponse<KnowledgeTreeResponse>> {
  return request<KnowledgeTreeResponse>({
    url: `/api/v1/materials/${materialId}/knowledge-tree`,
    method: 'GET',
    data: versionId ? { version_id: versionId } : undefined,
  });
}

/**
 * 移动指定资料的归属课程（folder_id 为 null 表示移回未分类）。
 *
 * @param materialId 目标资料主键 ID。
 * @param folderId 目标课程主键 ID，或 null（未分类）。
 * @returns 统一响应包，包含移动后的资料详情。
 */
export function moveMaterialFolder(
  materialId: string,
  folderId: string | null,
): Promise<ApiResponse<MaterialItem>> {
  return request<MaterialItem>({
    url: `/api/v1/materials/${materialId}/folder`,
    method: 'PATCH',
    data: { folder_id: folderId },
  });
}

/**
 * 查询资料当前激活（或最新）版本的页级 OCR 质检记录。
 *
 * @param materialId 目标资料主键 ID。
 * @param onlyUnqualified 是否仅返回未达标页面，默认 false（全量）。
 * @returns 统一响应包，包含页级质检记录列表。
 */
export function fetchMaterialOCRPages(
  materialId: string,
  onlyUnqualified = false,
): Promise<ApiResponse<MaterialOCRPagesResponse>> {
  return request<MaterialOCRPagesResponse>({
    url: `/api/v1/materials/${materialId}/ocr-pages`,
    method: 'GET',
    data: { only_unqualified: onlyUnqualified },
  });
}

export {
  uploadMaterial,
  retakeMaterialPage,
  uploadMaterialFile,
  reshootMaterialPage,
} from './materialUpload';
