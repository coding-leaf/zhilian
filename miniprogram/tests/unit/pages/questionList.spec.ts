import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { setActivePinia, createPinia } from 'pinia';
import QuestionsPage from '@/subpackages/material/pages/questions/index.vue';
import * as questionApi from '@/api/question';
import * as practiceApi from '@/api/practice';
import { usePracticeStore } from '@/stores/practiceStore';
import type { QuestionItem } from '@/types/question';
import type { PracticeSession } from '@/types/practice';

describe('QuestionsPage (questions/index.vue)', () => {
  const sampleQuestions: QuestionItem[] = [
    {
      id: 'q_001',
      material_id: 'mat_001',
      version_id: 'ver_001',
      knowledge_point_id: 'kp_001',
      question_type: 'single_choice',
      stem: '什么是临界区？',
      options: [
        { key: 'A', text: '访问临界资源的代码段' },
        { key: 'B', text: '一种存储设备' },
      ],
      answer: 'A',
      analysis: '临界区指进程中访问临界资源的那段代码。',
      difficulty: 3,
    },
    {
      id: 'q_002',
      material_id: 'mat_001',
      version_id: 'ver_001',
      knowledge_point_id: 'kp_002',
      question_type: 'short_answer',
      stem: '简述进程与线程的区别。',
      answer: '线程是调度的基本单位，进程是资源分配的基本单位。',
      difficulty: 4,
    },
  ];

  function mockList(items: QuestionItem[], total = items.length) {
    return vi.spyOn(questionApi, 'fetchQuestionList').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { items, total, limit: 20, offset: 0 },
    });
  }

  async function flush(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 10));
    await Promise.resolve();
  }

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('loads persisted questions from the backend using material_id and renders cards', async () => {
    const fetchSpy = mockList(sampleQuestions);

    const wrapper = mount(QuestionsPage, { props: { materialId: 'mat_001' } });
    await wrapper.vm.$nextTick();
    await flush();

    expect(fetchSpy).toHaveBeenCalledWith({
      material_id: 'mat_001',
      page: 1,
      page_size: 20,
    });

    const text = wrapper.text();
    expect(text).toContain('什么是临界区？');
    expect(text).toContain('单选题');
    expect(text).toContain('难度 3');
    expect(text).toContain('访问临界资源的代码段');
    expect(text).toContain('简述进程与线程的区别。');
    expect(text).toContain('主观简答题');

    // 零 Emoji 检查
    const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
    expect(emojiRegex.test(text)).toBe(false);
  });

  it('hides options for subjective short_answer questions and reveals analysis on toggle', async () => {
    mockList(sampleQuestions);
    const wrapper = mount(QuestionsPage, { props: { materialId: 'mat_001' } });
    await wrapper.vm.$nextTick();
    await flush();

    const cards = wrapper.findAll('.question-card');
    expect(cards.length).toBe(2);
    expect(cards[0].findAll('.q-option').length).toBe(2);
    expect(cards[1].findAll('.q-option').length).toBe(0);

    // 解析默认折叠
    expect(cards[0].text()).not.toContain('临界区指进程中访问临界资源的那段代码。');
    await cards[0].find('.analysis-header').trigger('tap');
    expect(cards[0].text()).toContain('临界区指进程中访问临界资源的那段代码。');
  });

  it('accepts the id alias query parameter and forwards material_id to the API', async () => {
    const fetchSpy = mockList([]);

    mount(QuestionsPage, { props: { id: 'mat_alias_9' } });
    await flush();

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ material_id: 'mat_alias_9', page: 1 }),
    );
  });

  it('renders the empty state with knowledge-tree guidance when no questions exist', async () => {
    mockList([]);

    const wrapper = mount(QuestionsPage, { props: { materialId: 'mat_001' } });
    await wrapper.vm.$nextTick();
    await flush();

    expect(wrapper.find('.empty-state').exists()).toBe(true);
    expect(wrapper.text()).toContain('暂无题目，去知识树生成');
    expect(wrapper.text()).toContain('去知识树生成');
  });

  it('navigates to the knowledge tree with material_id from the empty state action', async () => {
    mockList([]);
    const navigateSpy = vi.spyOn(uni, 'navigateTo');

    const wrapper = mount(QuestionsPage, { props: { materialId: 'mat_001' } });
    await wrapper.vm.$nextTick();
    await flush();

    await wrapper.find('.empty-action-btn').trigger('tap');

    expect(navigateSpy).toHaveBeenCalledWith({
      url: '/subpackages/material/pages/knowledge-tree/index?material_id=mat_001',
      fail: expect.any(Function),
    });
  });

  it('reloads page 1 after a confirmed delete so shifted items are not skipped', async () => {
    const fetchSpy = mockList(sampleQuestions);
    const deleteSpy = vi.spyOn(questionApi, 'deleteQuestion').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { id: 'q_001', is_deleted: true },
    });
    const showModalSpy = vi.fn(
      (opts: { success?: (res: { confirm: boolean; cancel: boolean }) => void }) => {
        opts.success?.({ confirm: true, cancel: false });
      },
    );
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.showModal = showModalSpy;

    const wrapper = mount(QuestionsPage, { props: { materialId: 'mat_001' } });
    await wrapper.vm.$nextTick();
    await flush();

    // After deletion the backend view no longer contains q_001 (items shift forward).
    fetchSpy.mockResolvedValue({
      code: 200,
      message: 'success',
      data: { items: [sampleQuestions[1]], total: 1, limit: 20, offset: 0 },
    });

    await wrapper.findAll('.action-btn.danger')[0].trigger('tap');
    await flush();
    await wrapper.vm.$nextTick();

    expect(deleteSpy).toHaveBeenCalledWith('q_001', '用户手动删除');
    // A fresh page-1 fetch must be triggered after the delete (initial load + reload).
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    // Pagination resets to page 1 so the next "load more" uses the real offset.
    expect(fetchSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ material_id: 'mat_001', page: 1, page_size: 20 }),
    );
    expect(wrapper.vm.listData.some((q) => q.id === 'q_001')).toBe(false);
    expect(wrapper.vm.listData.map((q) => q.id)).toEqual(['q_002']);
    expect(wrapper.text()).not.toContain('什么是临界区？');
  });

  it('updates the card content when the edit drawer emits an updated question', async () => {
    mockList(sampleQuestions);
    const wrapper = mount(QuestionsPage, { props: { materialId: 'mat_001' } });
    await wrapper.vm.$nextTick();
    await flush();

    wrapper.vm.handleQuestionUpdated({ ...sampleQuestions[0], stem: '更新后的题干内容' });
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain('更新后的题干内容');
  });

  it('appends the next page on load more and de-duplicates merged items', async () => {
    const fetchSpy = mockList([sampleQuestions[0]], 2);
    const wrapper = mount(QuestionsPage, { props: { materialId: 'mat_001' } });
    await wrapper.vm.$nextTick();
    await flush();

    fetchSpy.mockResolvedValue({
      code: 200,
      message: 'success',
      data: { items: [sampleQuestions[0], sampleQuestions[1]], total: 2, limit: 20, offset: 0 },
    });

    wrapper.vm.handleLoadMore();
    await flush();
    await wrapper.vm.$nextTick();

    expect(fetchSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ material_id: 'mat_001', page: 2, page_size: 20 }),
    );
    expect(wrapper.vm.listData.map((q) => q.id)).toEqual(['q_001', 'q_002']);
  });

  it('resolves folder_id from props and forwards it to the question list API', async () => {
    const fetchSpy = mockList(sampleQuestions);

    const wrapper = mount(QuestionsPage, { props: { folderId: 'f1' } });
    await wrapper.vm.$nextTick();
    await flush();

    expect(wrapper.vm.isFolderScope).toBe(true);
    expect(fetchSpy).toHaveBeenCalledWith({
      folder_id: 'f1',
      page: 1,
      page_size: 20,
    });
    expect(wrapper.vm.listData.map((q) => q.id)).toEqual(['q_001', 'q_002']);
  });

  it('guides folder-scoped empty state to the course generate entry with a fail fallback', async () => {
    mockList([]);
    const navigateSpy = vi.spyOn(uni, 'navigateTo');

    const wrapper = mount(QuestionsPage, { props: { folderId: 'f1' } });
    await wrapper.vm.$nextTick();
    await flush();

    expect(wrapper.find('.empty-state').exists()).toBe(true);
    expect(wrapper.text()).toContain('本课程暂无题目');
    expect(wrapper.text()).toContain('去出题');

    await wrapper.find('.empty-action-btn').trigger('tap');

    expect(navigateSpy).toHaveBeenCalledWith({
      url: '/subpackages/material/pages/course/index?folder_id=f1',
      fail: expect.any(Function),
    });
  });

  it('starts a folder-scoped practice via createPractice and navigates to the session', async () => {
    mockList(sampleQuestions);
    const session: PracticeSession = {
      id: 'prac_1',
      title: '课程练习',
      material_id: '',
      folder_id: 'f1',
      status: 'in_progress',
      questions: [],
    };
    const createSpy = vi.spyOn(practiceApi, 'createPractice').mockResolvedValue({
      code: 200,
      message: 'success',
      data: session,
    });
    const navigateSpy = vi.spyOn(uni, 'navigateTo');
    const practiceStore = usePracticeStore();

    const wrapper = mount(QuestionsPage, { props: { folderId: 'f1' } });
    await wrapper.vm.$nextTick();
    await flush();

    expect(wrapper.find('.start-btn').exists()).toBe(true);
    await wrapper.vm.handleStartPractice();
    await flush();

    expect(createSpy).toHaveBeenCalledWith({
      title: '课程练习',
      folder_id: 'f1',
      question_count: 2,
      question_types: ['single_choice', 'multiple_choice', 'true_false', 'short_answer'],
      mode: 'sequential',
    });
    expect(practiceStore.sessionId).toBe('prac_1');
    expect(navigateSpy).toHaveBeenCalledWith({
      url: '/subpackages/practice/pages/session/index?id=prac_1',
      fail: expect.any(Function),
    });
  });

  it('disables start practice when the folder scope has no questions', async () => {
    mockList([]);
    const createSpy = vi.spyOn(practiceApi, 'createPractice');

    const wrapper = mount(QuestionsPage, { props: { folderId: 'f1' } });
    await wrapper.vm.$nextTick();
    await flush();

    expect(wrapper.find('.start-btn').exists()).toBe(false);
    await wrapper.vm.handleStartPractice();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it('groups questions by generation batch and filters by batch on tap (B5)', async () => {
    const batched: QuestionItem[] = [
      { ...sampleQuestions[0], id: 'q_a1', batch_id: 'batch_aaa' },
      { ...sampleQuestions[1], id: 'q_a2', batch_id: 'batch_aaa' },
      { ...sampleQuestions[0], id: 'q_b1', batch_id: 'batch_bbb' },
    ];
    const fetchSpy = mockList(batched);

    const wrapper = mount(QuestionsPage, { props: { materialId: 'mat_001' } });
    await wrapper.vm.$nextTick();
    await flush();

    expect(wrapper.findAll('.batch-group')).toHaveLength(2);
    expect(wrapper.text()).toContain('批次 aaa');
    expect(wrapper.text()).toContain('批次 bbb');

    await wrapper.vm.handleToggleBatchFilter('batch_bbb');
    await flush();

    expect(fetchSpy).toHaveBeenLastCalledWith({
      material_id: 'mat_001',
      batch_id: 'batch_bbb',
      page: 1,
      page_size: 20,
    });
  });
});
