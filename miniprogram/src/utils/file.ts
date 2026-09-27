/**
 * 资料文件校验与幂等键工具纯函数
 */

export interface SelectedFileInfo {
  name: string;
  path: string;
  size: number;
  sourceType: 'local' | 'wechat';
}

/**
 * Mini-program accepted file extensions.
 *
 * This whitelist is a **deliberate, controlled subset** of the backend
 * `MaterialDocType` / `MAX_FILE_SIZES` catalogue (see
 * `backend/app/services/material.py` and `backend/app/models/material.py`).
 * The mobile client intentionally keeps pptx/txt/md unsupported because of
 * WeChat file-picker and preview limitations (confirmed design narrowing, not
 * an omission).
 */
const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.png', '.jpg', '.jpeg'];

/**
 * Per-format size ceilings (bytes), aligned with the backend
 * `MAX_FILE_SIZES` table for the formats accepted by this client.
 */
export const MAX_FILE_SIZES: Record<string, number> = {
  pdf: 20 * 1024 * 1024,
  docx: 20 * 1024 * 1024,
  png: 10 * 1024 * 1024,
  jpg: 10 * 1024 * 1024,
  jpeg: 10 * 1024 * 1024,
};

/** Fallback ceiling (bytes) for unknown-but-recognised extensions. */
export const DEFAULT_MAX_FILE_SIZE = 20 * 1024 * 1024;

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg']);

function extractExtension(lowerName: string): string {
  const dotIndex = lowerName.lastIndexOf('.');
  return dotIndex >= 0 ? lowerName.slice(dotIndex + 1) : '';
}

function formatMegabytes(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))}MB`;
}

export function generateIdempotencyKey(): string {
  const chars = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
  let result = '';
  const cryptoObj = typeof crypto !== 'undefined' ? crypto : undefined;
  if (cryptoObj?.getRandomValues) {
    const bytes = new Uint8Array(16);
    cryptoObj.getRandomValues(bytes);
    for (let i = 0; i < 16; i++) {
      result += chars[bytes[i] % chars.length];
    }
  } else {
    for (let i = 0; i < 16; i++) {
      result += chars[Math.floor(Math.random() * chars.length)];
    }
  }
  return result;
}

export function validateMaterialFile(
  name: string,
  size: number,
): { valid: boolean; error?: string } {
  const lowerName = name.toLowerCase();
  const hasValidExt = ALLOWED_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
  if (!hasValidExt) {
    return { valid: false, error: '目前仅支持 PDF、DOCX 及图片格式文件' };
  }
  const ext = extractExtension(lowerName);
  const maxSize = MAX_FILE_SIZES[ext] ?? DEFAULT_MAX_FILE_SIZE;
  if (size > maxSize) {
    const sizeLabel = formatMegabytes(maxSize);
    const error = IMAGE_EXTENSIONS.has(ext)
      ? `图片体积过大，请上传小于 ${sizeLabel} 的文件`
      : `文件体积过大，请上传小于 ${sizeLabel} 的文件`;
    return { valid: false, error };
  }
  return { valid: true };
}
