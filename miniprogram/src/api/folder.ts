/**
 * 课程文件夹管理 API 网络接口模块。
 *
 * 封装课程新建/列表/详情/重命名/归档/恢复。Store 层严禁发请求，统一经此调用。
 * 严格遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { request } from '../utils/request';
import type { ApiResponse } from '../types/common';
import type {
  FolderItem,
  FolderListQuery,
  FolderListResult,
  FolderDeleteResult,
} from '../types/folder';

/**
 * 分页检索当前用户的课程文件夹列表（默认隐藏已归档课程）。
 *
 * @param params 过滤参数（是否包含已归档、分页游标）。
 * @returns 统一响应包，包含课程列表与总数。
 */
export function fetchFolderList(params?: FolderListQuery): Promise<ApiResponse<FolderListResult>> {
  const data: Record<string, unknown> = {};
  if (params) {
    for (const [key, val] of Object.entries(params)) {
      if (val !== undefined && val !== null && val !== '') {
        data[key] = val;
      }
    }
  }
  return request<FolderListResult>({
    url: '/api/v1/folders',
    method: 'GET',
    data: Object.keys(data).length > 0 ? data : undefined,
  });
}

/**
 * 获取指定课程文件夹详情（含聚合计数）。
 *
 * @param folderId 目标课程主键 UUID。
 * @returns 统一响应包，包含课程聚合详情。
 */
export function fetchFolderDetail(folderId: string): Promise<ApiResponse<FolderItem>> {
  return request<FolderItem>({
    url: `/api/v1/folders/${folderId}`,
    method: 'GET',
  });
}

/**
 * 新建课程文件夹。
 *
 * @param payload 课程名称请求体。
 * @returns 统一响应包，包含新建课程详情。
 */
export function createFolder(payload: { name: string }): Promise<ApiResponse<FolderItem>> {
  return request<FolderItem>({
    url: '/api/v1/folders',
    method: 'POST',
    data: payload,
  });
}

/**
 * 重命名指定课程文件夹。
 *
 * @param folderId 目标课程主键 UUID。
 * @param payload 新名称请求体。
 * @returns 统一响应包，包含重命名后的课程详情。
 */
export function renameFolder(
  folderId: string,
  payload: { name: string },
): Promise<ApiResponse<FolderItem>> {
  return request<FolderItem>({
    url: `/api/v1/folders/${folderId}`,
    method: 'PATCH',
    data: payload,
  });
}

/**
 * 归档指定课程文件夹（软删除，7 天内可恢复）。
 *
 * @param folderId 目标课程主键 UUID。
 * @returns 统一响应包，包含归档结果与物理清理时间。
 */
export function archiveFolder(folderId: string): Promise<ApiResponse<FolderDeleteResult>> {
  return request<FolderDeleteResult>({
    url: `/api/v1/folders/${folderId}`,
    method: 'DELETE',
  });
}

/**
 * 恢复已归档的课程文件夹。
 *
 * @param folderId 目标课程主键 UUID。
 * @returns 统一响应包，包含恢复后的课程详情。
 */
export function restoreFolder(folderId: string): Promise<ApiResponse<FolderItem>> {
  return request<FolderItem>({
    url: `/api/v1/folders/${folderId}/restore`,
    method: 'POST',
  });
}
