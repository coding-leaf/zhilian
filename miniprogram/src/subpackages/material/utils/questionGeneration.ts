/**
 * 出题生成跳转契约与错误文案工具。
 *
 * - 统一题目页路径与主键参数名 `material_id`，接收页兼容 `materialId` / `id`；
 * - 跳转失败必须给出兜底提示，禁止静默无响应；
 * - 按错误类型分类出题失败文案（网络/超时 vs 业务错误）。
 * 单文件 <= 300 行，零 Emoji。
 */

import { AppError } from '@/utils/error';

/** 独立题目页路径，主键参数统一使用 material_id。 */
export const QUESTION_PAGE_PATH = '/subpackages/material/pages/questions/index';

/** 题型选项。 */
export const QUESTION_TYPE_OPTIONS = [
  { label: '单选题', value: 'single_choice' },
  { label: '多选题', value: 'multiple_choice' },
  { label: '填空题', value: 'fill_in_blank' },
  { label: '主观简答题', value: 'short_answer' },
];

/** 难度倾向选项。 */
export const DIFFICULTY_OPTIONS = [
  { label: '基础巩固', value: 2 },
  { label: '默认/自适应', value: 3 },
  { label: '进阶挑战', value: 4 },
];

const GENERATE_FAIL_MESSAGE = '生成题目失败，请稍后重试';
const NETWORK_FAIL_MESSAGE = '网络异常，请重试';

/**
 * 跳转到独立题目页，并携带失败兜底提示。
 *
 * @param materialId 资料主键，为空时不跳转。
 */
export function navigateToQuestionPage(materialId: string): void {
  if (!materialId) {
    return;
  }
  uni.navigateTo({
    url: `${QUESTION_PAGE_PATH}?material_id=${materialId}`,
    fail: () => {
      uni.showToast({ title: '题目页打开失败，请稍后重试', icon: 'none' });
    },
  });
}

/**
 * 按错误类型解析出题失败提示文案。
 *
 * @param err 捕获到的未知错误。
 * @returns 面向用户的自然文案。
 */
export function resolveGenerateErrorMessage(err: unknown): string {
  if (err instanceof AppError) {
    return err.code === -1 ? NETWORK_FAIL_MESSAGE : err.message || GENERATE_FAIL_MESSAGE;
  }
  const payload = err as { message?: string; errMsg?: string } | null;
  return payload?.message || payload?.errMsg || GENERATE_FAIL_MESSAGE;
}
