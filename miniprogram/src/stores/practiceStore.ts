/**
 * Practice Store
 * Manages active practice session, questions sequence, and local answer drafts.
 * Enforces pure state mutation without direct network API calls.
 */

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { QuestionItem } from '../types/question';
import type { PracticeQuestionOutline, AnswerDraft } from '../types/practice';
import { storage } from '../utils/storage';

export type PracticeQuestion = QuestionItem | PracticeQuestionOutline;

export const usePracticeStore = defineStore('practice', () => {
  // State
  const sessionId = ref<string | null>(null);
  const questions = ref<PracticeQuestion[]>([]);
  const currentIndex = ref<number>(0);
  const drafts = ref<Record<string, AnswerDraft>>({});
  const isSubmitting = ref<boolean>(false);

  // Getters
  const currentQuestion = computed<PracticeQuestion | null>(() => {
    if (questions.value.length === 0) {
      return null;
    }
    return questions.value[currentIndex.value] ?? null;
  });

  const totalQuestions = computed(() => questions.value.length);
  const practiceId = computed(() => sessionId.value);

  const currentDraft = computed<AnswerDraft | null>(() => {
    if (!sessionId.value) {
      return null;
    }
    return drafts.value[sessionId.value] ?? null;
  });

  const answeredCount = computed(() => {
    if (!sessionId.value) {
      return 0;
    }
    const draft = drafts.value[sessionId.value];
    if (!draft || !draft.answers) {
      return 0;
    }
    let count = 0;
    for (const key of Object.keys(draft.answers)) {
      const ans = draft.answers[key];
      if (
        ans !== undefined &&
        ans !== null &&
        ans !== '' &&
        !(Array.isArray(ans) && ans.length === 0)
      ) {
        count += 1;
      }
    }
    return count;
  });

  const progressPercentage = computed(() => {
    if (questions.value.length === 0) {
      return 0;
    }
    return Math.round((answeredCount.value / questions.value.length) * 100);
  });

  const isAllAnswered = computed(() => {
    return questions.value.length > 0 && answeredCount.value === questions.value.length;
  });

  // Actions
  function initSession(id: string, questionList: PracticeQuestion[]): void {
    sessionId.value = id;
    questions.value = [...questionList];
    currentIndex.value = 0;
    isSubmitting.value = false;

    if (!drafts.value[id]) {
      drafts.value[id] = {
        practice_id: id,
        answers: {},
        updated_at: Date.now(),
      };
    }
  }

  function setCurrentIndex(index: number): void {
    if (questions.value.length === 0) {
      currentIndex.value = 0;
      return;
    }
    if (index < 0) {
      currentIndex.value = 0;
    } else if (index >= questions.value.length) {
      currentIndex.value = questions.value.length - 1;
    } else {
      currentIndex.value = index;
    }
  }

  function jumpToQuestion(index: number): void {
    setCurrentIndex(index);
  }

  function nextQuestion(): void {
    if (currentIndex.value < questions.value.length - 1) {
      currentIndex.value += 1;
    }
  }

  function prevQuestion(): void {
    if (currentIndex.value > 0) {
      currentIndex.value -= 1;
    }
  }

  function updateDraft(questionId: string, answer: string | string[]): void {
    if (!sessionId.value) {
      return;
    }
    const id = sessionId.value;
    if (!drafts.value[id]) {
      drafts.value[id] = {
        practice_id: id,
        answers: {},
        updated_at: Date.now(),
      };
    }
    drafts.value[id].answers[questionId] = answer;
    drafts.value[id].updated_at = Date.now();
  }

  function updateAnswer(questionId: string, answer: string | string[]): void {
    updateDraft(questionId, answer);
  }

  function syncDraftToStorage(): void {
    storage.setItem('practice_drafts', drafts.value);
  }

  function loadDraftFromStorage(id?: string): void {
    const saved = storage.getItem('practice_drafts');
    if (saved) {
      drafts.value = { ...drafts.value, ...saved };
      if (id && drafts.value[id]) {
        sessionId.value = id;
      }
    }
  }

  function clearSession(): void {
    sessionId.value = null;
    questions.value = [];
    currentIndex.value = 0;
    isSubmitting.value = false;
  }

  return {
    sessionId,
    questions,
    currentIndex,
    drafts,
    isSubmitting,
    currentQuestion,
    totalQuestions,
    practiceId,
    currentDraft,
    answeredCount,
    progressPercentage,
    isAllAnswered,
    initSession,
    setCurrentIndex,
    jumpToQuestion,
    nextQuestion,
    prevQuestion,
    updateDraft,
    updateAnswer,
    syncDraftToStorage,
    loadDraftFromStorage,
    clearSession,
  };
});

export default usePracticeStore;
