import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount } from '@vue/test-utils';
import TransitionPage from '@/subpackages/practice/pages/transition/index.vue';
import * as diagnosisApi from '@/api/diagnosis';
import type { DiagnosisReport } from '@/types/report';

describe('Practice Transition Page (transition/index.vue)', () => {
  const practiceId = 'prac_trans_001';

  beforeEach(() => {
    vi.useFakeTimers();
    uni.redirectTo = vi.fn() as unknown as typeof uni.redirectTo;
    uni.switchTab = vi.fn() as unknown as typeof uni.switchTab;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('renders 3-stage animated steps initially', () => {
    vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 1,
      message: 'generating',
      data: null as unknown as DiagnosisReport,
    });

    const wrapper = mount(TransitionPage, {
      props: { practiceId },
    });
    expect(wrapper.text()).toContain('AI 助教正在诊断');
    expect(wrapper.text()).toContain('客观题精准核验');
    expect(wrapper.text()).toContain('主观题多维采分对齐');
    expect(wrapper.text()).toContain('学情诊断画像构建');

    const stepRows = wrapper.findAll('.step-row');
    expect(stepRows.length).toBe(3);
    expect(stepRows[0].classes()).toContain('step-active');
  });

  it('polls diagnosis report and redirects to detail page upon completion', async () => {
    const mockReport: Partial<DiagnosisReport> = {
      id: 'rep_1001',
      practice_id: practiceId,
      overall_score: 85,
    };

    let callCount = 0;
    vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockImplementation(() => {
      callCount += 1;
      if (callCount < 2) {
        return Promise.resolve({
          code: 1,
          message: 'processing',
          data: null as unknown as DiagnosisReport,
        });
      }
      return Promise.resolve({
        code: 0,
        message: 'success',
        data: mockReport as DiagnosisReport,
      });
    });

    mount(TransitionPage, {
      props: { practiceId },
    });

    // Initial check (call 1)
    await vi.advanceTimersByTimeAsync(1500);

    // Second check (call 2 -> resolves report)
    await vi.advanceTimersByTimeAsync(1500);
    await vi.advanceTimersByTimeAsync(600); // 500ms debounce redirect

    expect(uni.redirectTo).toHaveBeenCalledWith({
      url: expect.stringContaining('/subpackages/report/pages/detail/index'),
    });
  });

  it('degrades to safe fallback actions after polling threshold is exceeded', async () => {
    vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 1,
      message: 'still processing',
      data: null as unknown as DiagnosisReport,
    });

    const wrapper = mount(TransitionPage, {
      props: { practiceId },
    });

    // Fast-forward 20 polling cycles (20 * 1500ms = 30s)
    for (let i = 0; i < 21; i++) {
      await vi.advanceTimersByTimeAsync(1500);
    }

    expect(wrapper.text()).toContain('诊断分析排队中');
    expect(wrapper.text()).toContain('前往学情看板');

    await wrapper.find('.btn-primary').trigger('tap');
    expect(uni.switchTab).toHaveBeenCalledWith({
      url: '/pages/review/index',
    });

    await wrapper.find('.btn-text-link').trigger('tap');
    expect(uni.switchTab).toHaveBeenCalledWith({
      url: '/pages/index/index',
    });
  });
});
