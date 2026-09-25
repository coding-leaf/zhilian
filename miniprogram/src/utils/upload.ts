/**
 * 智练小程序文件上传客户端。
 * 封装 uni.uploadFile 为 Promise，支持进度监听、自动注入 Authorization 凭证与状态校验。
 * 遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

import { AppError } from './error';
import { storage } from './storage';
import { resolveUrl } from '../config/env';
import type { ApiResponse } from '../types/common';

export interface UploadOptions {
  url: string;
  filePath: string;
  name?: string;
  formData?: Record<string, string | number>;
  headers?: Record<string, string>;
  onProgressUpdate?: (progress: number) => void;
  timeout?: number;
}

/**
 * 封装 uni.uploadFile 执行多段表单文件二进制上传。
 */
export async function uploadFile<T = unknown>(options: UploadOptions): Promise<ApiResponse<T>> {
  const fullUrl = resolveUrl(options.url);
  const headers: Record<string, string> = {
    ...(options.headers || {}),
  };

  const tokens = storage.getItem('auth_tokens');
  if (tokens?.access_token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${tokens.access_token}`;
  }

  return new Promise<ApiResponse<T>>((resolve, reject) => {
    let uploadTask: UniApp.UploadTask | undefined;
    try {
      uploadTask = uni.uploadFile({
        url: fullUrl,
        filePath: options.filePath,
        name: options.name || 'file',
        formData: options.formData,
        header: headers,
        timeout: options.timeout || 60000,
        success: (result) => {
          const statusCode = result.statusCode;
          let parsedData: Record<string, unknown> = {};

          try {
            if (typeof result.data === 'string') {
              parsedData = JSON.parse(result.data) as Record<string, unknown>;
            } else if (typeof result.data === 'object' && result.data !== null) {
              parsedData = result.data as Record<string, unknown>;
            }
          } catch {
            parsedData = { raw: result.data };
          }

          if (statusCode < 200 || statusCode >= 300) {
            const errCode = typeof parsedData.code === 'number' ? parsedData.code : statusCode;
            const errMsg =
              typeof parsedData.message === 'string'
                ? parsedData.message
                : `上传失败 (HTTP ${statusCode})`;
            return reject(
              new AppError(errCode, errMsg, {
                status_code: statusCode,
                details: parsedData.details as Record<string, unknown> | undefined,
              }),
            );
          }

          if (
            typeof parsedData.code === 'number' &&
            parsedData.code !== 0 &&
            parsedData.code !== 200 &&
            parsedData.code !== 201
          ) {
            return reject(
              new AppError(
                parsedData.code,
                typeof parsedData.message === 'string' ? parsedData.message : '上传失败',
                {
                  status_code: statusCode,
                  details: parsedData.details as Record<string, unknown> | undefined,
                },
              ),
            );
          }

          if (typeof parsedData.code === 'number' && 'data' in parsedData) {
            return resolve(parsedData as unknown as ApiResponse<T>);
          }

          resolve({
            code: 0,
            message: 'success',
            data: parsedData as T,
          });
        },
        fail: (err) => {
          reject(
            new AppError(-1, '网络连接异常，文件上传失败', {
              details: { original_error: String(err?.errMsg || err) },
            }),
          );
        },
      });

      if (uploadTask && typeof options.onProgressUpdate === 'function') {
        uploadTask.onProgressUpdate((res) => {
          if (typeof res.progress === 'number' && options.onProgressUpdate) {
            options.onProgressUpdate(res.progress);
          }
        });
      }
    } catch (err) {
      reject(
        new AppError(-1, '网络请求初始化失败', {
          details: { original_error: String(err) },
        }),
      );
    }
  });
}
