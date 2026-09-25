/**
 * 全局环境变量与网络基础配置。
 * 遵循 AGENTS.md 规范：单文件 <= 300 行、零表情包、全英文标识符。
 */

const DEFAULT_API_BASE_URL = 'http://10.39.144.79:8000';

/**
 * 获取当前有效的 API 基础前缀地址。
 * 支持真机或开发者工具通过本地缓存切换目标服务地址。
 */
export function getApiBaseUrl(): string {
  try {
    if (typeof uni !== 'undefined' && typeof uni.getStorageSync === 'function') {
      const customUrl = uni.getStorageSync('CUSTOM_API_BASE_URL');
      if (typeof customUrl === 'string' && customUrl.trim().length > 0) {
        return customUrl.trim().replace(/\/+$/, '');
      }
    }
  } catch {
    // 兼容脱机测试环境
  }

  const envUrl = (import.meta as unknown as { env?: Record<string, string> }).env
    ?.VITE_API_BASE_URL;
  if (envUrl && typeof envUrl === 'string' && envUrl.trim().length > 0) {
    return envUrl.trim().replace(/\/+$/, '');
  }

  if (typeof process !== 'undefined' && process.env?.NODE_ENV === 'test') {
    return '';
  }

  return DEFAULT_API_BASE_URL;
}

/**
 * 将相对 API 路径解析转换为包含协议与主机的绝对网络请求地址。
 */
export function resolveUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  const base = getApiBaseUrl();
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${base}${normalizedPath}`;
}
