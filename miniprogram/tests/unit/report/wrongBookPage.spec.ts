import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import WrongBookPage from '@/subpackages/report/pages/wrong-book/index.vue';
import * as diagnosisApi from '@/api/diagnosis';
import { useReportStore } from '@/stores/reportStore';
import type { WrongRecordItem } from '@/types/report';
import type { PracticeSession } from '@/types/practice';

describe('WrongBookPage (subpackages/report/pages/wrong-book/index.vue)', () => {
  let pinia: ReturnType<typeof createPinia>;

  function getMockWrongRecords(): WrongRecordItem[] {
    return [
      {
        id: 'wr_001',
        practice_id: 'prac_1001',
        question_id: 'q_101',
        knowledge_point_id: 'kp_tree',
        material_id: 'mat_001',
        question_type: 'single_choice',
        question_stem: 'AVL树的平衡因子绝对值必须小于等于多少？',
        user_answer: '2',
        correct_answer: '1',
        analysis: '平衡因子为左右子树高度差，绝对值必须<=1。',
        error_type: 'conceptual',
        error_count: 2,
        is_mastered: false,
        created_at: '2026-09-25T10:00:00Z',
        question_snapshot: {
          stem: 'AVL树的平衡因子绝对值必须小于等于多少？',
          question_type: 'single_choice',
          options: [
            { key: 'A', text: '0' },
            { key: 'B', text: '1' },
            { key: 'C', text: '2' },
            { key: 'D', text: '3' },
          ],
          answer: '1',
          analysis: '平衡因子为左右子树高度差，绝对值必须<=1。',
          knowledge_name: '二叉平衡树',
        },
      },
      {
        id: 'wr_002',
        practice_id: 'prac_1001',
        question_id: 'q_102',
        knowledge_point_id: 'kp_graph',
        material_id: 'mat_001',
        question_type: 'true_false',
        question_stem: '无向完全图的边数为 n*(n-1)/2。',
        user_answer: '错误',
        correct_answer: '正确',
        analysis: 'n个顶点的无向完全图任意两点间均有一条边，总边数为n*(n-1)/2。',
        error_type: 'incomplete',
        error_count: 1,
        is_mastered: true,
        mastered_at: '2026-09-25T11:00:00Z',
        created_at: '2026-09-25T10:05:00Z',
        question_snapshot: {
          stem: '无向完全图的边数为 n*(n-1)/2。',
          question_type: 'true_false',
          answer: '正确',
          knowledge_name: '图论基础',
        },
      },
    ];
  }

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    vi.restoreAllMocks();
  });

  it('renders loading skeleton initially before data resolves', () => {
    vi.spyOn(diagnosisApi, 'fetchWrongBook').mockReturnValue(new Promise(() => {}));

    const wrapper = mount(WrongBookPage, {
      global: { plugins: [pinia] },
      props: { materialId: 'mat_001' },
    });

    expect(wrapper.find('.skeleton-wrapper').exists()).toBe(true);
    expect(wrapper.find('.records-list').exists()).toBe(false);
  });

  it('renders error state and retries successfully', async () => {
    const fetchSpy = vi
      .spyOn(diagnosisApi, 'fetchWrongBook')
      .mockRejectedValueOnce(new Error('错题库拉取超时'))
      .mockResolvedValueOnce({
        code: 0,
        message: 'success',
        data: {
          items: getMockWrongRecords(),
          total: 2,
          limit: 20,
          offset: 0,
        },
      });

    const wrapper = mount(WrongBookPage, {
      global: { plugins: [pinia] },
      props: { materialId: 'mat_001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.error-state').exists()).toBe(true);
    });
    expect(wrapper.text()).toContain('错题库拉取超时');

    const retryBtn = wrapper.find('.retry-btn');
    await retryBtn.trigger('tap');

    await vi.waitFor(() => {
      expect(wrapper.find('.records-list').exists()).toBe(true);
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('renders empty state when no wrong records returned', async () => {
    vi.spyOn(diagnosisApi, 'fetchWrongBook').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
      },
    });

    const wrapper = mount(WrongBookPage, {
      global: { plugins: [pinia] },
      props: { materialId: 'mat_001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.empty-state').exists()).toBe(true);
    });
    expect(wrapper.text()).toContain('暂无错题记录');
  });

  it('renders wrong records list and interacts with filters', async () => {
    const fetchSpy = vi.spyOn(diagnosisApi, 'fetchWrongBook').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: getMockWrongRecords(),
        total: 2,
        limit: 20,
        offset: 0,
      },
    });

    const wrapper = mount(WrongBookPage, {
      global: { plugins: [pinia] },
      props: { materialId: 'mat_001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.records-list').exists()).toBe(true);
    });

    const cards = wrapper.findAllComponents({ name: 'WrongRecordCard' });
    expect(cards).toHaveLength(2);
    expect(wrapper.text()).toContain('AVL树的平衡因子绝对值必须小于等于多少？');
    expect(wrapper.text()).toContain('无向完全图的边数为 n*(n-1)/2。');

    // Filter interaction: click on status tab
    const filterBar = wrapper.findComponent({ name: 'WrongRecordFilterBar' });
    expect(filterBar.exists()).toBe(true);

    const tabs = filterBar.findAll('.status-tab-item');
    // Click '待攻克'
    await tabs[1].trigger('tap');

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        is_mastered: false,
        material_id: 'mat_001',
      }),
    );
  });

  it('handles multi-selection, select-all, and clear-selection flow', async () => {
    vi.spyOn(diagnosisApi, 'fetchWrongBook').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: getMockWrongRecords(),
        total: 2,
        limit: 20,
        offset: 0,
      },
    });

    const wrapper = mount(WrongBookPage, {
      global: { plugins: [pinia] },
      props: { materialId: 'mat_001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.records-list').exists()).toBe(true);
    });

    const store = useReportStore();
    expect(store.selectedRecordCount).toBe(0);

    // Toggle select first card
    const firstCheckbox = wrapper.find('.select-touch-area');
    await firstCheckbox.trigger('tap');
    expect(store.selectedRecordIds).toContain('wr_001');
    expect(store.selectedRecordCount).toBe(1);

    // Click select all
    const selectAllBtn = wrapper.find('.batch-select-btn');
    await selectAllBtn.trigger('tap');
    expect(store.selectedRecordCount).toBe(2);

    // Click clear selection
    const clearBtn = wrapper.find('.clear-btn');
    expect(clearBtn.exists()).toBe(true);
    await clearBtn.trigger('tap');
    expect(store.selectedRecordCount).toBe(0);
  });

  it('optimistically toggles wrong record mastered status with rollback on failure', async () => {
    vi.spyOn(diagnosisApi, 'fetchWrongBook').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: [getMockWrongRecords()[0]], // is_mastered: false
        total: 1,
        limit: 20,
        offset: 0,
      },
    });

    const toggleSpy = vi
      .spyOn(diagnosisApi, 'toggleWrongRecordResolved')
      .mockResolvedValueOnce({
        code: 0,
        message: 'success',
        data: {
          id: 'wr_001',
          is_mastered: true,
          mastered_at: '2026-09-25T12:00:00Z',
          message: 'marked',
        },
      })
      .mockRejectedValueOnce(new Error('网络中断'));

    const wrapper = mount(WrongBookPage, {
      global: { plugins: [pinia] },
      props: { materialId: 'mat_001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.records-list').exists()).toBe(true);
    });

    const store = useReportStore();
    expect(store.wrongRecords[0].is_mastered).toBe(false);

    // Click toggle mastered button
    const masterBtn = wrapper.find('.master-action-btn');
    await masterBtn.trigger('tap');

    expect(toggleSpy).toHaveBeenCalledTimes(1);
    expect(store.wrongRecords[0].is_mastered).toBe(true);

    // Second click: mock failure and assert rollback
    await masterBtn.trigger('tap');
    await vi.waitFor(() => {
      expect(store.wrongRecords[0].is_mastered).toBe(true); // Rolled back from false to true
    });
  });

  it('triggers continue practice with selected records or unmastered fallback', async () => {
    vi.spyOn(diagnosisApi, 'fetchWrongBook').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        items: getMockWrongRecords(),
        total: 2,
        limit: 20,
        offset: 0,
      },
    });

    const continueSpy = vi.spyOn(diagnosisApi, 'continuePractice').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        id: 'prac_session_5001',
        title: '错题巩固练习',
        material_id: 'mat_001',
        status: 'idle',
        questions: [],
      } as unknown as PracticeSession,
    });

    const navigateSpy = vi.spyOn(uni, 'navigateTo');

    const wrapper = mount(WrongBookPage, {
      global: { plugins: [pinia] },
      props: { materialId: 'mat_001' },
    });

    await vi.waitFor(() => {
      expect(wrapper.find('.records-list').exists()).toBe(true);
    });

    // 1. Initial state (no selected): button says '一键巩固待攻克错题'
    const bottomBar = wrapper.findComponent({ name: 'ContinuePracticeBar' });
    expect(bottomBar.exists()).toBe(true);
    expect(bottomBar.props('sourceType')).toBe('wrong_record');
    expect(bottomBar.props('buttonText')).toBe('一键巩固待攻克错题');
    expect(bottomBar.props('knowledgePointIds')).toEqual(['kp_tree']);

    // 2. Select first record
    const store = useReportStore();
    store.toggleSelectRecord('wr_001');
    await wrapper.vm.$nextTick();

    expect(bottomBar.props('count')).toBe(1);
    expect(bottomBar.props('buttonText')).toBe('巩固已选 1 道错题');

    // 3. Tap continue practice button
    const continueBtn = wrapper.find('.continue-btn');
    await continueBtn.trigger('tap');

    expect(continueSpy).toHaveBeenCalledTimes(1);
    expect(continueSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        material_id: 'mat_001',
        knowledge_point_ids: ['kp_tree'],
        source_type: 'wrong_record',
      }),
    );

    expect(navigateSpy).toHaveBeenCalledWith({
      url: '/subpackages/practice/pages/session/index?id=prac_session_5001',
    });
  });
});
