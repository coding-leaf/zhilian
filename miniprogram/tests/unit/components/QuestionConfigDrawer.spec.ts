import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import QuestionConfigDrawer from '@/subpackages/material/components/QuestionConfigDrawer.vue';
import * as questionApi from '@/api/question';
import type { QuestionGenerateResponse } from '@/types/question';

describe('QuestionConfigDrawer.vue', () => {
  const mockGenerateResponse: QuestionGenerateResponse = {
    batch_id: 'batch_001',
    material_id: 'mat_001',
    version_id: 'ver_001',
    knowledge_point_id: 'kp_001',
    total_generated: 2,
    qualified_count: 2,
    pending_count: 0,
    retry_count: 0,
    qualified_questions: [
      {
        id: 'q_001',
        material_id: 'mat_001',
        version_id: 'ver_001',
        knowledge_point_id: 'kp_001',
        question_type: 'single_choice',
        stem: '下列属于进程同步机制的是？',
        answer: '信号量机制',
        difficulty: 3,
        options: [
          { key: 'A', text: '信号量机制' },
          { key: 'B', text: '分页机制' },
        ],
      },
    ],
    pending_questions: [],
    quality_checks: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders correctly with default 10 questions and selected types', () => {
    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001', 'kp_002'],
      },
    });

    const text = wrapper.text();
    expect(text).toContain('定制出题配置');
    expect(text).toContain('已选考点: 2 项');
    expect(text).toContain('单选题');
    expect(text).toContain('多选题');
    expect(text).toContain('填空题');
    expect(text).toContain('主观简答题');
    expect(text).toContain('默认/自适应');

    const input = wrapper.find('.count-input');
    expect((input.element as HTMLInputElement).value).toBe('10');

    // Zero Emoji check
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });

  it('clamps question count between 1 and 50 with stepper and input', async () => {
    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    const stepBtns = wrapper.findAll('.step-btn');
    const minusBtn = stepBtns[0];
    const plusBtn = stepBtns[1];

    // Click minus: 10 -> 9
    await minusBtn.trigger('tap');
    expect((wrapper.find('.count-input').element as HTMLInputElement).value).toBe('9');

    // Click plus: 9 -> 10
    await plusBtn.trigger('tap');
    expect((wrapper.find('.count-input').element as HTMLInputElement).value).toBe('10');

    // Input boundary <= 0 -> clamped to 1
    const input = wrapper.find('.count-input');
    await input.trigger('input', { detail: { value: '0' } });
    expect((wrapper.find('.count-input').element as HTMLInputElement).value).toBe('1');

    // Input boundary > 50 -> clamped to 50
    await input.trigger('input', { detail: { value: '99' } });
    expect((wrapper.find('.count-input').element as HTMLInputElement).value).toBe('50');
  });

  it('enforces selecting at least 1 question type', async () => {
    const toastSpy = vi.spyOn(uni, 'showToast');
    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    const capsules = wrapper.findAll('.capsule-item');
    // Initially all 4 types selected
    // Unselect 3 types
    await capsules[0].trigger('tap'); // remove single_choice
    await capsules[1].trigger('tap'); // remove multiple_choice
    await capsules[2].trigger('tap'); // remove fill_in_blank

    // Now only short_answer remains
    await capsules[3].trigger('tap'); // try to remove short_answer
    expect(toastSpy).toHaveBeenCalledWith({
      title: '至少选择一种题型',
      icon: 'none',
    });
  });

  it('selects difficulty options', async () => {
    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    const diffCapsules = wrapper.findAll('.config-section')[3].findAll('.capsule-item');
    expect(diffCapsules.length).toBe(3);

    // Click "基础巩固"
    await diffCapsules[0].trigger('tap');
    expect(diffCapsules[0].classes()).toContain('active');

    // Click "进阶挑战"
    await diffCapsules[2].trigger('tap');
    expect(diffCapsules[2].classes()).toContain('active');
  });

  it('successfully generates questions and emits success event', async () => {
    const generateSpy = vi.spyOn(questionApi, 'generateQuestions').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockGenerateResponse,
    });
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        versionId: 'ver_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    const submitBtn = wrapper.find('.submit-btn');
    await submitBtn.trigger('tap');

    expect(generateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        material_id: 'mat_001',
        version_id: 'ver_001',
        knowledge_point_id: 'kp_001',
        count: 10,
        difficulty: 3,
      }),
    );

    await wrapper.vm.$nextTick();
    expect(toastSpy).toHaveBeenCalledWith({
      title: '出题成功',
      icon: 'success',
    });

    expect(wrapper.emitted('success')).toBeDefined();
    expect(wrapper.emitted('success')?.[0]?.[0]).toEqual(mockGenerateResponse.qualified_questions);
    expect(wrapper.emitted('update:visible')?.[0]?.[0]).toBe(false);
  });

  it('handles generate questions failure gracefully', async () => {
    vi.spyOn(questionApi, 'generateQuestions').mockRejectedValue(new Error('Network error'));
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    const submitBtn = wrapper.find('.submit-btn');
    await submitBtn.trigger('tap');

    await wrapper.vm.$nextTick();
    expect(toastSpy).toHaveBeenCalledWith({
      title: 'Network error',
      icon: 'none',
    });
  });

  it('handles generate questions failure with default message when error is empty', async () => {
    vi.spyOn(questionApi, 'generateQuestions').mockRejectedValue({});
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    const submitBtn = wrapper.find('.submit-btn');
    await submitBtn.trigger('tap');

    await wrapper.vm.$nextTick();
    expect(toastSpy).toHaveBeenCalledWith({
      title: '生成题目失败，请稍后重试',
      icon: 'none',
    });
  });
});
