/**
 * 学习资料上传与单页重拍 API 网络接口模块。
 *
 * 自 `material.ts` 拆分以遵守单文件 <= 300 行约定；`material.ts` 对其再做再导出，
 * 调用方仍可继续从 `@/api/material` 引入。
 * 真机端走 multipart `uni.uploadFile`，测试/开发环境保留 JSON 分支。
 */

import { request } from '../utils/request';
import { uploadFile } from '../utils/upload';
import type { ApiResponse } from '../types/common';
import type { MaterialUploadResponse, MaterialReshootResponse } from '../types/material';

/**
 * 判断当前是否运行在具备 multipart 能力的真机小程序环境。
 *
 * @returns 真机小程序环境返回 true，测试/开发环境返回 false。
 */
export function isRealMiniProgramUpload(): boolean {
  if (typeof process !== 'undefined' && process.env?.NODE_ENV === 'test') {
    return false;
  }
  return typeof uni !== 'undefined' && typeof uni.uploadFile === 'function';
}

/**
 * 上传学习资料文件并创建初始版本。
 *
 * @param file 待上传的文件对象或本地临时路径。
 * @param title 资料展示标题（可选）。
 * @param idempotencyKey 防重放幂等键（可选）。
 * @param sourceType 资料来源渠道，默认 local。
 * @param onProgressUpdate 上传进度回调（可选）。
 * @param folderId 归属课程文件夹标识（可选，缺省=未分类）。
 * @returns 统一响应包，包含上传后的资料信息。
 */
export function uploadMaterial(
  file: File | Blob | string,
  title?: string,
  idempotencyKey?: string,
  sourceType: 'local' | 'wechat' = 'local',
  onProgressUpdate?: (progress: number) => void,
  folderId?: string,
): Promise<ApiResponse<MaterialUploadResponse>> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey;
  }
  if (isRealMiniProgramUpload() && typeof file === 'string') {
    const formData: Record<string, string> = {
      title: title || '',
      source_type: sourceType,
    };
    if (folderId) {
      formData.folder_id = folderId;
    }
    return uploadFile<MaterialUploadResponse>({
      url: '/api/v1/materials/upload',
      filePath: file,
      name: 'file',
      formData,
      headers,
      onProgressUpdate,
    });
  }
  const data: Record<string, unknown> = { file, title, source_type: sourceType };
  if (folderId) {
    data.folder_id = folderId;
  }
  return request<MaterialUploadResponse>({
    url: '/api/v1/materials/upload',
    method: 'POST',
    data,
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
): Promise<ApiResponse<MaterialReshootResponse>> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey;
  }
  // 真机端后端契约为 multipart File+Form；非真机（测试/开发）保留 JSON 分支。
  if (isRealMiniProgramUpload() && typeof file === 'string') {
    return uploadFile<MaterialReshootResponse>({
      url: `/api/v1/materials/${materialId}/reshoot`,
      filePath: file,
      name: 'file',
      formData: { page_index: pageNo },
      headers,
    });
  }
  return request<MaterialReshootResponse>({
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
  folderId?: string;
  onProgressUpdate?: (progress: number) => void;
}): Promise<ApiResponse<MaterialUploadResponse>> {
  return uploadMaterial(
    params.filePath,
    params.title,
    params.idempotencyKey,
    params.sourceType || 'local',
    params.onProgressUpdate,
    params.folderId,
  );
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
  if (isRealMiniProgramUpload() && typeof params.filePath === 'string') {
    const formData: Record<string, string | number> = {
      page_index: params.pageIndex,
    };
    if (params.versionId) {
      formData.version_id = params.versionId;
    }
    return uploadFile<MaterialReshootResponse>({
      url: `/api/v1/materials/${params.materialId}/reshoot`,
      filePath: params.filePath,
      name: 'file',
      formData,
      headers,
    });
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
