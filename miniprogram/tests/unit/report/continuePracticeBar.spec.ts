import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ContinuePracticeBar from '@/subpackages/report/components/ContinuePracticeBar.vue';
import * as diagnosisApi from '@/api/diagnosis';
import { usePracticeStore } from '@/stores/practiceStore';
import type { PracticeSession } from '@/types/practice';
import type { ApiResponse } from '@/types/common';

describe('ContinuePracticeBar Component', () => {
  let pinia: ReturnType<typeof createPinia>;

  const mockSession: PracticeSession = {
    id: 'prac_sess_9001',
    title: '薄弱点强化练习',
    material_id: 'mat_001',
    status: 'idle',
    questions: [
      {
        id: 'q_1',
        stem: '测试题目1',
        question_type: 'single_choice',
        material_id: 'mat_001',
        version_id: 'v_1',
        knowledge_point_id: 'kp_1',
        difficulty: 1,
      },
    ],
  };

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders default button text for weakness mode', () => {
    const wrapper = mount(ContinuePracticeBar, {
      global: { plugins: [pinia] },
    });

    expect(wrapper.text()).toContain('一键强化薄弱点练习');
  });

  it('renders custom button text when provided', () => {
    const wrapper = mount(ContinuePracticeBar, {
      global: { plugins: [pinia] },
      props: { buttonText: '开始定制刷题' },
    });

    expect(wrapper.text()).toContain('开始定制刷题');
  });

  it('renders dynamic text for wrong_record mode with count', () => {
    const wrapper = mount(ContinuePracticeBar, {
      global: { plugins: [pinia] },
      props: {
        sourceType: 'wrong_record',
        count: 5,
        showInfo: true,
        tipText: '针对错题定向突破',
      },
    });

    expect(wrapper.text()).toContain('已选5道错题');
    expect(wrapper.text()).toContain('针对错题定向突破');
    expect(wrapper.text()).toContain('巩固已选 5 道错题');
  });

  it('renders dynamic text for weakness mode with count', () => {
    const wrapper = mount(ContinuePracticeBar, {
      global: { plugins: [pinia] },
      props: {
        sourceType: 'weakness',
        count: 3,
      },
    });

    expect(wrapper.text()).toContain('一键强化 3 个薄弱点');
  });

  it('generates UUIDv4 idempotency key and initiates continue practice', async () => {
    const continueSpy = vi.spyOn(diagnosisApi, 'continuePractice').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockSession,
    });
    const navigateSpy = vi.spyOn(uni, 'navigateTo');

    const wrapper = mount(ContinuePracticeBar, {
      global: { plugins: [pinia] },
      props: {
        materialId: 'mat_001',
        knowledgePointIds: ['kp_1', 'kp_2'],
        sourceReportId: 'rep_1001',
        title: '专项薄弱突破',
      },
    });

    const btn = wrapper.find('.continue-btn');
    await btn.trigger('tap');

    expect(continueSpy).toHaveBeenCalledTimes(1);
    const calledPayload = continueSpy.mock.calls[0][0];
    expect(calledPayload.material_id).toBe('mat_001');
    expect(calledPayload.knowledge_point_ids).toEqual(['kp_1', 'kp_2']);
    expect(calledPayload.source_report_id).toBe('rep_1001');
    expect(calledPayload.title).toBe('专项薄弱突破');
    expect(calledPayload.idempotency_key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );

    const practiceStore = usePracticeStore();
    expect(practiceStore.sessionId).toBe('prac_sess_9001');
    expect(practiceStore.questions).toHaveLength(1);

    expect(navigateSpy).toHaveBeenCalledWith({
      url: '/subpackages/practice/pages/session/index?id=prac_sess_9001',
    });

    expect(wrapper.emitted('success')).toBeTruthy();
    expect(wrapper.emitted('success')![0][0]).toEqual(mockSession);
  });

  it('defends against duplicate rapid clicks within 500ms', async () => {
    let resolveApi: (value: unknown) => void;
    const apiPromise = new Promise((resolve) => {
      resolveApi = resolve;
    });

    const continueSpy = vi
      .spyOn(diagnosisApi, 'continuePractice')
      .mockReturnValue(apiPromise as Promise<ApiResponse<PracticeSession>>);

    const wrapper = mount(ContinuePracticeBar, {
      global: { plugins: [pinia] },
      props: {
        materialId: 'mat_001',
        knowledgePointIds: ['kp_1'],
      },
    });

    const btn = wrapper.find('.continue-btn');
    // First click
    await btn.trigger('tap');
    expect(continueSpy).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain('正在生成练习...');

    // Second immediate click
    await btn.trigger('tap');
    // Still 1 call due to isSubmitting lock & debounce
    expect(continueSpy).toHaveBeenCalledTimes(1);

    // Resolve API
    resolveApi!({
      code: 0,
      message: 'success',
      data: mockSession,
    });
    await vi.waitFor(() => {
      expect(wrapper.emitted('success')).toBeTruthy();
    });
  });

  it('does not trigger API call when disabled prop is true', async () => {
    const continueSpy = vi.spyOn(diagnosisApi, 'continuePractice');

    const wrapper = mount(ContinuePracticeBar, {
      global: { plugins: [pinia] },
      props: {
        disabled: true,
      },
    });

    const btn = wrapper.find('.continue-btn');
    await btn.trigger('tap');

    expect(continueSpy).not.toHaveBeenCalled();
    expect(wrapper.emitted('click')).toBeFalsy();
  });

  it('handles API failure by showing toast and emitting error', async () => {
    vi.spyOn(diagnosisApi, 'continuePractice').mockRejectedValue(new Error('题库组卷失败'));
    const toastSpy = vi.spyOn(uni, 'showToast');

    const wrapper = mount(ContinuePracticeBar, {
      global: { plugins: [pinia] },
      props: {
        knowledgePointIds: ['kp_1'],
      },
    });

    const btn = wrapper.find('.continue-btn');
    await btn.trigger('tap');

    await vi.waitFor(() => {
      expect(wrapper.emitted('error')).toBeTruthy();
    });

    expect(toastSpy).toHaveBeenCalledWith({
      title: '题库组卷失败',
      icon: 'none',
    });
  });
});
