import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { usePracticeStore } from '@/stores/practiceStore';
import { storage } from '@/utils/storage';
import type { QuestionItem } from '@/types/question';

describe('PracticeStore', () => {
  const memoryStore: Record<string, unknown> = {};

  beforeEach(() => {
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
  });

  const mockQuestions: QuestionItem[] = [
    {
      id: 'q-001',
      material_id: 'mat-001',
      version_id: 'ver-001',
      knowledge_point_id: 'kn-001',
      question_type: 'single_choice',
      stem: 'What is a process?',
      options: [
        { key: 'A', text: 'Program in execution' },
        { key: 'B', text: 'Storage device' },
      ],
      difficulty: 1,
    },
    {
      id: 'q-002',
      material_id: 'mat-001',
      version_id: 'ver-001',
      knowledge_point_id: 'kn-001',
      question_type: 'multiple_choice',
      stem: 'Which are valid states?',
      options: [
        { key: 'A', text: 'Running' },
        { key: 'B', text: 'Ready' },
        { key: 'C', text: 'Waiting' },
      ],
      difficulty: 2,
    },
  ];

  it('should initialize with default idle state', () => {
    const store = usePracticeStore();
    expect(store.sessionId).toBeNull();
    expect(store.questions).toEqual([]);
    expect(store.currentIndex).toBe(0);
    expect(store.drafts).toEqual({});
    expect(store.isSubmitting).toBe(false);
    expect(store.currentQuestion).toBeNull();
    expect(store.progressPercentage).toBe(0);
    expect(store.answeredCount).toBe(0);
    expect(store.isAllAnswered).toBe(false);
  });

  it('should initialize session and setup drafts container', () => {
    const store = usePracticeStore();
    store.initSession('session-100', mockQuestions);

    expect(store.sessionId).toBe('session-100');
    expect(store.questions).toHaveLength(2);
    expect(store.currentIndex).toBe(0);
    expect(store.currentQuestion?.id).toBe('q-001');
    expect(store.drafts['session-100']).toBeDefined();
    expect(store.drafts['session-100'].answers).toEqual({});
  });

  it('should update draft answers and compute progress/completion getters correctly', () => {
    const store = usePracticeStore();
    store.initSession('session-100', mockQuestions);

    expect(store.answeredCount).toBe(0);
    expect(store.progressPercentage).toBe(0);
    expect(store.isAllAnswered).toBe(false);

    // Answer first question
    store.updateDraft('q-001', 'A');
    expect(store.drafts['session-100'].answers['q-001']).toBe('A');
    expect(store.answeredCount).toBe(1);
    expect(store.progressPercentage).toBe(50);
    expect(store.isAllAnswered).toBe(false);

    // Answer second question
    store.updateDraft('q-002', ['A', 'B']);
    expect(store.answeredCount).toBe(2);
    expect(store.progressPercentage).toBe(100);
    expect(store.isAllAnswered).toBe(true);
  });

  it('should navigate through questions with boundary clamping', () => {
    const store = usePracticeStore();
    store.initSession('session-100', mockQuestions);

    expect(store.currentIndex).toBe(0);
    store.prevQuestion(); // Underflow protection
    expect(store.currentIndex).toBe(0);

    store.nextQuestion();
    expect(store.currentIndex).toBe(1);
    expect(store.currentQuestion?.id).toBe('q-002');

    store.nextQuestion(); // Overflow protection
    expect(store.currentIndex).toBe(1);

    store.setCurrentIndex(-5);
    expect(store.currentIndex).toBe(0);

    store.setCurrentIndex(100);
    expect(store.currentIndex).toBe(1);
  });

  it('should sync drafts to storage and load drafts back', () => {
    const store = usePracticeStore();
    store.initSession('session-100', mockQuestions);
    store.updateDraft('q-001', 'A');

    store.syncDraftToStorage();

    const storedDrafts = storage.getItem('practice_drafts');
    expect(storedDrafts).toBeDefined();
    expect(storedDrafts?.['session-100']?.answers['q-001']).toBe('A');

    // Create a new store instance and load draft
    const newStore = usePracticeStore();
    newStore.loadDraftFromStorage();
    expect(newStore.drafts['session-100']?.answers['q-001']).toBe('A');
  });

  it('should clear session cleanly', () => {
    const store = usePracticeStore();
    store.initSession('session-100', mockQuestions);
    store.updateDraft('q-001', 'A');

    store.clearSession();

    expect(store.sessionId).toBeNull();
    expect(store.questions).toEqual([]);
    expect(store.currentIndex).toBe(0);
    expect(store.currentQuestion).toBeNull();
    expect(store.isSubmitting).toBe(false);
  });

  it('should purge the submitted draft from the in-memory drafts map (PRAC-008)', () => {
    const store = usePracticeStore();
    store.initSession('session-100', mockQuestions);
    store.updateDraft('q-001', 'A');
    expect(store.drafts['session-100']).toBeDefined();

    // Submitting clears both the active session and its lingering draft entry
    store.clearSession('session-100');

    expect(store.sessionId).toBeNull();
    expect(store.drafts['session-100']).toBeUndefined();
  });

  it('should expose removeDraft to drop a single practice draft (PRAC-008)', () => {
    const store = usePracticeStore();
    store.initSession('session-100', mockQuestions);
    store.initSession('session-200', mockQuestions);
    store.updateDraft('q-001', 'A');

    store.removeDraft('session-100');

    expect(store.drafts['session-100']).toBeUndefined();
    expect(store.sessionId).toBe('session-200');
  });
});
