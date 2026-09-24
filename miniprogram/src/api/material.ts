/**
 * 学习资料管理 API 网络接口模块。
 *
 * 封装资料列表检索、详情查询、状态轮询、资料删除与知识树拓扑获取。
 * 严格遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { request } from '../utils/request';
import type { ApiResponse, PageResult } from '../types/common';
import type {
  MaterialItem,
  MaterialListQueryParams,
  KnowledgeTreeResponse,
  MaterialUploadResponse,
  MaterialReshootResponse,
  RetakePageResponse,
} from '../types/material';

/**
 * 分页检索当前用户的学习资料列表。
 *
 * @param params 分页与筛选条件（页码、条数、关键词、状态）。
 * @returns 统一响应包，包含分页资料项列表与总数。
 */
export function fetchMaterialList(
  params?: MaterialListQueryParams,
): Promise<ApiResponse<PageResult<MaterialItem>>> {
  return request<PageResult<MaterialItem>>({
    url: '/api/v1/materials',
    method: 'GET',
    data: params,
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
 * 上传学习资料文件并创建初始版本。
 *
 * @param file 待上传的文件对象或本地临时路径。
 * @param title 资料展示标题（可选）。
 * @param idempotencyKey 防重放幂等键（可选）。
 * @returns 统一响应包，包含上传后的资料信息。
 */
export function uploadMaterial(
  file: File | Blob | string,
  title?: string,
  idempotencyKey?: string,
): Promise<ApiResponse<MaterialUploadResponse>> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey;
  }
  return request<MaterialUploadResponse>({
    url: '/api/v1/materials/upload',
    method: 'POST',
    data: { file, title },
    headers,
  });
}

/**
 * 针对 OCR 质检不达标的单页进行重拍替换与重检。
 *
 * @param materialId 目标资料主键 ID。
 * @param pageNo 重拍目标页码（从 1 开始）。
 * @param file 重新拍摄的单页图片。
 * @param idempotencyKey 防重放幂等键（可选）。
 * @returns 统一响应包，包含重拍判定结果。
 */
export function retakeMaterialPage(
  materialId: string,
  pageNo: number,
  file: File | Blob | string,
  idempotencyKey?: string,
): Promise<ApiResponse<RetakePageResponse>> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey;
  }
  return request<RetakePageResponse>({
    url: `/api/v1/materials/${materialId}/reshoot`,
    method: 'POST',
    data: { page_index: pageNo, file },
    headers,
  });
}

/**
 * 上传资料文件标准别名契约 (支持对象式调用与进度监听)。
 *
 * @param params 上传参数对象。
 * @returns 统一响应包。
 */
export function uploadMaterialFile(params: {
  filePath: string;
  title?: string;
  sourceType?: 'local' | 'wechat';
  idempotencyKey?: string;
  onProgressUpdate?: (progress: number) => void;
}): Promise<ApiResponse<MaterialUploadResponse>> {
  return uploadMaterial(params.filePath, params.title, params.idempotencyKey);
}

/**
 * 单页重拍标准别名契约 (支持对象式调用)。
 *
 * @param params 重拍参数对象。
 * @returns 统一响应包。
 */
export function reshootMaterialPage(params: {
  materialId: string;
  pageIndex: number;
  filePath: string;
  versionId?: string;
  idempotencyKey?: string;
}): Promise<ApiResponse<MaterialReshootResponse>> {
  const headers: Record<string, string> = {};
  if (params.idempotencyKey) {
    headers['Idempotency-Key'] = params.idempotencyKey;
  }
  return request<MaterialReshootResponse>({
    url: `/api/v1/materials/${params.materialId}/reshoot`,
    method: 'POST',
    data: {
      page_index: params.pageIndex,
      file: params.filePath,
      version_id: params.versionId,
    },
    headers,
  });
}
