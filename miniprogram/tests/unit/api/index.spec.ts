import { describe, it, expect } from 'vitest';
import * as api from '@/api/index';

describe('API Entry Point Module', () => {
  it('should export all expected API functions', () => {
    // Auth
    expect(typeof api.loginByWechat).toBe('function');
    expect(typeof api.refreshToken).toBe('function');
    expect(typeof api.revokeTokens).toBe('function');

    // User
    expect(typeof api.fetchUserProfile).toBe('function');
    expect(typeof api.updateUserProfile).toBe('function');
    expect(typeof api.deleteAccount).toBe('function');

    // Material
    expect(typeof api.fetchMaterialList).toBe('function');
    expect(typeof api.fetchMaterialDetail).toBe('function');
    expect(typeof api.fetchMaterialStatus).toBe('function');
    expect(typeof api.deleteMaterial).toBe('function');
    expect(typeof api.fetchKnowledgeTree).toBe('function');

    // Question
    expect(typeof api.generateQuestions).toBe('function');
    expect(typeof api.fetchQuestionList).toBe('function');
    expect(typeof api.fetchQuestionDetail).toBe('function');
    expect(typeof api.updateQuestion).toBe('function');
    expect(typeof api.deleteQuestion).toBe('function');

    // Practice
    expect(typeof api.createPractice).toBe('function');
    expect(typeof api.fetchPracticeSession).toBe('function');
    expect(typeof api.saveAnswerDraft).toBe('function');
    expect(typeof api.submitPractice).toBe('function');

    // Diagnosis
    expect(typeof api.fetchDiagnosisReport).toBe('function');
    expect(typeof api.fetchMasteryOverview).toBe('function');
    expect(typeof api.fetchWrongBook).toBe('function');
    expect(typeof api.selfGradeQuestion).toBe('function');
    expect(typeof api.requestRegrade).toBe('function');
    expect(typeof api.continuePractice).toBe('function');
  });
});
