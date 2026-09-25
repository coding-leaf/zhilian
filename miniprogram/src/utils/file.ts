/**
 * 资料文件校验与幂等键工具纯函数
 */

export interface SelectedFileInfo {
  name: string;
  path: string;
  size: number;
  sourceType: 'local' | 'wechat';
}

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.png', '.jpg', '.jpeg'];
const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB

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
  if (size > MAX_FILE_SIZE) {
    return { valid: false, error: '文件体积过大，请上传小于 20MB 的文件' };
  }
  return { valid: true };
}
