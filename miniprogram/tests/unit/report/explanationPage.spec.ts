import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { mount } from '@vue/test-utils';
import AICoachCard from '@/subpackages/report/components/AICoachCard.vue';
import ExplanationPage from '@/subpackages/report/pages/explanation/index.vue';
import * as questionApi from '@/api/question';
import * as practiceApi from '@/api/practice';
import type { QuestionItem } from '@/types/question';
import type { PracticeSession } from '@/types/practice';

describe('Explanation & AI Coach Components', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    uni.showToast = vi.fn() as unknown as typeof uni.showToast;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe('AICoachCard.vue', () => {
    const questionId = 'q_coach_01';

    it('renders coach header and prompt suggestions', () => {
      const wrapper = mount(AICoachCard, {
        props: {
          questionId,
          userAnswer: '我的答案',
          gradingPoints: ['采分点1'],
        },
      });

      expect(wrapper.find('.coach-title').text()).toBe('深度答疑追问');
      expect(wrapper.text()).toContain('为什么我的答案遗漏了采分点？');
      expect(wrapper.find('.coach-send-btn').classes()).toContain('disabled');
    });

    it('submits prompt to askCoach API and renders reply with suggestions', async () => {
      vi.spyOn(questionApi, 'askCoach').mockResolvedValue({
        code: 0,
        message: 'success',
        data: {
          reply: '这是一段来自 AI 助教的通俗生动的深度解析。',
          suggestions: ['尝试从时间复杂度角度分析', '思考空间复杂度的权衡'],
        },
      });

      const wrapper = mount(AICoachCard, {
        props: {
          questionId,
          userAnswer: '递归实现',
          gradingPoints: ['基准情形', '递归推进'],
        },
      });

      // Tap on a prompt chip
      const chips = wrapper.findAll('.prompt-chip');
      await chips[0].trigger('tap');

      expect(questionApi.askCoach).toHaveBeenCalledWith(
        questionId,
        expect.objectContaining({
          user_prompt: '为什么我的答案遗漏了采分点？',
          user_answer: '递归实现',
        }),
      );

      await vi.runAllTimersAsync();

      expect(wrapper.find('.reply-text').text()).toContain(
        '这是一段来自 AI 助教的通俗生动的深度解析。',
      );
      expect(wrapper.text()).toContain('尝试从时间复杂度角度分析');
    });
  });

  describe('Explanation Page (explanation/index.vue)', () => {
    const mockQuestion: QuestionItem = {
      id: 'q_exp_01',
      material_id: 'mat_1',
      version_id: 'v1',
      knowledge_point_id: 'kp_1',
      question_type: 'short_answer',
      stem: '请详细阐述二叉平衡树的平衡因子计算准则。',
      difficulty: 4,
      answer: '平衡因子等于左子树高度减去右子树高度，绝对值不超过1。',
      analysis: '平衡因子用于在AVL树插入节点时判断是否需要旋转调整。',
    };

    const mockSession: Partial<PracticeSession> = {
      id: 'prac_exp_01',
      title: '算法练习',
      questions: [],
      items: [
        {
          attempt_item_id: 'att_exp_01',
          question_id: 'q_exp_01',
          order_index: 2,
          score: 3.5,
          max_score: 5.0,
          user_answer: '左子树高度减右子树高度',
          hit_keywords: ['子树高度'],
          missing_keywords: ['绝对值不超过1'],
          source_snippet: {
            chapter_title: '第 4 章 平衡二叉树',
            page_index: 88,
            snippet_content: 'AVL树中任意节点的左右子树高度差绝对值不超过1。',
          },
          question_snapshot: {
            stem: mockQuestion.stem,
            question_type: 'short_answer',
            difficulty: 4,
            answer: mockQuestion.answer,
            analysis: mockQuestion.analysis,
          },
        },
      ],
    };

    it('renders explanation details with keywords, snippets, and correction buttons', async () => {
      vi.spyOn(practiceApi, 'fetchPracticeSession').mockResolvedValue({
        code: 0,
        message: 'success',
        data: mockSession as PracticeSession,
      });

      vi.spyOn(questionApi, 'fetchQuestionDetail').mockResolvedValue({
        code: 0,
        message: 'success',
        data: mockQuestion,
      });

      const wrapper = mount(ExplanationPage, {
        props: {
          practiceId: 'prac_exp_01',
          questionId: 'q_exp_01',
        },
      });

      // Trigger loadExplanationData
      await vi.runAllTimersAsync();

      expect(wrapper.find('.stem-card').text()).toContain(mockQuestion.stem);
      expect(wrapper.find('.comparison-card').text()).toContain('左子树高度减右子树高度');
      expect(wrapper.find('.rubric-card').text()).toContain('命中采分点：子树高度');
      expect(wrapper.find('.rubric-card').text()).toContain('遗漏采分点：绝对值不超过1');
      expect(wrapper.find('.snippet-card').text()).toContain('第 4 章 平衡二叉树');
      expect(wrapper.find('.action-buttons-card').exists()).toBe(true);

      // Modals open
      const selfGradeBtn = wrapper.find('.btn-self-grade');
      await selfGradeBtn.trigger('tap');
      expect(wrapper.findComponent({ name: 'SelfGradeModal' }).props('visible')).toBe(true);

      const regradeBtn = wrapper.find('.btn-regrade');
      await regradeBtn.trigger('tap');
      expect(wrapper.findComponent({ name: 'RegradeModal' }).props('visible')).toBe(true);
    });
  });
});
