import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import OriginalSnippetDrawer from '@/subpackages/report/components/OriginalSnippetDrawer.vue';
import GradingResultList from '@/subpackages/report/components/GradingResultList.vue';
import type { AttemptGradingItem } from '@/types/report';

describe('Grading Results & Original Snippet Components', () => {
  describe('OriginalSnippetDrawer.vue', () => {
    it('controls visibility and renders meta info correctly', async () => {
      const wrapper = mount(OriginalSnippetDrawer, {
        props: {
          visible: true,
          chapterTitle: '第 3 章 树与二叉树',
          pageIndex: 42,
          snippetContent: '二叉树的中序遍历是先左子树后根节点再右子树。',
          highlightKeywords: ['中序遍历', '左子树'],
        },
      });

      expect(wrapper.classes()).toContain('visible');
      expect(wrapper.find('.snippet-drawer-sheet').classes()).toContain('visible');
      expect(wrapper.text()).toContain('章节：第 3 章 树与二叉树');
      expect(wrapper.text()).toContain('第 42 页');

      // Verify safe highlighted segments
      const highlighted = wrapper.findAll('.highlighted-keyword');
      expect(highlighted.length).toBe(2);
      expect(highlighted.map((el) => el.text())).toContain('中序遍历');
      expect(highlighted.map((el) => el.text())).toContain('左子树');

      // Trigger close button
      const closeBtn = wrapper.find('.close-btn');
      await closeBtn.trigger('tap');
      expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
      expect(wrapper.emitted('close')).toBeTruthy();
    });

    it('renders empty placeholder when content is empty', () => {
      const wrapper = mount(OriginalSnippetDrawer, {
        props: {
          visible: true,
          snippetContent: '',
        },
      });

      expect(wrapper.text()).toContain('暂无原文切片内容');
    });
  });

  describe('GradingResultList.vue', () => {
    it('renders empty placeholder when items list is empty', () => {
      const wrapper = mount(GradingResultList, {
        props: {
          items: [],
        },
      });

      expect(wrapper.find('.empty-state').exists()).toBe(true);
      expect(wrapper.text()).toContain('暂无题目作答记录');
    });

    it('renders items with correct statuses, keyword capsules, and emits user actions', async () => {
      const mockItems: AttemptGradingItem[] = [
        {
          attempt_item_id: 'att_1',
          order_index: 1,
          status: 'graded',
          score: 1.0,
          max_score: 1.0,
          user_answer: 'A',
          question_snapshot: {
            stem: '以下哪项属于进程的特征？',
            question_type: 'single_choice',
            answer: 'A',
            analysis: '进程具有动态性与并发性。',
            source_snippet_id: 'snip_001',
          },
        },
        {
          attempt_item_id: 'att_2',
          order_index: 2,
          status: 'pending_regrade',
          score: null,
          max_score: 5.0,
          user_answer: '采用递归回溯求解',
          question_snapshot: {
            stem: '请阐述快速排序的递归基设计思想。',
            question_type: 'short_answer',
            answer: '当子数组长度小于等于1时直接返回。',
            analysis: '核心在于分治策略与基准元素选取。',
            hit_keywords: ['递归回溯'],
            missing_keywords: ['基准元素', '子数组长度'],
          },
        },
      ];

      const wrapper = mount(GradingResultList, {
        props: {
          items: mockItems,
        },
      });

      const cards = wrapper.findAll('.result-card');
      expect(cards.length).toBe(2);

      // First card: Objective question, correct
      expect(cards[0].text()).toContain('第 1 题');
      expect(cards[0].text()).toContain('单选题');
      expect(cards[0].text()).toContain('判对');
      expect(cards[0].text()).toContain('1 / 1 分');
      expect(cards[0].find('.snippet-btn').exists()).toBe(true);
      expect(cards[0].find('.self-grade-btn').exists()).toBe(false);

      // Second card: Subjective question, pending regrade
      expect(cards[1].text()).toContain('第 2 题');
      expect(cards[1].text()).toContain('简答题');
      expect(cards[1].text()).toContain('待重新判题');
      expect(cards[1].text()).toContain('待判定');
      expect(cards[1].text()).toContain('已命中：递归回溯');
      expect(cards[1].text()).toContain('遗漏：基准元素');
      expect(cards[1].find('.self-grade-btn').exists()).toBe(true);
      expect(cards[1].find('.regrade-btn').exists()).toBe(true);

      // Tap actions test
      await cards[0].find('.snippet-btn').trigger('tap');
      expect(wrapper.emitted('view-snippet')).toBeTruthy();
      expect(wrapper.emitted('view-snippet')?.[0]).toEqual([mockItems[0]]);

      await cards[1].find('.self-grade-btn').trigger('tap');
      expect(wrapper.emitted('self-grade')).toBeTruthy();
      expect(wrapper.emitted('self-grade')?.[0]).toEqual([mockItems[1]]);

      await cards[1].find('.regrade-btn').trigger('tap');
      expect(wrapper.emitted('regrade')).toBeTruthy();
      expect(wrapper.emitted('regrade')?.[0]).toEqual([mockItems[1]]);
    });
  });
});
