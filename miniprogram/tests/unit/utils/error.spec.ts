import { describe, it, expect } from 'vitest';
import { AppError, mapErrorCodeToMessage, ERROR_MESSAGES } from '@/utils/error';

describe('AppError and Error Code Mapping', () => {
  it('should map exact error codes to designated copy without emojis', () => {
    expect(mapErrorCodeToMessage(10001)).toBe('输入信息格式有误，请核对后重试');
    expect(mapErrorCodeToMessage(20001)).toBe('登录状态已过期，请重新登录');
    expect(mapErrorCodeToMessage(20002)).toBe('无权访问此内容');
    expect(mapErrorCodeToMessage(30001)).toBe('图片识别或解析未完成，请重试或重新拍摄');
    expect(mapErrorCodeToMessage(30004)).toBe('图片识别或解析未完成，请重试或重新拍摄');
    expect(mapErrorCodeToMessage(30010)).toBe('智能分析暂不可用，请稍后重试');
    expect(mapErrorCodeToMessage(30011)).toBe('智能分析暂不可用，请稍后重试');
    expect(mapErrorCodeToMessage(40001)).toBe('资料清晰度不足或内容过少，请重新拍摄');
    expect(mapErrorCodeToMessage(40002)).toBe('重拍次数已达上限，请重新选择资料');
    expect(mapErrorCodeToMessage(40004)).toBe('当前学习资料不存在或已被移除');
    expect(mapErrorCodeToMessage(40010)).toBe('练习记录不存在或已被移除');
    expect(mapErrorCodeToMessage(40011)).toBe('当前练习已提交或已关闭，无法继续作答');
    expect(mapErrorCodeToMessage(40016)).toBe('练习正在批改中，请稍候查看结果');
    expect(mapErrorCodeToMessage(50000)).toBe('系统繁忙，请稍后重试');
  });

  it('should verify zero-emoji constraint across all registered messages', () => {
    const emojiRegex = /[\u{1F300}-\u{1FAFF}]/u;
    for (const [code, msg] of Object.entries(ERROR_MESSAGES)) {
      expect(emojiRegex.test(msg), `Message for code ${code} must not contain emoji`).toBe(false);
    }
  });

  it('should correctly fall back across 5-digit ranges', () => {
    expect(mapErrorCodeToMessage(10050)).toBe('输入信息格式有误，请核对后重试');
    expect(mapErrorCodeToMessage(20099)).toBe('登录状态已过期，请重新登录');
    expect(mapErrorCodeToMessage(30099)).toBe('智能分析暂不可用，请稍后重试');
    expect(mapErrorCodeToMessage(40099)).toBe('资料清晰度不足或内容过少，请重新拍摄');
    expect(mapErrorCodeToMessage(50099)).toBe('系统繁忙，请稍后重试');
  });

  it('should map network error flags to network error copy', () => {
    expect(mapErrorCodeToMessage('NETWORK_FAIL')).toBe('网络连接异常，请检查网络设置');
    expect(mapErrorCodeToMessage(-1)).toBe('网络连接异常，请检查网络设置');
  });

  it('should use custom fallback when provided for unknown codes', () => {
    expect(mapErrorCodeToMessage(99999, '自定义未知错误')).toBe('自定义未知错误');
    expect(mapErrorCodeToMessage('invalid_code', '保底错误')).toBe('保底错误');
    expect(mapErrorCodeToMessage(99999)).toBe('系统繁忙，请稍后重试');
  });

  it('should create AppError instance with correct code, message and details', () => {
    const err = new AppError(20002);
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(AppError);
    expect(err.code).toBe(20002);
    expect(err.message).toBe('无权访问此内容');
    expect(err.name).toBe('AppError');

    const customErr = new AppError(10001, '手机号码格式不合法', {
      details: { field: 'phone' },
      status_code: 422,
    });
    expect(customErr.code).toBe(10001);
    expect(customErr.message).toBe('手机号码格式不合法');
    expect(customErr.details).toEqual({ field: 'phone' });
    expect(customErr.status_code).toBe(422);
  });
});
