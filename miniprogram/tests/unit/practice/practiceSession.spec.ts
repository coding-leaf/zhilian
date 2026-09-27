import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import PracticeHeader from '@/subpackages/practice/components/PracticeHeader.vue';
import BottomActionBar from '@/subpackages/practice/components/BottomActionBar.vue';
import SessionPage from '@/subpackages/practice/pages/session/index.vue';
import { usePracticeStore } from '@/stores/practiceStore';
import * as requestModule from '@/utils/request';
import { usePracticeSession } from '@/subpackages/practice/composables/usePracticeSession';
import { getOrCreateSubmitKey } from '@/subpackages/practice/utils/submitKey';
import type {
  PracticeQuestionOutline,
  PracticeQuestionItem,
  RawPracticeSession,
} from '@/types/practice';
import { storage } from '@/utils/storage';
import { loadDraftFromStorage } from '@/subpackages/practice/utils/draft';
import { AppError } from '@/utils/error';

describe('PracticeHeader.vue', () => {
  it('renders title, progress, and formatted timer correctly', () => {
    const wrapper = mount(PracticeHeader, {
      props: {
        title: 'Python算法专项练习',
        currentIndex: 2,
        totalQuestions: 10,
        elapsedSeconds: 75,
      },
    });

    expect(wrapper.text()).toContain('Python算法专项练习');
    expect(wrapper.find('.progress-badge').text()).toBe('3/10');
    expect(wrapper.find('.timer-text').text()).toBe('01:15');
    expect(wrapper.find('.header-exit').text()).toContain('退出');
    expect(wrapper.find('.header-sheet').text()).toContain('答题卡');
  });

  it('emits exit when exit button is clicked', async () => {
    const wrapper = mount(PracticeHeader, {
      props: {
        currentIndex: 0,
        totalQuestions: 5,
      },
    });

    await wrapper.find('.header-exit').trigger('tap');
    expect(wrapper.emitted('exit')).toHaveLength(1);
  });

  it('emits open-sheet when sheet button is clicked', async () => {
    const wrapper = mount(PracticeHeader, {
      props: {
        currentIndex: 0,
        totalQuestions: 5,
      },
    });

    await wrapper.find('.header-sheet').trigger('tap');
    expect(wrapper.emitted('open-sheet')).toHaveLength(1);
  });
});

describe('BottomActionBar.vue', () => {
  it('disables prev button on first question and enables next', async () => {
    const wrapper = mount(BottomActionBar, {
      props: {
        currentIndex: 0,
        totalCount: 5,
        isSubmitting: false,
      },
    });

    const prevBtn = wrapper.find('.btn-prev');
    const nextBtn = wrapper.find('.btn-next');

    expect(prevBtn.classes()).toContain('disabled');
    expect(nextBtn.classes()).not.toContain('disabled');

    // Tap on disabled prev should not emit
    await prevBtn.trigger('tap');
    expect(wrapper.emitted('prev')).toBeUndefined();

    // Tap on next should emit
    await nextBtn.trigger('tap');
    expect(wrapper.emitted('next')).toHaveLength(1);
  });

  it('disables next button on last question and sets submit as primary', async () => {
    const wrapper = mount(BottomActionBar, {
      props: {
        currentIndex: 4,
        totalCount: 5,
        isSubmitting: false,
      },
    });

    const prevBtn = wrapper.find('.btn-prev');
    const nextBtn = wrapper.find('.btn-next');
    const submitBtn = wrapper.find('.btn-submit');

    expect(prevBtn.classes()).not.toContain('disabled');
    expect(nextBtn.classes()).toContain('disabled');
    expect(submitBtn.classes()).toContain('btn-primary');

    await prevBtn.trigger('tap');
    expect(wrapper.emitted('prev')).toHaveLength(1);

    await submitBtn.trigger('tap');
    expect(wrapper.emitted('submit')).toHaveLength(1);
  });

  it('disables all buttons when isSubmitting is true', async () => {
    const wrapper = mount(BottomActionBar, {
      props: {
        currentIndex: 2,
        totalCount: 5,
        isSubmitting: true,
      },
    });

    expect(wrapper.find('.btn-prev').classes()).toContain('disabled');
    expect(wrapper.find('.btn-next').classes()).toContain('disabled');
    expect(wrapper.find('.btn-submit').classes()).toContain('disabled');
    expect(wrapper.find('.btn-submit').text()).toContain('提交中...');

    await wrapper.find('.btn-submit').trigger('tap');
    expect(wrapper.emitted('submit')).toBeUndefined();
  });
});

