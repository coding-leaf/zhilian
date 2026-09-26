import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import QuestionConfigDrawer from '@/subpackages/material/components/QuestionConfigDrawer.vue';
import * as questionApi from '@/api/question';
import { AppError } from '@/utils/error';
import type { ApiResponse } from '@/types/common';
import type { QuestionGenerateResponse } from '@/types/question';

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

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

  afterEach(() => {
    vi.useRealTimers();
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

  it('shows the in-progress panel with stage text and elapsed timer, blocking duplicate submit', async () => {
    const deferred = createDeferred<ApiResponse<QuestionGenerateResponse>>();
    const generateSpy = vi
      .spyOn(questionApi, 'generateQuestions')
      .mockReturnValue(deferred.promise);

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

    expect(wrapper.find('.progress-panel').exists()).toBe(true);
    expect(wrapper.text()).toContain('检索切片');
    expect(wrapper.text()).toContain('命制题目');
    expect(wrapper.text()).toContain('质检门禁');
    expect(wrapper.text()).toContain('已等待 0 秒');

    // Duplicate taps must not trigger another generation request
    await submitBtn.trigger('tap');
    await submitBtn.trigger('tap');
    expect(generateSpy).toHaveBeenCalledTimes(1);

    deferred.resolve({ code: 200, message: 'success', data: mockGenerateResponse });
    await flushPromises();
  });

  it('advances stages, ticks elapsed seconds and clears timers on unmount', async () => {
    vi.useFakeTimers();
    const deferred = createDeferred<ApiResponse<QuestionGenerateResponse>>();
    vi.spyOn(questionApi, 'generateQuestions').mockReturnValue(deferred.promise);

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    await wrapper.find('.submit-btn').trigger('tap');

    await vi.advanceTimersByTimeAsync(3000);
    expect(wrapper.text()).toContain('已等待 3 秒');

    await vi.advanceTimersByTimeAsync(1000);
    expect(wrapper.find('.progress-stage.active').text()).toBe('命制题目');

    expect(vi.getTimerCount()).toBeGreaterThan(0);
    wrapper.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('blocks closing while generation is in progress', async () => {
    const deferred = createDeferred<ApiResponse<QuestionGenerateResponse>>();
    vi.spyOn(questionApi, 'generateQuestions').mockReturnValue(deferred.promise);
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    await wrapper.find('.submit-btn').trigger('tap');
    await wrapper.find('.close-btn').trigger('tap');

    expect(toastSpy).toHaveBeenCalledWith({
      title: '正在生成题目，请稍候',
      icon: 'none',
    });
    expect(wrapper.emitted('close')).toBeUndefined();
    expect(wrapper.find('.drawer-mask').exists()).toBe(true);

    deferred.resolve({ code: 200, message: 'success', data: mockGenerateResponse });
    await flushPromises();
  });

  it('successfully generates questions, closes the drawer and navigates to the question page', async () => {
    const generateSpy = vi.spyOn(questionApi, 'generateQuestions').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockGenerateResponse,
    });
    const toastSpy = vi.spyOn(uni, 'showToast');
    const navigateSpy = vi.spyOn(uni, 'navigateTo');

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

    await flushPromises();

    expect(toastSpy).toHaveBeenCalledWith({
      title: '出题成功',
      icon: 'success',
    });

    expect(wrapper.emitted('success')).toBeDefined();
    expect(wrapper.emitted('success')?.[0]?.[0]).toEqual(mockGenerateResponse.qualified_questions);
    expect(wrapper.emitted('update:visible')?.[0]?.[0]).toBe(false);

    expect(navigateSpy).toHaveBeenCalledWith({
      url: '/subpackages/material/pages/questions/index?material_id=mat_001',
      fail: expect.any(Function),
    });
  });

  it('submits all selected knowledge points and shows the distribution hint', async () => {
    const generateSpy = vi.spyOn(questionApi, 'generateQuestions').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockGenerateResponse,
    });

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        versionId: 'ver_001',
        selectedKnowledgeIds: ['kp_001', 'kp_002', 'kp_003'],
      },
    });

    expect(wrapper.text()).toContain('已选 3 个考点，共 10 题');

    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(generateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        material_id: 'mat_001',
        version_id: 'ver_001',
        knowledge_point_id: 'kp_001',
        knowledge_point_ids: ['kp_001', 'kp_002', 'kp_003'],
        count: 10,
      }),
    );
  });

  it('warns when the requested count is lower than the number of knowledge points', async () => {
    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001', 'kp_002', 'kp_003'],
      },
    });

    const input = wrapper.find('.count-input');
    await input.trigger('input', { detail: { value: '2' } });
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain('每个考点至少 1 题，实际将生成 3 题');
  });

  it('shows a fallback toast when the question page fails to open', async () => {
    vi.spyOn(questionApi, 'generateQuestions').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockGenerateResponse,
    });
    const toastSpy = vi.spyOn(uni, 'showToast');
    const navigateSpy = vi.fn();
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.navigateTo = navigateSpy;

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    const options = navigateSpy.mock.calls[0][0] as { fail?: () => void };
    expect(typeof options.fail).toBe('function');
    options.fail?.();

    expect(toastSpy).toHaveBeenCalledWith({
      title: '题目页打开失败，请稍后重试',
      icon: 'none',
    });
  });

  it('keeps the drawer open with a retry hint when no qualified questions are produced', async () => {
    vi.spyOn(questionApi, 'generateQuestions').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { ...mockGenerateResponse, qualified_count: 0, qualified_questions: [] },
    });
    const toastSpy = vi.spyOn(uni, 'showToast');
    const navigateSpy = vi.spyOn(uni, 'navigateTo');

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(toastSpy).toHaveBeenCalledWith({
      title: '本次未产出合格题目，可调整考点或题量后重试',
      icon: 'none',
    });
    expect(wrapper.emitted('success')).toBeUndefined();
    expect(wrapper.emitted('update:visible')).toBeUndefined();
    expect(navigateSpy).not.toHaveBeenCalled();
    expect(wrapper.find('.drawer-mask').exists()).toBe(true);
  });

  it('shows a network retry message for network or timeout errors', async () => {
    vi.spyOn(questionApi, 'generateQuestions').mockRejectedValue(new AppError(-1));
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(toastSpy).toHaveBeenCalledWith({
      title: '网络异常，请重试',
      icon: 'none',
    });
    // Configuration is preserved and the drawer stays open for retry
    expect(wrapper.find('.drawer-mask').exists()).toBe(true);
    expect(wrapper.find('.submit-btn').classes()).not.toContain('disabled');
  });

  it('shows the backend message for business errors', async () => {
    vi.spyOn(questionApi, 'generateQuestions').mockRejectedValue(
      new AppError(40003, '当前资料没有可用知识切片，暂无法出题'),
    );
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mount(QuestionConfigDrawer, {
      props: {
        visible: true,
        materialId: 'mat_001',
        selectedKnowledgeIds: ['kp_001'],
      },
    });

    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(toastSpy).toHaveBeenCalledWith({
      title: '当前资料没有可用知识切片，暂无法出题',
      icon: 'none',
    });
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

    await flushPromises();
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

    await flushPromises();
    expect(toastSpy).toHaveBeenCalledWith({
      title: '生成题目失败，请稍后重试',
      icon: 'none',
    });
  });
});
