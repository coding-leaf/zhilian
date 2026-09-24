import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import QuestionEditDrawer from '@/subpackages/material/components/QuestionEditDrawer.vue';
import * as questionApi from '@/api/question';
import type { QuestionItem } from '@/types/question';

describe('QuestionEditDrawer.vue', () => {
  const mockQuestion: QuestionItem = {
    id: 'q_test_101',
    material_id: 'mat_001',
    version_id: 'ver_001',
    knowledge_point_id: 'kp_001',
    question_type: 'single_choice',
    stem: '以下哪种算法用于死锁避免？',
    answer: '银行家算法',
    analysis: '银行家算法通过安全性检查实现死锁避免。',
    difficulty: 3,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders question data and initial empty reason input', () => {
    const wrapper = mount(QuestionEditDrawer, {
      props: {
        visible: true,
        question: mockQuestion,
      },
    });

    const text = wrapper.text();
    expect(text).toContain('编辑题目');
    expect(text).toContain('题干内容');
    expect(text).toContain('参考答案');
    expect(text).toContain('修改原因');

    const textareas = wrapper.findAll('.form-textarea');
    expect((textareas[0].element as HTMLTextAreaElement).value).toBe(mockQuestion.stem);
    expect((textareas[1].element as HTMLTextAreaElement).value).toBe(mockQuestion.answer);

    const input = wrapper.find('.form-input');
    expect((input.element as HTMLInputElement).value).toBe('');

    // Zero Emoji check
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });

  it('blocks submission and shows toast when reason is shorter than 2 chars', async () => {
    const toastSpy = vi.spyOn(uni, 'showToast');
    const updateSpy = vi.spyOn(questionApi, 'updateQuestion');

    const wrapper = mount(QuestionEditDrawer, {
      props: {
        visible: true,
        question: mockQuestion,
      },
    });

    const submitBtn = wrapper.find('.submit-btn');
    await submitBtn.trigger('tap');

    expect(toastSpy).toHaveBeenCalledWith({
      title: '修改原因不得少于2个字符',
      icon: 'none',
    });
    expect(updateSpy).not.toHaveBeenCalled();

    // With 1 char
    const input = wrapper.find('.form-input');
    await input.setValue('改');
    await submitBtn.trigger('tap');
    expect(toastSpy).toHaveBeenCalledWith({
      title: '修改原因不得少于2个字符',
      icon: 'none',
    });
    expect(updateSpy).not.toHaveBeenCalled();
  });

  it('blocks submission when stem or answer is cleared', async () => {
    const toastSpy = vi.spyOn(uni, 'showToast');
    const updateSpy = vi.spyOn(questionApi, 'updateQuestion');

    const wrapper = mount(QuestionEditDrawer, {
      props: {
        visible: true,
        question: mockQuestion,
      },
    });

    const textareas = wrapper.findAll('.form-textarea');
    await textareas[0].setValue(''); // clear stem

    const input = wrapper.find('.form-input');
    await input.setValue('优化题干阐述');

    const submitBtn = wrapper.find('.submit-btn');
    await submitBtn.trigger('tap');

    expect(toastSpy).toHaveBeenCalledWith({
      title: '题干内容不能为空',
      icon: 'none',
    });
    expect(updateSpy).not.toHaveBeenCalled();
  });

  it('submits update successfully and emits updated event', async () => {
    const toastSpy = vi.spyOn(uni, 'showToast');
    const updateSpy = vi.spyOn(questionApi, 'updateQuestion').mockResolvedValue({
      code: 200,
      message: 'success',
      data: {
        ...mockQuestion,
        stem: '修改后的题干内容',
        reason: '修正错别字',
      },
    });

    const wrapper = mount(QuestionEditDrawer, {
      props: {
        visible: true,
        question: mockQuestion,
      },
    });

    const textareas = wrapper.findAll('.form-textarea');
    await textareas[0].setValue('修改后的题干内容');

    const input = wrapper.find('.form-input');
    await input.setValue('修正错别字');

    const submitBtn = wrapper.find('.submit-btn');
    await submitBtn.trigger('tap');

    expect(updateSpy).toHaveBeenCalledWith(
      'q_test_101',
      expect.objectContaining({
        stem: '修改后的题干内容',
        reason: '修正错别字',
      }),
    );

    await wrapper.vm.$nextTick();
    expect(toastSpy).toHaveBeenCalledWith({
      title: '修改已保存',
      icon: 'success',
    });
    expect(wrapper.emitted('updated')).toBeDefined();
    expect(wrapper.emitted('updated')?.[0]?.[0]).toMatchObject({
      stem: '修改后的题干内容',
    });
    expect(wrapper.emitted('update:visible')?.[0]?.[0]).toBe(false);
  });

  it('handles update failure gracefully without crash', async () => {
    const toastSpy = vi.spyOn(uni, 'showToast');
    vi.spyOn(questionApi, 'updateQuestion').mockRejectedValue(new Error('Update failed'));

    const wrapper = mount(QuestionEditDrawer, {
      props: {
        visible: true,
        question: mockQuestion,
      },
    });

    const input = wrapper.find('.form-input');
    await input.setValue('修正错别字');

    const submitBtn = wrapper.find('.submit-btn');
    await submitBtn.trigger('tap');

    await wrapper.vm.$nextTick();
    expect(toastSpy).toHaveBeenCalledWith({
      title: '保存修改失败，请重试',
      icon: 'none',
    });
  });
});
