import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { onLoad } from '@dcloudio/uni-app';
import ReportDetailPage from '@/subpackages/report/pages/detail/index.vue';
import * as diagnosisApi from '@/api/diagnosis';
import * as practiceApi from '@/api/practice';
import { useReportStore } from '@/stores/reportStore';
import type { DiagnosisReport, AttemptGradingItem } from '@/types/report';
import type { PracticeSession } from '@/types/practice';

describe('ReportDetailPage (subpackages/report/pages/detail/index.vue)', () => {
  let pinia: ReturnType<typeof createPinia>;

  const mockReport: DiagnosisReport = {
    id: 'rep_1001',
    practice_id: 'prac_1001',
    overall_score: 85,
    score_rate: 0.85,
    mastery_rate: 85,
    mastery_before: 0.65,
    mastery_after: 0.85,
    pending_regrade_count: 1,
    is_structure_degraded: false,
    created_at: '2026-09-25T11:00:00Z',
    weak_points: [
      {
        knowledge_point_id: 'kp_1',
        knowledge_name: '二叉树中序遍历',
        current_score: 0.35,
        previous_score: 0.55,
        score_delta: -0.2,
        priority: 1,
        cause_explanation: '递归基设计不熟练',
        actionable_advice: '建议重点练习非递归遍历与线索二叉树',
      },
    ],
  };

  const mockPracticeItems: AttemptGradingItem[] = [
    {
      attempt_item_id: 'att_01',
      order_index: 1,
      status: 'correct',
      score: 1.0,
      max_score: 1.0,
      is_answered: true,
      user_answer: 'A',
      question_snapshot: {
        stem: '在平衡二叉树（AVL树）中，任意节点的左右子树高度差绝对值不超过？',
        question_type: 'single_choice',
        answer: '1',
        analysis: 'AVL树的平衡因子定义为左子树与右子树高度差，绝对值必须<=1。',
        source_snippet: {
          chapter_title: '第 5 章 树形数据结构',
          page_index: 108,
          snippet_content: 'AVL树是一棵自平衡二叉搜索树，任何节点的平衡因子只能是-1、0或1。',
        },
        hit_keywords: ['平衡因子', 'AVL树'],
      },
    },
    {
      attempt_item_id: 'att_02',
      order_index: 2,
      status: 'pending_regrade',
      score: null,
      max_score: 5.0,
      is_answered: true,
      user_answer: '二叉树中序遍历先访问左子树，后访问根节点，再访问右子树。',
      question_snapshot: {
        stem: '请详细阐述二叉树中序遍历的遍历序列特征与递归定义。',
        question_type: 'short_answer',
        answer: '先递归遍历左子树，然后访问根节点，最后递归遍历右子树。',
        analysis: '对于二叉搜索树，中序遍历序列严格单调递增。',
        grading_rubric: {
          左子树判定: '明确指出先递归左子树（2分）',
          根节点访问: '指出居中访问根节点（1分）',
          右子树判定: '指出最后递归右子树（2分）',
        },
        hit_keywords: ['中序遍历', '根节点'],
        missing_keywords: ['递归定义'],
      },
    },
  ];

  function setupPracticeMock() {
    return vi.spyOn(practiceApi, 'fetchPracticeSession').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'prac_1001',
        title: '树结构专项练习',
        material_id: 'mat_001',
        status: 'graded',
        questions: [],
        items: mockPracticeItems,
        time_elapsed_seconds: 125,
      } as unknown as PracticeSession,
    });
  }

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    vi.restoreAllMocks();
  });

  it('renders loading skeleton initially before data resolves', () => {
    vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockReturnValue(new Promise(() => {}));
    vi.spyOn(practiceApi, 'fetchPracticeSession').mockReturnValue(new Promise(() => {}));

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    expect(wrapper.find('.skeleton-wrapper').exists()).toBe(true);
    expect(wrapper.find('.report-content').exists()).toBe(false);
  });

  it('renders empty state when no practice id is provided (BUG-DIAG-022)', async () => {
    const reportSpy = vi.spyOn(diagnosisApi, 'fetchDiagnosisReport');

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.empty-state').exists()).toBe(true);
    });

    expect(wrapper.text()).toContain('暂无诊断报告数据');
    expect(wrapper.find('.back-home-btn').exists()).toBe(true);
    expect(wrapper.find('.empty-btn.primary').exists()).toBe(true);
    expect(wrapper.find('.skeleton-wrapper').exists()).toBe(false);
    expect(wrapper.find('.report-content').exists()).toBe(false);
    expect(reportSpy).not.toHaveBeenCalled();
  });

  it('renders error state and retries successfully', async () => {
    const fetchSpy = vi
      .spyOn(diagnosisApi, 'fetchDiagnosisReport')
      .mockRejectedValueOnce(new Error('网络请求超时'))
      .mockResolvedValueOnce({
        code: 0,
        message: 'success',
        data: mockReport,
      });

    setupPracticeMock();

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.error-state').exists()).toBe(true);
    });

    expect(wrapper.text()).toContain('网络请求超时');

    const retryBtn = wrapper.find('.retry-btn');
    await retryBtn.trigger('tap');

    await vi.waitFor(() => {
      expect(wrapper.find('.report-content').exists()).toBe(true);
    });

    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('renders full diagnosis page with summary, weak points, and results', async () => {
    vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockReport,
    });
    setupPracticeMock();

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.report-content').exists()).toBe(true);
    });

    const reportStore = useReportStore();
    expect(reportStore.currentReport?.id).toBe('rep_1001');

    // DiagnosisSummaryCard assertions
    expect(wrapper.text()).toContain('85');
    expect(wrapper.find('.pending-regrade-banner').exists()).toBe(true);
    expect(wrapper.text()).toContain('当前有 1 道主观题待重新判题');

    // WeakKnowledgeCard assertions
    expect(wrapper.text()).toContain('二叉树中序遍历');
    expect(wrapper.text()).toContain('退步');
    expect(wrapper.text()).toContain('递归基设计不熟练');

    // GradingResultList assertions
    expect(wrapper.text()).toContain('第 1 题');
    expect(wrapper.text()).toContain('第 2 题');
    expect(wrapper.text()).toContain('待重新判题');

    // Bottom action bar
    expect(wrapper.find('.bottom-action-bar').exists()).toBe(true);
    expect(wrapper.text()).toContain('一键强化薄弱点练习');
  });

  it('opens snippet drawer when view snippet is emitted from result list', async () => {
    vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockReport,
    });
    setupPracticeMock();

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.report-content').exists()).toBe(true);
    });

    const snippetBtn = wrapper.find('.snippet-btn');
    expect(snippetBtn.exists()).toBe(true);
    await snippetBtn.trigger('tap');

    const drawer = wrapper.findComponent({ name: 'OriginalSnippetDrawer' });
    expect(drawer.exists()).toBe(true);
    expect(drawer.props('visible')).toBe(true);
    expect(drawer.props('chapterTitle')).toBe('第 5 章 树形数据结构');
  });

  it('opens self-grade modal and optimistically updates score on success', async () => {
    const fetchSpy = vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockReport,
    });
    setupPracticeMock();

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.report-content').exists()).toBe(true);
    });

    const selfGradeBtn = wrapper.find('.self-grade-btn');
    await selfGradeBtn.trigger('tap');

    const selfGradeModal = wrapper.findComponent({ name: 'SelfGradeModal' });
    expect(selfGradeModal.props('visible')).toBe(true);

    vi.spyOn(diagnosisApi, 'selfGradeQuestion').mockResolvedValue({
      code: 0,
      message: 'success',
      data: { grading_record_id: 'rec_1', score: 4.5 },
    });

    await selfGradeModal.vm.$emit('success', { attempt_item_id: 'att_02', score: 4.5 });

    const q2Score = wrapper.findAll('.score-info')[1];
    expect(q2Score.text()).toBe('4.5 / 5 分');
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('opens regrade modal and updates score on synchronous regrade success', async () => {
    const fetchSpy = vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockReport,
    });
    setupPracticeMock();

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.report-content').exists()).toBe(true);
    });

    const regradeBtn = wrapper.find('.regrade-btn');
    await regradeBtn.trigger('tap');

    const regradeModal = wrapper.findComponent({ name: 'RegradeModal' });
    expect(regradeModal.props('visible')).toBe(true);

    await regradeModal.vm.$emit('success', {
      attempt_item_id: 'att_02',
      reason: '核心关键点未识别',
      status: 'success',
      score: 4.2,
    });

    // 重判同步完成：就地更新新分数与判级，不再停留在“待重新判题”
    const q2Score = wrapper.findAll('.score-info')[1];
    expect(q2Score.text()).toBe('4.2 / 5 分');
    expect(wrapper.text()).not.toContain('待判定');
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('triggers continue practice when bottom bar button is tapped', async () => {
    vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockReport,
    });
    setupPracticeMock();

    const continueSpy = vi.spyOn(diagnosisApi, 'continuePractice').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'prac_new_2002',
        title: '薄弱点强化练习',
        material_id: 'mat_001',
        status: 'idle',
        questions: [],
      } as unknown as PracticeSession,
    });

    const navigateSpy = vi.spyOn(uni, 'navigateTo');

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.report-content').exists()).toBe(true);
    });

    const continueBtn = wrapper.find('.continue-btn');
    await continueBtn.trigger('tap');

    expect(continueSpy).toHaveBeenCalledTimes(1);
    expect(continueSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        material_id: 'mat_001',
        knowledge_point_ids: ['kp_1'],
        source_report_id: 'rep_1001',
        title: '薄弱点强化练习',
      }),
    );

    expect(navigateSpy).toHaveBeenCalledWith({
      url: '/subpackages/practice/pages/session/index?id=prac_new_2002',
    });
  });

  it('loads first screen only once despite onLoad and onMounted (BUG-GRADE-006)', async () => {
    const fetchSpy = vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockReport,
    });
    setupPracticeMock();

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    const onLoadHandler = vi
      .mocked(onLoad)
      .mock.calls.map((call) => call[0])
      .find((arg): arg is (query?: Record<string, string>) => void => typeof arg === 'function');
    expect(onLoadHandler).toBeTypeOf('function');

    // Simulate the WeChat lifecycle: onLoad receives the same practice_id while
    // onMounted's first-screen load is still in flight.
    onLoadHandler?.({ practice_id: 'prac_1001' });

    await vi.waitFor(() => {
      expect(wrapper.find('.report-content').exists()).toBe(true);
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it('loads report and practice exactly once on first screen (DIAG-014)', async () => {
    const reportSpy = vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockReport,
    });
    const practiceSpy = setupPracticeMock();

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    const onLoadHandler = vi
      .mocked(onLoad)
      .mock.calls.map((call) => call[0])
      .find((arg): arg is (query?: Record<string, string>) => void => typeof arg === 'function');
    expect(onLoadHandler).toBeTypeOf('function');

    // Simulate the WeChat lifecycle: onMounted already fired and onLoad now
    // passes the same practice_id while the first-screen load is in flight.
    onLoadHandler?.({ practice_id: 'prac_1001' });

    await vi.waitFor(() => {
      expect(wrapper.find('.report-content').exists()).toBe(true);
    });

    expect(reportSpy).toHaveBeenCalledTimes(1);
    expect(practiceSpy).toHaveBeenCalledTimes(1);
  });

  it('shows items error with retry when practice session fails (BUG-GRADE-005)', async () => {
    vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockReport,
    });
    const practiceSpy = vi
      .spyOn(practiceApi, 'fetchPracticeSession')
      .mockRejectedValueOnce(new Error('practice request failed'))
      .mockResolvedValueOnce({
        code: 0,
        message: 'success',
        data: {
          id: 'prac_1001',
          title: '树结构专项练习',
          material_id: 'mat_001',
          status: 'graded',
          questions: [],
          items: mockPracticeItems,
          time_elapsed_seconds: 125,
        } as unknown as PracticeSession,
      });

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.items-error-state').exists()).toBe(true);
    });
    expect(wrapper.text()).toContain('作答明细加载失败，请重试');
    // Report body still renders (degraded, not blank)
    expect(wrapper.find('.report-content').exists()).toBe(true);

    await wrapper.find('.items-retry-btn').trigger('tap');
    await vi.waitFor(() => {
      expect(wrapper.findAll('.result-card').length).toBeGreaterThan(0);
    });

    expect(wrapper.find('.items-error-state').exists()).toBe(false);
    expect(wrapper.text()).toContain('第 1 题');
    expect(practiceSpy).toHaveBeenCalledTimes(2);
  });

  it('opens snippet drawer from top-level source_snippet fallback (BUG-GRADE-004)', async () => {
    vi.spyOn(diagnosisApi, 'fetchDiagnosisReport').mockResolvedValue({
      code: 0,
      message: 'success',
      data: mockReport,
    });
    vi.spyOn(practiceApi, 'fetchPracticeSession').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'prac_1001',
        title: '图论专项练习',
        material_id: 'mat_001',
        status: 'graded',
        questions: [],
        items: [
          {
            attempt_item_id: 'att_top',
            order_index: 1,
            status: 'graded',
            score: 1,
            max_score: 1,
            is_answered: true,
            user_answer: 'A',
            source_snippet: {
              chapter_title: '第 9 章 图论',
              page_index: 77,
              snippet_content: '图的深度优先遍历借助栈递归实现。',
            },
            question_snapshot: {
              stem: '图的遍历方式有哪些？',
              question_type: 'single_choice',
              answer: 'A',
            },
          },
        ] as unknown as AttemptGradingItem[],
        time_elapsed_seconds: 10,
      } as unknown as PracticeSession,
    });

    const wrapper = mount(ReportDetailPage, {
      global: { plugins: [pinia] },
      props: { practiceId: 'prac_1001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.report-content').exists()).toBe(true);
    });

    await wrapper.find('.snippet-btn').trigger('tap');

    const drawer = wrapper.findComponent({ name: 'OriginalSnippetDrawer' });
    expect(drawer.props('visible')).toBe(true);
    expect(drawer.props('chapterTitle')).toBe('第 9 章 图论');
    expect(drawer.props('pageIndex')).toBe(77);
    expect(drawer.props('snippetContent')).toContain('图的深度优先遍历');
  });
});
