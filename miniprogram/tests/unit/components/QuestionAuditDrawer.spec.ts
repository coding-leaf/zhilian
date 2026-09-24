import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import QuestionAuditDrawer from '@/subpackages/material/components/QuestionAuditDrawer.vue';
import * as questionApi from '@/api/question';
import type { QuestionAuditLogsResponse } from '@/types/question';

describe('QuestionAuditDrawer.vue', () => {
  const mockAuditResponse: QuestionAuditLogsResponse = {
    question_id: 'q_test_101',
    logs: [
      {
        id: 'log_001',
        question_id: 'q_test_101',
        action: 'CREATE',
        changed_fields: ['stem', 'options', 'answer'],
        before_payload: {},
        after_payload: {
          stem: '初始生成的题目题干',
          answer: '初始标准答案',
        },
        reason: '智能出题初次生成',
        created_at: '2026-09-01T10:00:00Z',
      },
      {
        id: 'log_002',
        question_id: 'q_test_101',
        action: 'EDIT',
        changed_fields: ['stem'],
        before_payload: {
          stem: '初始生成的题目题干',
        },
        after_payload: {
          stem: '修正后的题目题干内容',
        },
        reason: '修正错别字与逻辑表述',
        created_at: '2026-09-02T14:30:00Z',
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads and renders audit timeline logs with actions, reasons and diffs', async () => {
    const auditSpy = vi.spyOn(questionApi, 'fetchQuestionAuditLogs').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockAuditResponse,
    });

    const wrapper = mount(QuestionAuditDrawer, {
      props: {
        visible: true,
        questionId: 'q_test_101',
      },
    });

    expect(auditSpy).toHaveBeenCalledWith('q_test_101');

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 20));

    const text = wrapper.text();
    expect(text).toContain('题目修改审计记录');
    expect(text).toContain('生成入库');
    expect(text).toContain('人工编辑');
    expect(text).toContain('智能出题初次生成');
    expect(text).toContain('修正错别字与逻辑表述');
    expect(text).toContain('修改前');
    expect(text).toContain('修改后');

    // Zero Emoji check
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });

  it('renders empty state when there are no logs', async () => {
    vi.spyOn(questionApi, 'fetchQuestionAuditLogs').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        question_id: 'q_empty',
        logs: [],
      },
    });

    const wrapper = mount(QuestionAuditDrawer, {
      props: {
        visible: true,
        questionId: 'q_empty',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(wrapper.text()).toContain('暂无修改审计记录');
  });

  it('handles audit fetch failure gracefully', async () => {
    const toastSpy = vi.spyOn(uni, 'showToast');
    vi.spyOn(questionApi, 'fetchQuestionAuditLogs').mockRejectedValue(new Error('Network error'));

    const wrapper = mount(QuestionAuditDrawer, {
      props: {
        visible: true,
        questionId: 'q_fail',
      },
    });

    await wrapper.vm.$nextTick();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(toastSpy).toHaveBeenCalledWith({
      title: '加载审计日志失败',
      icon: 'none',
    });
  });

  it('emits close event when close button or finish button is clicked', async () => {
    vi.spyOn(questionApi, 'fetchQuestionAuditLogs').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockAuditResponse,
    });

    const wrapper = mount(QuestionAuditDrawer, {
      props: {
        visible: true,
        questionId: 'q_test_101',
      },
    });

    const closeBtn = wrapper.find('.close-btn');
    await closeBtn.trigger('tap');

    expect(wrapper.emitted('close')).toBeDefined();
    expect(wrapper.emitted('update:visible')?.[0]?.[0]).toBe(false);
  });
});
