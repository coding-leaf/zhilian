/**
 * ZhiLian Mini-Program Business Error Module
 * Provides AppError base class and error code mapping to user-friendly copy.
 * Strictly adheres to docs/DESIGN.md Section 5 natural copywriting and zero-emoji policy.
 */

export const ERROR_MESSAGES: Record<number, string> = {
  10001: '输入信息格式有误，请核对后重试',
  20001: '登录状态已过期，请重新登录',
  20002: '无权访问此内容',
  30001: '图片识别或解析未完成，请重试或重新拍摄',
  30004: '图片识别或解析未完成，请重试或重新拍摄',
  30010: '智能分析暂不可用，请稍后重试',
  30011: '智能分析暂不可用，请稍后重试',
  40001: '资料清晰度不足或内容过少，请重新拍摄',
  40002: '重拍次数已达上限，请重新选择资料',
  40004: '当前学习资料不存在或已被移除',
  40010: '练习记录不存在或已被移除',
  40011: '当前练习已提交或已关闭，无法继续作答',
  40016: '练习正在批改中，请稍候查看结果',
  50000: '系统繁忙，请稍后重试',
};

export const NETWORK_ERROR_MESSAGE = '网络连接异常，请检查网络设置';
export const DEFAULT_ERROR_MESSAGE = '系统繁忙，请稍后重试';

/**
 * Maps error code to user-friendly natural copywriting.
 *
 * @param code 5-digit error code or network error indicator.
 * @param fallback Optional fallback message if code is unmapped.
 * @returns Human-readable message without technical jargon or emojis.
 */
export function mapErrorCodeToMessage(code: number | string, fallback?: string): string {
  if (code === 'NETWORK_FAIL' || code === -1) {
    return NETWORK_ERROR_MESSAGE;
  }

  const numericCode = typeof code === 'string' ? parseInt(code, 10) : code;
  if (isNaN(numericCode)) {
    return fallback || DEFAULT_ERROR_MESSAGE;
  }

  // Exact match from dictionary
  if (ERROR_MESSAGES[numericCode]) {
    return ERROR_MESSAGES[numericCode];
  }

  // 5-digit range classifications
  if (numericCode >= 10000 && numericCode <= 10999) {
    return '输入信息格式有误，请核对后重试';
  }
  if (numericCode >= 20000 && numericCode <= 29999) {
    return '登录状态已过期，请重新登录';
  }
  if (numericCode >= 30000 && numericCode <= 39999) {
    return '智能分析暂不可用，请稍后重试';
  }
  if (numericCode >= 40000 && numericCode <= 49999) {
    return fallback || '资料清晰度不足或内容过少，请重新拍摄';
  }
  if (numericCode >= 50000 && numericCode <= 59999) {
    return '系统繁忙，请稍后重试';
  }

  return fallback || DEFAULT_ERROR_MESSAGE;
}

export interface AppErrorOptions {
  details?: Record<string, unknown>;
  status_code?: number;
}

/**
 * ZhiLian Mini-Program unified application business error class.
 */
export class AppError extends Error {
  public readonly code: number;
  public readonly details?: Record<string, unknown>;
  public readonly status_code?: number;

  constructor(code: number = 50000, message?: string, options?: AppErrorOptions) {
    const finalMessage = message || mapErrorCodeToMessage(code);
    super(finalMessage);
    this.name = 'AppError';
    this.code = code;
    this.details = options?.details;
    this.status_code = options?.status_code;

    // Restore prototype chain
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/** 课程文件夹名称冲突的后端错误码（FolderNameConflictError, HTTP 409）。 */
export const FOLDER_NAME_CONFLICT_CODE = 40021;

/**
 * 判定错误是否为「课程名称已存在」冲突（40021 / HTTP 409）。
 *
 * @param err 待判定的未知错误。
 * @returns 命中名称冲突返回 true。
 */
export function isFolderNameConflictError(err: unknown): boolean {
  return (
    err instanceof AppError && (err.code === FOLDER_NAME_CONFLICT_CODE || err.status_code === 409)
  );
}