describe('Practice Session Integration (session/index.vue)', () => {
  const memoryStore: Record<string, unknown> = {};
  let networkChangeCallback: ((res: { isConnected: boolean }) => void) | null = null;

  const mockQuestions: PracticeQuestionOutline[] = [
    {
      id: 'q_001',
      stem: '以下哪项是 Python 的不可变数据类型？',
      type: 'single_choice',
      order_index: 0,
      options: [
        { key: 'A', text: '列表 (List)' },
        { key: 'B', text: '元组 (Tuple)' },
        { key: 'C', text: '字典 (Dict)' },
        { key: 'D', text: '集合 (Set)' },
      ],
    },
    {
      id: 'q_002',
      stem: '以下哪些是关系型数据库？',
      type: 'multiple_choice',
      order_index: 1,
      options: [
        { key: 'A', text: 'PostgreSQL' },
        { key: 'B', text: 'Redis' },
        { key: 'C', text: 'MySQL' },
        { key: 'D', text: 'MongoDB' },
      ],
    },
    {
      id: 'q_003',
      stem: 'Python 中整型无溢出风险。',
      type: 'true_false',
      order_index: 2,
    },
  ];

  // Real backend contract: PracticeDetailResponse.items[].question_snapshot
  const rawPracticeDetail: RawPracticeSession = {
    practice_id: 'practice_999',
    id: 'practice_999',
    title: '综合测试卷',
    material_id: 'mat_1',
    status: 'in_progress',
    time_elapsed_seconds: 10,
    items: [
      {
        attempt_item_id: 'att_001',
        question_id: 'q_001',
        order_index: 1,
        is_answered: false,
        question_snapshot: {
          stem: '以下哪项是 Python 的不可变数据类型？',
          question_type: 'single_choice',
          options: [
            { key: 'A', content: '列表 (List)' },
            { key: 'B', content: '元组 (Tuple)' },
            { key: 'C', content: '字典 (Dict)' },
            { key: 'D', content: '集合 (Set)' },
          ],
          answer: 'B',
          difficulty: 3,
        },
      },
      {
        attempt_item_id: 'att_002',
        question_id: 'q_002',
        order_index: 2,
        is_answered: false,
        question_snapshot: {
          stem: '以下哪些是关系型数据库？',
          question_type: 'multiple_choice',
          options: [
            { key: 'A', content: 'PostgreSQL' },
            { key: 'B', content: 'Redis' },
            { key: 'C', content: 'MySQL' },
            { key: 'D', content: 'MongoDB' },
          ],
          answer: 'AC',
          difficulty: 2,
        },
      },
      {
        attempt_item_id: 'att_003',
        question_id: 'q_003',
        order_index: 3,
        is_answered: false,
        question_snapshot: {
          stem: 'Python 中整型无溢出风险。',
          question_type: 'true_false',
          options: [],
          answer: 'T',
          difficulty: 1,
        },
      },
    ],
  };

  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    Object.keys(memoryStore).forEach((k) => delete memoryStore[k]);

    uni.getStorageSync = ((key: string) =>
      memoryStore[key] ?? null) as unknown as typeof uni.getStorageSync;
    uni.setStorageSync = (key: string, data: unknown) => {
      memoryStore[key] = data;
    };
    uni.removeStorageSync = (key: string) => {
      delete memoryStore[key];
    };
    uni.clearStorageSync = () => {
      Object.keys(memoryStore).forEach((k) => delete memoryStore[k]);
    };

    uni.onNetworkStatusChange = vi.fn((cb: (res: { isConnected: boolean }) => void) => {
      networkChangeCallback = cb;
    }) as unknown as typeof uni.onNetworkStatusChange;

    uni.offNetworkStatusChange = vi.fn() as unknown as typeof uni.offNetworkStatusChange;
    uni.showModal = vi.fn() as unknown as typeof uni.showModal;
    uni.showToast = vi.fn() as unknown as typeof uni.showToast;
    uni.navigateBack = vi.fn() as unknown as typeof uni.navigateBack;
    uni.redirectTo = vi.fn() as unknown as typeof uni.redirectTo;

    storage.clear();

    vi.spyOn(requestModule, 'request').mockImplementation((options) => {
      const url = options.url;
      if (url.includes('/answers')) {
        return Promise.resolve({
          code: 0,
          message: 'success',
          data: { attempt_item_id: 'item_1', status: 'saved' },
        });
      }
      if (url.includes('/submit')) {
        return Promise.resolve({
          code: 0,
          message: 'success',
          data: { practice_id: 'practice_999', status: 'submitted' },
        });
      }
      return Promise.resolve({
        code: 0,
        message: 'success',
        data: rawPracticeDetail,
      });
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('initializes session correctly and displays question 1', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);

    const wrapper = mount(SessionPage);

    expect(wrapper.find('.practice-header').exists()).toBe(true);
    expect(wrapper.find('.stem-text').text()).toContain('以下哪项是 Python 的不可变数据类型？');
    expect(wrapper.find('.progress-badge').text()).toBe('1/3');
  });

  it('answers single choice, saves to storage, and syncs via debounced network request', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);

    const wrapper = mount(SessionPage);

    // Option B is "元组 (Tuple)"
    const optionCards = wrapper.findAll('.option-card');
    expect(optionCards.length).toBe(4);

    await optionCards[1].trigger('tap');

    // Verified in Pinia store
    expect(store.currentDraft?.answers.q_001).toBe('B');

    // Verified in Storage practice_drafts
    const draftInStorage = loadDraftFromStorage('practice_999');
    expect(draftInStorage).not.toBeNull();
    expect(draftInStorage?.items.q_001.user_answer).toBe('B');

    // Debounce timer: fast-forward 600ms
    vi.advanceTimersByTime(600);
    expect(requestModule.request).toHaveBeenCalledWith({
      url: '/api/v1/practices/practice_999/answers',
      method: 'PUT',
      data: {
        question_id: 'q_001',
        user_answer: 'B',
        time_spent_seconds: 1,
      },
    });
  });

  it('navigates next and prev questions smoothly', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);

    const wrapper = mount(SessionPage);

    const nextBtn = wrapper.find('.btn-next');
    await nextBtn.trigger('tap');

    expect(store.currentIndex).toBe(1);
    expect(wrapper.find('.stem-text').text()).toContain('以下哪些是关系型数据库？');
    expect(wrapper.find('.progress-badge').text()).toBe('2/3');

    const prevBtn = wrapper.find('.btn-prev');
    await prevBtn.trigger('tap');

    expect(store.currentIndex).toBe(0);
    expect(wrapper.find('.stem-text').text()).toContain('以下哪项是 Python 的不可变数据类型？');
  });

  it('opens answer sheet drawer and jumps to selected question', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);

    const wrapper = mount(SessionPage);

    // Open sheet
    await wrapper.find('.header-sheet').trigger('tap');
    expect(wrapper.find('.sheet-drawer').exists()).toBe(true);

    // Click on question 3 cell
    const cells = wrapper.findAll('.sheet-cell');
    expect(cells.length).toBe(3);
    await cells[2].trigger('tap');

    expect(store.currentIndex).toBe(2);
    expect(wrapper.find('.stem-text').text()).toContain('Python 中整型无溢出风险。');
  });

  it('prompts exit confirmation when exit button is clicked', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);

    const wrapper = mount(SessionPage);

    await wrapper.find('.header-exit').trigger('tap');
    expect(uni.showModal).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '退出练习',
        confirmText: '退出',
      }),
    );
  });

  it('handles unanswered blocking modal and submits with idempotency key', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);

    // Answer only question 1
    store.updateAnswer('q_001', 'B');

    const wrapper = mount(SessionPage);

    // Click submit button in bottom action bar
    await wrapper.find('.btn-submit').trigger('tap');

    // Submit confirmation modal should be visible
    expect(wrapper.find('.modal-card').exists()).toBe(true);
    expect(wrapper.text()).toContain('尚有 2 道题目未作答');

    // Click "仍要交卷" button in modal
    const confirmBtn = wrapper.find('.modal-actions .btn-primary');
    await confirmBtn.trigger('tap');

    await vi.runAllTimersAsync();

    const submitCall = vi
      .mocked(requestModule.request)
      .mock.calls.find((call) => call[0]?.url.endsWith('/submit'));
    expect(submitCall).toBeDefined();
    expect(submitCall?.[0]).toEqual(
      expect.objectContaining({
        url: '/api/v1/practices/practice_999/submit',
        method: 'POST',
        data: { confirm_unanswered: true },
        headers: { 'Idempotency-Key': expect.any(String) },
      }),
    );

    // Verified storage cleared
    expect(loadDraftFromStorage('practice_999')).toBeNull();
    expect(uni.redirectTo).toHaveBeenCalledWith({
      url: '/subpackages/report/index?practice_id=practice_999',
    });
  });

  it('loads questions from the real backend items contract into the store (PRAC-001/002)', async () => {
    const store = usePracticeStore();
    const { loadPractice, cleanupSession } = usePracticeSession();

    await loadPractice('practice_999');

    expect(store.questions).toHaveLength(3);
    expect(store.currentQuestion?.id).toBe('q_001');
    const first = store.questions[0] as PracticeQuestionItem;
    expect(first.question_type).toBe('single_choice');
    expect(first.stem).toContain('不可变数据类型');
    expect(first.options?.[0]).toEqual({ key: 'A', text: '列表 (List)' });

    cleanupSession();
  });

  it('reuses one idempotency key across submit retries and clears it on success (PRAC-003)', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);
    const wrapper = mount(SessionPage);

    let submitAttempts = 0;
    vi.mocked(requestModule.request).mockImplementation((options) => {
      if (options.url.endsWith('/submit')) {
        submitAttempts += 1;
        if (submitAttempts === 1) {
          return Promise.reject(new AppError(-1, '网络请求异常'));
        }
        return Promise.resolve({
          code: 0,
          message: 'success',
          data: { practice_id: 'practice_999', status: 'submitted' },
        });
      }
      return Promise.resolve({ code: 0, message: 'success', data: {} });
    });

    await wrapper.find('.btn-submit').trigger('tap');
    const confirmBtn = wrapper.find('.modal-actions .btn-primary');

    await confirmBtn.trigger('tap');
    await vi.runAllTimersAsync();

    // Network failure keeps the modal open so the user retries the submission.
    await confirmBtn.trigger('tap');
    await vi.runAllTimersAsync();

    const submitCalls = vi
      .mocked(requestModule.request)
      .mock.calls.filter((call) => call[0]?.url.endsWith('/submit'));
    expect(submitCalls).toHaveLength(2);
    const firstKey = submitCalls[0][0].headers?.['Idempotency-Key'];
    const secondKey = submitCalls[1][0].headers?.['Idempotency-Key'];
    expect(firstKey).toBeTruthy();
    expect(secondKey).toBe(firstKey);

    // Success clears the persisted key, so the next session mints a new one.
    expect(getOrCreateSubmitKey('practice_999')).not.toBe(firstKey);
  });

  it('keeps answering usable and still schedules remote sync when draft storage overflows (PRAC-004)', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);
    const wrapper = mount(SessionPage);

    vi.spyOn(storage, 'setItem').mockImplementation(() => {
      throw new AppError(10001, 'Storage key forbidden');
    });

    const optionCards = wrapper.findAll('.option-card');
    await optionCards[0].trigger('tap');

    expect(store.currentDraft?.answers.q_001).toBe('A');

    vi.advanceTimersByTime(600);
    expect(requestModule.request).toHaveBeenCalledWith({
      url: '/api/v1/practices/practice_999/answers',
      method: 'PUT',
      data: { question_id: 'q_001', user_answer: 'A', time_spent_seconds: 1 },
    });
  });

  it('re-syncs pending drafts when network reconnects', async () => {
    const store = usePracticeStore();
    store.initSession('practice_999', mockQuestions);

    const wrapper = mount(SessionPage);

    // Simulate network reconnect callback
    expect(networkChangeCallback).not.toBeNull();
    if (networkChangeCallback) {
      // Simulate answer pending in storage via tapping option
      const optionCards = wrapper.findAll('.option-card');
      await optionCards[0].trigger('tap');

      const draft = loadDraftFromStorage('practice_999');
      expect(draft).not.toBeNull();

      await networkChangeCallback({ isConnected: true });
      await vi.runAllTimersAsync();

      expect(requestModule.request).toHaveBeenCalled();
    }
  });
});
