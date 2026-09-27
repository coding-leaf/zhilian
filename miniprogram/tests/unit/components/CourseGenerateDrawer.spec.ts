import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import CourseGenerateDrawer from '@/components/course/CourseGenerateDrawer.vue';
import CourseKnowledgePointPicker from '@/components/course/CourseKnowledgePointPicker.vue';
import * as questionApi from '@/api/question';
import * as folderApi from '@/api/folder';
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

const mockGenerateResponse: QuestionGenerateResponse = {
  batch_id: 'batch_1',
  total_generated: 1,
  qualified_count: 1,
  pending_count: 0,
  retry_count: 0,
  qualified_questions: [
    {
      id: 'q_1',
      material_id: 'mat_1',
      version_id: 'ver_1',
      knowledge_point_id: 'kp_1',
      question_type: 'single_choice',
      stem: '课程范围生成的题目',
      answer: 'A',
      difficulty: 3,
    },
  ],
  pending_questions: [],
  quality_checks: [],
};

function mountDrawer(props: Record<string, unknown> = {}) {
  return mount(CourseGenerateDrawer, {
    props: { visible: true, folderId: 'f1', ...props },
  });
}

describe('CourseGenerateDrawer.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(folderApi, 'fetchFolderKnowledgePoints').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { folder_id: 'f1', groups: [], total: 0 },
    });
  });

  it('renders defaults: 10 questions, four types and adaptive difficulty', () => {
    const wrapper = mountDrawer();

    const text = wrapper.text();
    expect(text).toContain('智能出题');
    expect(text).toContain('单选题');
    expect(text).toContain('多选题');
    expect(text).toContain('判断题');
    expect(text).toContain('主观简答题');
    expect(text).toContain('默认/自适应');
    expect((wrapper.find('.count-input').element as HTMLInputElement).value).toBe('10');

    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });

  it('clamps the question count between 1 and 20', async () => {
    const wrapper = mountDrawer();
    const stepBtns = wrapper.findAll('.step-btn');

    await stepBtns[0].trigger('tap');
    expect((wrapper.find('.count-input').element as HTMLInputElement).value).toBe('9');
    await stepBtns[1].trigger('tap');
    expect((wrapper.find('.count-input').element as HTMLInputElement).value).toBe('10');

    const input = wrapper.find('.count-input');
    await input.trigger('input', { detail: { value: '0' } });
    expect((wrapper.find('.count-input').element as HTMLInputElement).value).toBe('1');
    await input.trigger('input', { detail: { value: '99' } });
    expect((wrapper.find('.count-input').element as HTMLInputElement).value).toBe('20');
  });

  it('submits the folder-scoped generation payload and emits success', async () => {
    const generateSpy = vi.spyOn(questionApi, 'generateQuestions').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockGenerateResponse,
    });

    const wrapper = mountDrawer();
    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(generateSpy).toHaveBeenCalledWith({
      folder_id: 'f1',
      count: 10,
      difficulty: 3,
      question_types: ['single_choice', 'multiple_choice', 'true_false', 'short_answer'],
    });
    expect(wrapper.emitted('success')?.[0]?.[0]).toBe('f1');
    expect(wrapper.emitted('update:visible')?.[0]?.[0]).toBe(false);
  });

  it('blocks duplicate submits while a generation request is in flight', async () => {
    const deferred = createDeferred<ApiResponse<QuestionGenerateResponse>>();
    const generateSpy = vi
      .spyOn(questionApi, 'generateQuestions')
      .mockReturnValue(deferred.promise);

    const wrapper = mountDrawer();
    const submitBtn = wrapper.find('.submit-btn');
    await submitBtn.trigger('tap');
    await submitBtn.trigger('tap');
    expect(generateSpy).toHaveBeenCalledTimes(1);
    expect(wrapper.find('.submit-btn').classes()).toContain('disabled');

    deferred.resolve({ code: 200, message: 'success', data: mockGenerateResponse });
    await flushPromises();
  });

  it('keeps the drawer open when no qualified questions are produced', async () => {
    vi.spyOn(questionApi, 'generateQuestions').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { ...mockGenerateResponse, qualified_count: 0, qualified_questions: [] },
    });
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mountDrawer();
    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(toastSpy).toHaveBeenCalledWith({
      title: '本次未产出合格题目，可调整题量或考点后重试',
      icon: 'none',
    });
    expect(wrapper.emitted('success')).toBeUndefined();
    expect(wrapper.find('.course-generate-mask').exists()).toBe(true);
    expect(wrapper.find('.submit-btn').classes()).not.toContain('disabled');
  });

  it('shows a network retry message and keeps the config for retry', async () => {
    vi.spyOn(questionApi, 'generateQuestions').mockRejectedValue(new AppError(-1));
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mountDrawer();
    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(toastSpy).toHaveBeenCalledWith({ title: '网络异常，请重试', icon: 'none' });
    expect(wrapper.find('.course-generate-mask').exists()).toBe(true);
  });

  it('shows the backend business message for business errors', async () => {
    vi.spyOn(questionApi, 'generateQuestions').mockRejectedValue(
      new AppError(40003, '当前课程没有可用考点，暂无法出题'),
    );
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mountDrawer();
    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(toastSpy).toHaveBeenCalledWith({
      title: '当前课程没有可用考点，暂无法出题',
      icon: 'none',
    });
  });

  it('requires a folder id before submitting', async () => {
    const generateSpy = vi.spyOn(questionApi, 'generateQuestions');
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mountDrawer({ folderId: '' });
    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(generateSpy).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith({ title: '缺少课程信息', icon: 'none' });
  });

  it('passes selected knowledge point ids to the generation request (B4)', async () => {
    const generateSpy = vi.spyOn(questionApi, 'generateQuestions').mockResolvedValue({
      code: 200,
      message: 'success',
      data: mockGenerateResponse,
    });

    const wrapper = mountDrawer();
    const picker = wrapper.findComponent(CourseKnowledgePointPicker);
    picker.vm.$emit('update:selectedIds', ['kp_1', 'kp_2']);
    await wrapper.vm.$nextTick();

    await wrapper.find('.submit-btn').trigger('tap');
    await flushPromises();

    expect(generateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ folder_id: 'f1', knowledge_point_ids: ['kp_1', 'kp_2'] }),
    );
  });

  it('allows closing the drawer while generation is in flight (B2)', async () => {
    const deferred = createDeferred<ApiResponse<QuestionGenerateResponse>>();
    vi.spyOn(questionApi, 'generateQuestions').mockReturnValue(deferred.promise);

    const wrapper = mountDrawer();
    await wrapper.find('.submit-btn').trigger('tap');

    wrapper.vm.handleClose();
    expect(wrapper.emitted('update:visible')?.[0]?.[0]).toBe(false);

    deferred.resolve({ code: 200, message: 'success', data: mockGenerateResponse });
    await flushPromises();
  });
});
